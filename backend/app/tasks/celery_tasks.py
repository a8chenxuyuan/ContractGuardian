from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "contract_guard",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 回收站定期清理：每 6 小时检查一次，彻底删除软删除超过 30 天的合同
    beat_schedule={
        "cleanup-trash-every-6h": {
            "task": "app.tasks.celery_tasks.cleanup_trash_task",
            "schedule": 6 * 60 * 60,
        },
        # 履约日期管家：每天 09:00 检查 30 天内到期日期并推送站内提醒
        "check-key-dates-daily": {
            "task": "app.tasks.celery_tasks.check_key_dates_task",
            "schedule": crontab(hour=9, minute=0),
        },
    },
)


@celery_app.task
def cleanup_trash_task():
    """清理回收站：彻底删除软删除超过 30 天的合同（文件+记录+向量）。"""
    from datetime import datetime, timedelta

    from sqlalchemy import create_engine, select
    from sqlalchemy import delete as sa_delete
    from sqlalchemy.orm import sessionmaker

    sync_engine = create_engine(settings.SYNC_DATABASE_URL)
    Session = sessionmaker(bind=sync_engine)
    db = Session()
    purged = 0
    try:
        from app.models.chat import ChatRecord
        from app.models.contract import Contract

        cutoff = datetime.utcnow() - timedelta(days=30)
        contracts = db.execute(
            select(Contract).where(Contract.deleted_at.is_not(None), Contract.deleted_at < cutoff)
        ).scalars().all()

        if contracts:
            from app.rag.vector_store import get_vector_store

            store = get_vector_store()
            for contract in contracts:
                # 磁盘文件
                for f in contract.files:
                    try:
                        import os

                        if os.path.exists(f.storage_path):
                            os.remove(f.storage_path)
                    except OSError:
                        pass
                # 向量数据
                try:
                    store.delete_contract_clauses(contract.id)
                except Exception:
                    pass
                # 对话记录无 ORM 级联，手动清理
                db.execute(sa_delete(ChatRecord).where(ChatRecord.contract_id == contract.id))
                db.delete(contract)
                purged += 1
            db.commit()
        return {"status": "success", "purged": purged}
    finally:
        db.close()
        sync_engine.dispose()


@celery_app.task(bind=True, max_retries=2)
def parse_contract_task(self, contract_id: int, file_path: str, file_type: str):
    """异步解析合同任务。

    调用文档解析引擎，生成 Section 树、Chunk 列表、BBox 坐标和向量索引。
    解析完成后把结果写回 contracts.parsed_data。
    """
    from app.contracts.parser import ContractParser

    try:
        parser = ContractParser()
        result = parser.parse(file_path, file_type)

        # 同步写回数据库
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        sync_engine = create_engine(settings.SYNC_DATABASE_URL)
        Session = sessionmaker(bind=sync_engine)
        db = Session()
        try:
            from app.models.contract import Contract

            contract = db.query(Contract).filter(Contract.id == contract_id).first()
            if contract:
                contract.status = "parsed"
                contract.page_count = result.get("page_count")
                contract.parsed_data = result
                db.commit()
        finally:
            db.close()
            sync_engine.dispose()

        return {"status": "success", "contract_id": contract_id}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)


