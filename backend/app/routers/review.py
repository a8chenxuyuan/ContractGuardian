import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.quota import check_page_quota, check_review_quota
from app.core.sse import SSEManager
from app.models.chat import ChatRecord
from app.models.contract import Contract
from app.models.review import Finding, HumanReview, ReviewSession
from app.models.share import ShareLink
from app.models.user import User
from app.review.quick_lane import citations_from_answer, quick_answer
from app.review.report import ReportService
from app.routers.admin import get_current_admin
from app.routers.auth import get_current_active_user, resolve_user_from_token
from app.schemas.review import (
    AskIn,
    AskOut,
    FindingStatusIn,
    RectificationOut,
    ReviewDiffIn,
    ReviewFeedbackIn,
    ReviewFeedbackOut,
    ReviewResultOut,
    ReviewStartResponse,
)
from app.tasks.celery_tasks import review_contract_task

router = APIRouter()
settings = get_settings()
sse_manager = SSEManager()
report_service = ReportService()


@router.post("/{contract_id}/review", response_model=ReviewStartResponse)
async def start_review(
    contract_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    body: ReviewDiffIn | None = None,
):
    """启动合同审查；body.base_version 传入历史版本号时执行双版本对比审查。"""
    result = await db.execute(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.owner_id == current_user.id,
            Contract.deleted_at.is_(None),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    if contract.status not in ("parsed", "completed", "failed"):
        raise HTTPException(status_code=400, detail="合同尚未解析完成，请稍后再试")

    # 配额校验：非会员检查月度审查次数与单合同页数上限
    await check_review_quota(db, current_user)
    check_page_quota(current_user, contract.page_count)

    # 对比审查：校验基准版本存在
    base_version = body.base_version if body else None
    if base_version is not None:
        if not any(f.version == base_version for f in contract.files):
            raise HTTPException(status_code=400, detail="基准版本不存在")

    # 创建审查会话
    session = ReviewSession(contract_id=contract.id, status="pending", base_version=base_version)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # 触发异步审查任务
    # 如果 Redis/Celery broker 不可用，则降级为当前进程同步执行
    try:
        review_contract_task.delay(contract.id, session.id)
    except Exception:
        review_contract_task.run(contract.id, session.id)

    return ReviewStartResponse(
        review_session_id=session.id,
        message="审查任务已启动",
    )


@router.post("/{review_session_id}/cancel")
async def cancel_review(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """取消进行中的审查（软中断：Celery 任务在阶段边界检测到 cancelled 后停止）。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")
    if session.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="审查已结束，无法取消")

    session.status = "cancelled"
    session.fail_reason = "cancelled"

    # 回退合同状态，避免合同卡在 reviewing 无法重新发起审查
    contract_result = await db.execute(
        select(Contract).where(Contract.id == session.contract_id)
    )
    contract = contract_result.scalar_one_or_none()
    if contract and contract.status == "reviewing":
        has_completed = await db.scalar(
            select(ReviewSession.id).where(
                ReviewSession.contract_id == contract.id,
                ReviewSession.status == "completed",
                ReviewSession.id != session.id,
            )
        )
        contract.status = "completed" if has_completed else "parsed"

    await db.commit()
    return {"id": session.id, "status": "cancelled", "fail_reason": "cancelled"}


@router.get("/{review_session_id}/diff")
async def get_review_diff(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取对比审查的条款级 diff 结果（仅对比审查会话有数据）。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")
    return {
        "base_version": session.base_version,
        "status": session.status,
        "diff": session.diff_summary,
    }


@router.get("/{review_session_id}/stream")
async def review_stream(
    review_session_id: int,
    token: Annotated[str, Query(description="JWT Token（EventSource 无法携带 Header，改用 query 传递）")],
    db: AsyncSession = Depends(get_db),
):
    """SSE 实时推送审查进度（带鉴权：token + 归属校验）。"""
    # EventSource 不支持自定义 Header，通过 query 参数传递 token
    user = await resolve_user_from_token(token, db)
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    async def event_generator():
        # 先推送当前状态
        yield f"data: {{\"event\": \"phase\", \"data\": {{\"phase\": \"{session.status}\", \"message\": \"当前状态\"}}}}\n\n"
        # 订阅 Redis 频道，并把 AgentBus 事件格式转换为前端期望格式
        async for raw in sse_manager.subscribe(review_session_id):
            try:
                event = json.loads(raw.replace("data: ", "", 1))
            except Exception:
                continue

            event_type = event.get("event_type", "")
            payload = event.get("payload", {})

            if event_type == "phase_changed":
                yield f"data: {{\"event\": \"phase\", \"data\": {json.dumps(payload, ensure_ascii=False)}}}\n\n"
            elif event_type == "finding_added":
                finding = payload.get("finding", {})
                yield f"data: {{\"event\": \"finding_added\", \"data\": {json.dumps(finding, ensure_ascii=False)}}}\n\n"
            elif event_type == "completed":
                yield f"data: {{\"event\": \"completed\", \"data\": {json.dumps(payload, ensure_ascii=False)}}}\n\n"
            elif event_type == "cancelled":
                yield (
                    "data: {\"event\": \"phase\", \"data\": "
                    + json.dumps({"phase": "cancelled", "message": "审查已取消"}, ensure_ascii=False)
                    + "}\n\n"
                )
            elif event_type == "error":
                # 错误详情不透传给前端（可能含服务商内部信息），统一展示通用文案
                yield (
                    "data: {\"event\": \"phase\", \"data\": "
                    + json.dumps(
                        {"phase": "failed", "message": "审查出现错误，请稍后重试"},
                        ensure_ascii=False,
                    )
                    + "}\n\n"
                )
            else:
                # 其他事件类型原样透传
                yield raw

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/{review_session_id}/result", response_model=ReviewResultOut)
async def get_review_result(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取审查结果。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")
    return session


async def _deep_ask(
    session: ReviewSession, question: str, user_id: int, db: AsyncSession
) -> str | None:
    """深潜问答：用 ChatAgent 基于已持久化的审查风险图回答。

    任何失败返回 None，调用方照旧使用 quick_lane 的 degraded 文案（不阻断追问）。
    """
    from app.agentkit.session_graph import SessionGraph
    from app.review.agents.chat import ChatAgent

    try:
        graph = SessionGraph.from_dict(session.graph_data)
        history_result = await db.execute(
            select(ChatRecord)
            .where(
                ChatRecord.contract_id == session.contract_id,
                ChatRecord.user_id == user_id,
            )
            .order_by(ChatRecord.created_at.desc())
            .limit(6)
        )
        records = list(reversed(history_result.scalars().all()))  # 恢复时间正序
        chat_history = [
            {"role": r.role, "content": r.question if r.role == "user" else (r.answer or "")}
            for r in records
        ]
        agent = ChatAgent()
        result = await agent.run(
            graph,
            {"question": question, "chat_history": chat_history, "user_id": user_id},
        )
        output = result.get("output") or {}
        return output.get("answer") or None
    except Exception:  # noqa: BLE001 —— 深潜失败降级回快车道文案，不阻断追问
        return None


@router.post("/{review_session_id}/ask", response_model=AskOut)
async def ask_about_finding(
    review_session_id: int,
    body: AskIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """划词追问：携带风险发现上下文的快车道问答（CRAG 检索 + 单次生成 + 强制引用）。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    extra_context = None
    if body.finding_id is not None:
        finding_result = await db.execute(
            select(Finding).where(
                Finding.id == body.finding_id,
                Finding.review_session_id == review_session_id,
            )
        )
        finding = finding_result.scalar_one_or_none()
        if not finding:
            raise HTTPException(status_code=404, detail="风险发现不存在")
        extra_context = (
            f"风险类型：{finding.risk_type}（{finding.level}）\n"
            f"风险说明：{finding.reason or ''}\n"
            f"涉及条款：{finding.clause_text or ''}\n"
            f"法律依据：{', '.join(finding.law_refs or [])}"
        )

    qa = await quick_answer(
        question=body.question,
        contract_id=session.contract_id,
        selected_text=body.selected_text,
        extra_context=extra_context,
        user_id=current_user.id,
    )
    answer = qa["answer"]
    degraded = qa["degraded"]
    references = citations_from_answer(answer, qa["citations"])

    # 深潜回落：知识库两轮检索仍不足时，改用 ChatAgent 基于审查风险图作答
    #（图已在 ReviewSession.graph_data 持久化，无需额外落盘）
    if degraded and session.graph_data:
        deep_answer = await _deep_ask(session, body.question, current_user.id, db)
        if deep_answer:
            answer, references, degraded = deep_answer, [], False

    # 追问记录复用 ChatRecord 落库，随合同对话历史留存
    db.add(
        ChatRecord(
            contract_id=session.contract_id,
            user_id=current_user.id,
            role="user",
            question=body.question,
            selected_text=body.selected_text,
        )
    )
    db.add(
        ChatRecord(
            contract_id=session.contract_id,
            user_id=current_user.id,
            role="assistant",
            answer=qa["answer"],
            references=references,
        )
    )
    await db.commit()

    return AskOut(answer=answer, references=references, degraded=degraded)


@router.get("/{review_session_id}/findings")
async def list_findings(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取审查会话的风险发现列表。"""
    result = await db.execute(
        select(Finding)
        .join(Contract)
        .where(
            Finding.review_session_id == review_session_id,
            Contract.owner_id == current_user.id,
        )
        .order_by(Finding.id)
    )
    return result.scalars().all()


@router.put("/findings/{finding_id}/status")
async def update_finding_status(
    finding_id: int,
    body: FindingStatusIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """更新风险项整改状态（归属校验；PUT 写操作由审计中间件记录）。"""
    result = await db.execute(
        select(Finding)
        .join(Contract, Finding.contract_id == Contract.id)
        .where(Finding.id == finding_id, Contract.owner_id == current_user.id)
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="风险发现不存在")

    finding.status = body.status
    finding.resolution_note = body.note
    finding.resolved_at = datetime.now(timezone.utc) if body.status == "resolved" else None
    await db.commit()
    await db.refresh(finding)

    return {
        "id": finding.id,
        "status": finding.status,
        "resolution_note": finding.resolution_note,
        "resolved_at": finding.resolved_at,
    }


@router.get("/{review_session_id}/rectification", response_model=RectificationOut)
async def get_rectification(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取审查会话的整改进度统计（已关闭 = 已整改 + 已忽略误报）。"""
    owner_result = await db.execute(
        select(ReviewSession.id)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    if owner_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    rows = await db.execute(
        select(Finding.status, func.count())
        .where(Finding.review_session_id == review_session_id)
        .group_by(Finding.status)
    )
    counts = {status: count for status, count in rows.all()}
    total = sum(counts.values())
    closed = counts.get("resolved", 0) + counts.get("dismissed", 0)
    return RectificationOut(
        total=total,
        active=counts.get("active", 0),
        confirmed=counts.get("confirmed", 0),
        dismissed=counts.get("dismissed", 0),
        resolved=counts.get("resolved", 0),
        close_rate=round(closed / total * 100, 2) if total else 0.0,
    )


@router.post("/{review_session_id}/share")
async def create_share_link(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """创建报告分享链接（7 天有效，免登录只读）。同一会话重复创建时旧链接立即失效。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    now = datetime.now(timezone.utc)
    # 旧链接置为已过期（替换语义，避免同一会话多个有效链接并存）
    old_links = await db.execute(
        select(ShareLink).where(
            ShareLink.review_session_id == review_session_id,
            ShareLink.expires_at > now,
        )
    )
    for link in old_links.scalars():
        link.expires_at = now

    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=7)
    db.add(
        ShareLink(
            token=token,
            review_session_id=review_session_id,
            contract_id=session.contract_id,
            created_by=current_user.id,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return {"token": token, "url": f"/share/{token}", "expires_at": expires_at}


@router.get("/share/{token}")
async def get_shared_report(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """免登录只读获取分享的报告（token 过期返回 410）。"""
    result = await db.execute(select(ShareLink).where(ShareLink.token == token))
    link = result.scalar_one_or_none()
    if not link or link.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="分享链接已失效或已过期")

    session = await db.get(ReviewSession, link.review_session_id)
    contract = await db.get(Contract, link.contract_id)
    if not session or not contract:
        raise HTTPException(status_code=410, detail="分享的报告已不存在")

    return {
        "contract_filename": contract.filename,
        "status": session.status,
        "completed_at": session.completed_at,
        "base_version": session.base_version,
        "findings": session.findings or [],
        "stats": session.stats or {},
        "diff": session.diff_summary,
        "expires_at": link.expires_at,
    }


@router.post("/{review_session_id}/export")
async def export_report(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    format: str = "pdf",
):
    """导出审查报告。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    session_dict = {
        "id": session.id,
        "findings": session.findings,
        "stats": session.stats,
    }

    if format == "pdf":
        if not report_service.pdf_available:
            raise HTTPException(
                status_code=503,
                detail="PDF 导出服务当前不可用：缺少 PDF 渲染依赖（WeasyPrint 或 xhtml2pdf）。请使用导出 Word，或在服务器上安装依赖。",
            )
        path = report_service.generate_pdf(session_dict)
    elif format == "word":
        path = report_service.generate_word(session_dict)
    else:
        raise HTTPException(status_code=400, detail="不支持的导出格式")

    return FileResponse(path, filename=f"report_{session.id}.{format}", media_type="application/octet-stream")


@router.get("/{review_session_id}/export/marked")
async def export_marked_report(
    review_session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """导出修订版 Word 报告：条款原文按风险等级色标标注，附风险说明与修改建议块。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    session_dict = {"id": session.id, "findings": session.findings, "stats": session.stats}
    path = report_service.generate_marked_word(session_dict)
    return FileResponse(
        path,
        filename=f"marked_report_{session.id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.post("/{review_session_id}/feedback", response_model=ReviewFeedbackOut)
async def submit_feedback(
    review_session_id: int,
    feedback: ReviewFeedbackIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """提交对审查结果的人工反馈。"""
    result = await db.execute(
        select(ReviewSession)
        .join(Contract)
        .where(
            ReviewSession.id == review_session_id,
            Contract.owner_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="审查会话不存在")

    # 如果指定了 finding_id，校验其存在性并更新状态
    if feedback.finding_id is not None:
        finding_result = await db.execute(
            select(Finding).where(
                Finding.id == feedback.finding_id,
                Finding.review_session_id == review_session_id,
            )
        )
        finding = finding_result.scalar_one_or_none()
        if not finding:
            raise HTTPException(status_code=404, detail="风险发现不存在")
        finding.status = "confirmed" if feedback.is_correct else "dismissed"
        if feedback.correct_label:
            finding.level = feedback.correct_label
        if not feedback.is_correct:
            # 误报反馈落入跨会话记忆，后续提问时注入抑制该类风险
            from app.agentkit.memory import add_memory

            add_memory(
                current_user.id,
                "dismissed_risk",
                f"{finding.risk_type}：{(finding.clause_text or finding.reason or '')[:80]}",
            )

    reason = "用户认为该风险判断正确" if feedback.is_correct else "用户认为该风险判断有误"
    human_review = HumanReview(
        review_session_id=review_session_id,
        finding_id=feedback.finding_id,
        reason=reason,
        status="approved" if feedback.is_correct else "rejected",
        reviewer_id=current_user.id,
        comment=feedback.comment,
    )
    db.add(human_review)
    await db.commit()
    await db.refresh(human_review)

    return human_review


# ---------------------------------------------------------------------------
# 可观测（P2-A）：trace 查询与汇总，仅管理员（调试/验证装配层与 Agent 用量）
# ---------------------------------------------------------------------------


def _read_trace(review_session_id: int) -> list[dict]:
    """从 ReviewLogger 落盘文件读取全量 trace（新实例内存为空，必须读文件）。"""
    from app.review.logger import LOG_DIR

    path = LOG_DIR / f"{review_session_id}.jsonl"
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # 半行写入等损坏行：跳过不阻断查询
    return rows


def _summarize_trace(rows: list[dict]) -> dict:
    """从 trace 行汇总：事件计数、阶段时长、LLM 调用与 token 消耗、风险数量。"""
    event_counts: dict[str, int] = {}
    tokens = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    llm_latencies: list[float] = []
    phases: list[dict] = []
    finding_count: int | None = None

    for row in rows:
        event_type = row.get("event_type", "unknown")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
        payload = row.get("payload") or {}
        if event_type == "llm_usage":
            tokens["calls"] += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                tokens[key] += payload.get(key) or 0
        elif event_type == "llm_raw" and payload.get("latency") is not None:
            llm_latencies.append(payload["latency"])
        elif event_type == "phase_changed":
            phases.append({"phase": payload.get("phase"), "at": row.get("elapsed", 0)})
        elif event_type == "final_findings":
            finding_count = payload.get("finding_count")

    # 阶段时长 = 相邻 phase_changed 事件的时间差分
    phase_durations = [
        {
            "phase": phases[i]["phase"],
            "started_at": phases[i]["at"],
            "duration": round(phases[i + 1]["at"] - phases[i]["at"], 3),
        }
        for i in range(len(phases) - 1)
    ]

    return {
        "review_session_id": rows[0].get("review_session_id"),
        "total_events": len(rows),
        "elapsed_total": rows[-1].get("elapsed"),
        "event_counts": event_counts,
        "phase_durations": phase_durations,
        "llm": {
            "calls": len(llm_latencies),
            "avg_latency": round(sum(llm_latencies) / len(llm_latencies), 3)
            if llm_latencies
            else None,
        },
        "tokens": tokens,
        "finding_count": finding_count,
    }


@router.get("/{review_session_id}/trace")
async def get_review_trace(
    review_session_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    limit: int = 500,
) -> dict:
    """查看审查 trace 事件流（尾部 limit 条，管理员专用）。"""
    rows = _read_trace(review_session_id)
    if not rows:
        raise HTTPException(status_code=404, detail="该审查会话暂无 trace 记录")
    return {"total": len(rows), "events": rows[-limit:]}


@router.get("/{review_session_id}/trace/summary")
async def get_review_trace_summary(
    review_session_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """trace 汇总：阶段时长、LLM 调用/延迟、token 消耗、事件计数（管理员专用）。"""
    rows = _read_trace(review_session_id)
    if not rows:
        raise HTTPException(status_code=404, detail="该审查会话暂无 trace 记录")
    return _summarize_trace(rows)