def _auto_resolve_findings(db, contract_id: int, current_session_id: int, changes: list) -> int:
    """整改自动核对：旧会话的风险条款在新版本中被删除/修改时，自动关闭对应风险项。

    匹配策略：diff 中 removed/modified 的基准条款文本（已截断 500 字）与旧 finding
    的 clause_text 做归一化子串匹配，未命中再按前 300 字相似度 >= 0.8 兜底。
    """
    from datetime import datetime
    from difflib import SequenceMatcher

    from sqlalchemy import select

    from app.models.review import Finding

    def _norm(text: str | None) -> str:
        return "".join((text or "").split())

    base_texts = [
        _norm(c.get("base", {}).get("text"))
        for c in changes
        if c.get("type") in ("removed", "modified") and c.get("base")
    ]
    base_texts = [t for t in base_texts if t]
    if not base_texts:
        return 0

    old_findings = db.execute(
        select(Finding).where(
            Finding.contract_id == contract_id,
            Finding.review_session_id != current_session_id,
            Finding.status.in_(["active", "confirmed"]),
        )
    ).scalars().all()

    resolved = 0
    for finding in old_findings:
        clause_norm = _norm(finding.clause_text)
        if not clause_norm:
            continue
        hit = any(
            base[:150] in clause_norm
            or SequenceMatcher(None, base[:300], clause_norm[:300]).ratio() >= 0.8
            for base in base_texts
        )
        if hit:
            finding.status = "resolved"
            finding.resolution_note = (
                f"自动核对：该风险条款在新版本审查（会话#{current_session_id}）中已被删除或修改"
            )
            finding.resolved_at = datetime.utcnow()
            resolved += 1
    return resolved


@celery_app.task
def check_key_dates_task():
    """履约日期管家：检查 30 天内到期的关键日期，推送站内提醒（按 key_date id 查重）。"""
    from datetime import date, timedelta

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    sync_engine = create_engine(settings.SYNC_DATABASE_URL)
    Session = sessionmaker(bind=sync_engine)
    db = Session()
    notified = 0
    try:
        from app.models.contract import Contract
        from app.models.key_date import KeyDate
        from app.models.notify import Notification

        today = date.today()
        deadline = today + timedelta(days=30)
        rows = db.execute(
            select(KeyDate, Contract)
            .join(Contract, KeyDate.contract_id == Contract.id)
            .where(
                KeyDate.date_type == "expiry",
                KeyDate.date_value >= today,
                KeyDate.date_value <= deadline,
                Contract.deleted_at.is_(None),
            )
        ).all()

        for key_date, contract in rows:
            exists = db.execute(
                select(Notification.id).where(
                    Notification.type == "key_date",
                    Notification.related_id == key_date.id,
                )
            ).scalar_one_or_none()
            if exists:
                continue
            days_left = (key_date.date_value - today).days
            db.add(
                Notification(
                    user_id=contract.owner_id,
                    title="履约日期提醒",
                    content=(
                        f"《{contract.filename}》的到期日 {key_date.date_value.isoformat()}"
                        f"（{key_date.raw_text}）还有 {days_left} 天到达，请及时跟进。"
                    ),
                    type="key_date",
                    contract_id=contract.id,
                    related_id=key_date.id,
                )
            )
            notified += 1
        db.commit()
        return {"status": "success", "notified": notified}
    finally:
        db.close()
        sync_engine.dispose()


# 失败原因 → 用户可读文案（站内通知使用）
FAIL_REASON_TEXT = {
    "timeout": "审查超时（模型服务响应过慢或超出任务时限）",
    "quota": "模型服务额度不足",
    "permission": "模型服务鉴权失败（请检查 API Key 配置）",
    "provider": "模型服务暂时不可用",
    "internal": "系统内部错误",
}


def _classify_failure(exc: Exception) -> str:
    """把异常归类为 cancelled/timeout/quota/permission/provider/internal，驱动重试与前端文案。"""
    import asyncio

    import openai

    from app.review.graph import ReviewCancelledError

    if isinstance(exc, ReviewCancelledError):
        return "cancelled"
    from celery.exceptions import SoftTimeLimitExceeded

    if isinstance(exc, SoftTimeLimitExceeded):
        return "timeout"
    # openai SDK 异常优先按类型细分
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return "permission"
    if isinstance(exc, openai.RateLimitError):
        # 429 里"额度耗尽"不可重试，普通限流归为服务商波动可重试
        return "quota" if "insufficient_quota" in str(exc).lower() else "provider"
    if isinstance(exc, (openai.APITimeoutError, asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, (openai.APIConnectionError, openai.InternalServerError)):
        return "provider"
    # 非 SDK 异常按报错文本兜底归类
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "401" in text or "403" in text or "invalid api key" in text:
        return "permission"
    if "quota" in text or "402" in text:
        return "quota"
    return "internal"


def _revert_contract_status(db, contract) -> None:
    """审查中断/失败后回退合同状态，避免合同卡在 reviewing 无法重新发起审查。"""
    from sqlalchemy import select

    from app.models.review import ReviewSession

    if contract is None:
        return
    has_completed = db.execute(
        select(ReviewSession.id)
        .where(ReviewSession.contract_id == contract.id, ReviewSession.status == "completed")
        .limit(1)
    ).scalar_one_or_none()
    contract.status = "completed" if has_completed else "parsed"


@celery_app.task(
    bind=True,
    max_retries=settings.REVIEW_MAX_RETRIES,
    soft_time_limit=settings.REVIEW_SOFT_TIME_LIMIT,
)
def review_contract_task(self, contract_id: int, review_session_id: int):
    """异步审查合同任务。

    调用 AI 审查引擎（Agent 模块）进行真实审查，
    并将结果写回 ReviewSession 和 Finding 表。
    """
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_engine = create_engine(settings.SYNC_DATABASE_URL)
    Session = sessionmaker(bind=sync_engine)
    db = Session()
    session = None
    try:
        from datetime import datetime

        from app.models.contract import Contract
        from app.models.notify import Notification
        from app.models.review import Finding, ReviewSession

        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        session = db.query(ReviewSession).filter(ReviewSession.id == review_session_id).first()
        if not contract or not session:
            return {"status": "failed", "reason": "not found"}

        # 排队/重试等待期间被用户取消：直接退出，不再执行
        if session.status == "cancelled":
            return {"status": "cancelled", "review_session_id": review_session_id}

        parsed_data = contract.parsed_data or {}
        chunks = parsed_data.get("chunks", [])
        section_tree = parsed_data.get("section_tree", {})
        # 使用解析阶段推断的合同类型（修复原硬编码"劳动合同"的问题）
        contract_type = parsed_data.get("contract_type") or "通用合同"

        # 没有解析结果时直接失败
        if not chunks:
            session.status = "failed"
            session.fail_reason = "internal"
            db.commit()
            return {"status": "failed", "reason": "no parsed chunks"}

        contract.status = "reviewing"
        session.status = "running"
        db.commit()

        # 调用真实 Coordinator（异步函数在同步 Celery 任务中用 asyncio.run 执行）
        from app.review.pipeline import ReviewCoordinator

        async def _run_review():
            coordinator = ReviewCoordinator(config={})
            return await coordinator.run_review(
                contract_id=contract_id,
                chunks=chunks,
                section_tree=section_tree,
                vector_index="default",
                contract_type=contract_type,
                review_session_id=review_session_id,
            )

        review_result = asyncio.run(_run_review())
        findings = review_result.get("findings", [])
        graph_data = review_result.get("graph_data", {})
        stats = review_result.get("stats", {})

        # 将 AgentBus 使用的 session_id 同步为 ReviewSession.id，
        # 确保 SSE 进度推送能收到同一 Redis 频道的消息
        graph_data["session_id"] = review_session_id

        # 写回审查会话
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        session.findings = findings
        session.graph_data = graph_data
        session.stats = stats
        contract.status = "completed"
        contract.risk_summary = stats

        # 对比审查：条款级 diff（基准版本现场重解析，目标用最新解析结果）
        if session.base_version is not None:
            try:
                from app.contracts.diff import diff_clauses, extract_clauses

                base_file = next(
                    (f for f in contract.files if f.version == session.base_version), None
                )
                if base_file:
                    base_clauses = extract_clauses(base_file.storage_path, contract.file_type)
                    target_clauses = parsed_data.get("clauses", [])
                    session.diff_summary = diff_clauses(base_clauses, target_clauses)
            except Exception as exc:  # diff 失败不影响审查主流程
                session.diff_summary = {"summary": None, "changes": [], "error": str(exc)[:200]}

            # 整改自动核对：基准会话中已被删除/修改条款的风险项自动关闭
            if session.diff_summary and session.diff_summary.get("changes"):
                try:
                    resolved = _auto_resolve_findings(
                        db, contract_id, review_session_id, session.diff_summary["changes"]
                    )
                    if resolved:
                        # 新字典触发变更检测（stats 此前已赋给 session.stats，原地改不会标记脏）
                        session.stats = {**stats, "auto_resolved": resolved}
                except Exception:  # 核对失败不影响审查主流程
                    pass

        # 履约日期管家：从条款提取关键日期（覆盖更新该合同的日期集合）
        try:
            from sqlalchemy import delete as sa_delete

            from app.contracts.date_extractor import extract_key_dates
            from app.models.key_date import KeyDate

            new_dates = extract_key_dates(parsed_data.get("clauses", []))
            db.execute(sa_delete(KeyDate).where(KeyDate.contract_id == contract_id))
            for item in new_dates:
                db.add(
                    KeyDate(
                        contract_id=contract_id,
                        review_session_id=review_session_id,
                        date_value=item["date_value"],
                        date_type=item["date_type"],
                        raw_text=item["raw_text"],
                        context=item["context"],
                    )
                )
            expiry = next((d for d in new_dates if d["date_type"] == "expiry"), None)
            contract.nearest_expiry = expiry["date_value"] if expiry else None
        except Exception:  # 日期提取失败不影响审查主流程
            pass

        # 把 findings 写入细粒度表
        db.add_all(
            [
                Finding(
                    review_session_id=review_session_id,
                    contract_id=contract_id,
                    clause_text=f.get("clause_text"),
                    risk_type=f.get("risk_type", "未分类"),
                    level=f.get("level", "low"),
                    confidence=f.get("confidence", 0.0),
                    reason=f.get("reason", ""),
                    law_refs=f.get("law_refs", []),
                    suggestion=f.get("suggestion", {}),
                    bbox=f.get("bbox"),
                )
                for f in findings
            ]
        )
        # 审查完成：写入站内通知
        db.add(
            Notification(
                user_id=contract.owner_id,
                title="合同审查完成",
                content=f"《{contract.filename}》审查完成，共发现 {len(findings)} 个风险项。",
                type="review",
                contract_id=contract_id,
                related_id=review_session_id,
            )
        )
        db.commit()

        return {"status": "success", "review_session_id": review_session_id}
    except Exception as exc:
        reason = _classify_failure(exc)

        # 用户主动取消：cancel 接口已置 cancelled，这里只回退合同状态，不重试、不推通知
        if reason == "cancelled":
            _revert_contract_status(db, contract)
            db.commit()
            return {"status": "cancelled", "review_session_id": review_session_id}

        # 仅超时/服务商波动可重试，指数退避（30s/60s/120s）；重试期间会话回到 pending
        if reason in ("timeout", "provider") and self.request.retries < self.max_retries:
            if session is not None:
                session.status = "pending"
                db.commit()
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))

        # 终态失败：落库失败原因 + 回退合同状态 + 推送带原因的通知
        if session:
            session.status = "failed"
            session.fail_reason = reason
            _revert_contract_status(db, contract)
            if contract:
                db.add(
                    Notification(
                        user_id=contract.owner_id,
                        title="合同审查失败",
                        content=(
                            f"《{contract.filename}》审查未完成："
                            f"{FAIL_REASON_TEXT.get(reason, '未知原因')}，请稍后重试。"
                        ),
                        type="review",
                        contract_id=contract_id,
                        related_id=review_session_id,
                    )
                )
            db.commit()
        raise exc
    finally:
        db.close()
        sync_engine.dispose()
