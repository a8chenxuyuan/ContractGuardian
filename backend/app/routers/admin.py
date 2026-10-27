from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.contract import Contract
from app.models.knowledge import KnowledgeArticle, KnowledgeCase
from app.models.review import Finding, HumanReview, ReviewSession
from app.models.user import User
from app.routers.auth import get_current_active_user, get_password_hash
from app.schemas.user import (
    AdminUserOut,
    PasswordReset,
    UserRoleUpdate,
    UserStatusUpdate,
)

router = APIRouter()


async def get_current_admin(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
    """校验当前用户是否为管理员。"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


# ---------- 用户管理 ----------


@router.get("/users")
async def list_users(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    keyword: str | None = None,
):
    """用户列表（含合同/审查数量统计）。"""
    stmt = select(User)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(User.email.ilike(kw), User.nickname.ilike(kw)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    users = (await db.execute(stmt.order_by(User.id).offset(skip).limit(limit))).scalars().all()

    contract_counts = dict(
        (await db.execute(select(Contract.owner_id, func.count()).group_by(Contract.owner_id))).all()
    )
    review_counts = dict(
        (
            await db.execute(
                select(Contract.owner_id, func.count(ReviewSession.id))
                .join(ReviewSession, ReviewSession.contract_id == Contract.id)
                .group_by(Contract.owner_id)
            )
        ).all()
    )

    items = []
    for user in users:
        item = AdminUserOut.model_validate(user).model_dump(mode="json")
        item["contract_count"] = contract_counts.get(user.id, 0)
        item["review_count"] = review_counts.get(user.id, 0)
        items.append(item)
    return {"total": total, "items": items}


@router.put("/users/{user_id}/status")
async def set_user_status(
    user_id: int,
    body: UserStatusUpdate,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """启用/禁用用户。"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    user = await _get_user_or_404(db, user_id)
    user.is_active = body.is_active
    await db.commit()
    return {"message": "已启用" if body.is_active else "已禁用"}


@router.put("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    body: UserRoleUpdate,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """调整用户角色（管理员/会员）。"""
    if user_id == admin.id and not body.is_admin:
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
    user = await _get_user_or_404(db, user_id)
    user.is_admin = body.is_admin
    user.is_member = body.is_member
    await db.commit()
    return {"message": "角色已更新"}


@router.put("/users/{user_id}/password")
async def reset_user_password(
    user_id: int,
    body: PasswordReset,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """管理员重置用户密码。"""
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    user = await _get_user_or_404(db, user_id)
    user.hashed_password = get_password_hash(body.new_password)
    await db.commit()
    return {"message": "密码已重置"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """删除用户（有合同数据时拒绝，避免悬空引用）。"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    user = await _get_user_or_404(db, user_id)
    contract_count = (
        await db.execute(select(func.count()).where(Contract.owner_id == user_id))
    ).scalar() or 0
    if contract_count > 0:
        raise HTTPException(status_code=400, detail="该用户名下仍有合同数据，请先清理后再删除")
    await db.delete(user)
    await db.commit()
    return {"message": "用户已删除"}


# ---------- 审查记录 ----------


@router.get("/reviews")
async def list_reviews(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
):
    """全平台审查记录列表（带合同文件名与所有者）。"""
    total = (await db.execute(select(func.count()).select_from(ReviewSession))).scalar() or 0
    rows = (
        await db.execute(
            select(ReviewSession, Contract.filename, User.email)
            .join(Contract, ReviewSession.contract_id == Contract.id)
            .join(User, Contract.owner_id == User.id)
            .order_by(desc(ReviewSession.created_at))
            .offset(skip)
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": row.ReviewSession.id,
            "contract_id": row.ReviewSession.contract_id,
            "filename": row.filename,
            "owner": row.email,
            "status": row.ReviewSession.status,
            "created_at": row.ReviewSession.created_at,
            "completed_at": row.ReviewSession.completed_at,
        }
        for row in rows
    ]
    return {"total": total, "items": items}


# ---------- 人工复核 ----------


@router.get("/human-reviews")
async def list_human_reviews(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
):
    """人工复核任务列表。"""
    stmt = select(HumanReview)
    if status:
        stmt = stmt.where(HumanReview.status == status)
    result = await db.execute(stmt.order_by(desc(HumanReview.created_at)))
    return result.scalars().all()


@router.post("/human-reviews/{review_id}/resolve")
async def resolve_human_review(
    review_id: int,
    action: str,
    comment: str | None = None,
    admin: Annotated[User, Depends(get_current_admin)] = None,
    db: AsyncSession = Depends(get_db),
):
    """处理人工复核任务。"""
    result = await db.execute(select(HumanReview).where(HumanReview.id == review_id))
    hr = result.scalar_one_or_none()
    if not hr:
        raise HTTPException(status_code=404, detail="复核任务不存在")
    hr.status = "approved" if action == "approve" else "rejected"
    hr.comment = comment
    hr.reviewer_id = admin.id if admin else None
    hr.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "处理成功"}


# ---------- 知识库管理 ----------


async def _vectorize_articles(records: list[KnowledgeArticle]) -> int:
    """将法条写入 Qdrant 向量库；失败时降级返回 0，不影响 SQL 数据。"""
    if not records:
        return 0
    try:
        from app.rag.vector_store import VectorStore

        articles = [
            {
                "id": r.id,
                "law_name": r.law_name or "",
                "article_number": r.article_number or "",
                "article_title": r.article_title or "",
                "article_text": r.article_text or "",
                "category": r.category or "",
            }
            for r in records
        ]
        return await VectorStore().upsert_knowledge_async(articles)
    except Exception:
        return 0


async def _delete_article_vectors(article_id: int) -> bool:
    """按 payload.article_id 删除对应向量点。"""
    try:
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        from app.rag.vector_store import KNOWLEDGE_COLLECTION, VectorStore

        client = VectorStore()._get_client()
        client.delete(
            collection_name=KNOWLEDGE_COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="article_id", match=MatchValue(value=article_id))]
            ),
        )
        return True
    except Exception:
        return False


@router.get("/knowledge/articles")
async def list_knowledge_articles(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    keyword: str | None = None,
    category: str | None = None,
):
    """法条列表（支持关键词与分类筛选）。"""
    stmt = select(KnowledgeArticle)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                KnowledgeArticle.law_name.ilike(kw),
                KnowledgeArticle.article_number.ilike(kw),
                KnowledgeArticle.article_title.ilike(kw),
                KnowledgeArticle.article_text.ilike(kw),
            )
        )
    if category:
        stmt = stmt.where(KnowledgeArticle.category == category)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    items = (await db.execute(stmt.order_by(KnowledgeArticle.id).offset(skip).limit(limit))).scalars().all()
    return {"total": total, "items": items}


@router.get("/knowledge/cases")
async def list_knowledge_cases(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    keyword: str | None = None,
):
    """案例列表。"""
    stmt = select(KnowledgeCase)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(KnowledgeCase.title.ilike(kw), KnowledgeCase.summary.ilike(kw)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    items = (await db.execute(stmt.order_by(KnowledgeCase.id).offset(skip).limit(limit))).scalars().all()
    return {"total": total, "items": items}


@router.post("/knowledge/articles")
async def create_knowledge_article(
    article: dict,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """新增法条并同步向量化。"""
    record = KnowledgeArticle(
        law_name=article.get("law_name"),
        article_number=article.get("article_number"),
        article_title=article.get("article_title"),
        article_text=article.get("article_text"),
        category=article.get("category", "劳动法"),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    vectorized = await _vectorize_articles([record])
    return {"record": record, "vectorized": vectorized}


@router.put("/knowledge/articles/{article_id}")
async def update_knowledge_article(
    article_id: int,
    article: dict,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """更新法条并重建向量。"""
    result = await db.execute(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="法条不存在")
    for field in ("law_name", "article_number", "article_title", "article_text", "category"):
        if field in article and article[field] is not None:
            setattr(record, field, article[field])
    await db.commit()
    await db.refresh(record)
    vectorized = await _vectorize_articles([record])
    return {"record": record, "vectorized": vectorized}


@router.delete("/knowledge/articles/{article_id}")
async def delete_knowledge_article(
    article_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """删除法条并清理向量。"""
    result = await db.execute(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="法条不存在")
    await db.delete(record)
    await db.commit()
    vector_deleted = await _delete_article_vectors(article_id)
    return {"message": "已删除", "vector_deleted": vector_deleted}


@router.post("/knowledge/cases")
async def create_knowledge_case(
    case: dict,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """新增典型案例。"""
    record = KnowledgeCase(
        title=case.get("title"),
        summary=case.get("summary"),
        court=case.get("court"),
        verdict=case.get("verdict"),
        related_articles=case.get("related_articles", []),
        source_url=case.get("source_url"),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.put("/knowledge/cases/{case_id}")
async def update_knowledge_case(
    case_id: int,
    case: dict,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """更新典型案例。"""
    result = await db.execute(select(KnowledgeCase).where(KnowledgeCase.id == case_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="案例不存在")
    for field in ("title", "summary", "court", "verdict", "related_articles", "source_url"):
        if field in case:
            setattr(record, field, case[field])
    await db.commit()
    await db.refresh(record)
    return record


@router.delete("/knowledge/cases/{case_id}")
async def delete_knowledge_case(
    case_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """删除典型案例。"""
    result = await db.execute(select(KnowledgeCase).where(KnowledgeCase.id == case_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="案例不存在")
    await db.delete(record)
    await db.commit()
    return {"message": "已删除"}


class KnowledgeImportBody(BaseModel):
    """批量导入法条请求体。"""

    articles: list[dict[str, Any]]


@router.post("/knowledge/articles/import")
async def import_knowledge_articles(
    body: KnowledgeImportBody,
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """批量导入法条：按「法名+条号」去重，存在则更新，不存在则新增，最后统一向量化。"""
    imported = updated = skipped = 0
    processed: list[KnowledgeArticle] = []
    for art in body.articles:
        law_name = (art.get("law_name") or "").strip()
        article_number = (art.get("article_number") or "").strip()
        article_text = (art.get("article_text") or "").strip()
        if not law_name or not article_number or not article_text:
            skipped += 1
            continue
        existing = (
            await db.execute(
                select(KnowledgeArticle).where(
                    KnowledgeArticle.law_name == law_name,
                    KnowledgeArticle.article_number == article_number,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.article_title = art.get("article_title") or existing.article_title
            existing.article_text = article_text
            existing.category = art.get("category") or existing.category
            updated += 1
            processed.append(existing)
        else:
            record = KnowledgeArticle(
                law_name=law_name,
                article_number=article_number,
                article_title=art.get("article_title"),
                article_text=article_text,
                category=art.get("category", "劳动法"),
            )
            db.add(record)
            imported += 1
            processed.append(record)
    await db.commit()
    for record in processed:
        await db.refresh(record)
    vectorized = await _vectorize_articles(processed)
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "vectorized": vectorized,
    }


# ---------- 审计日志与统计 ----------


@router.get("/audit-logs")
async def list_audit_logs(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    action: str | None = None,
    keyword: str | None = None,
):
    """审计日志列表（按操作类型/用户筛选）。"""
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(AuditLog.email.ilike(kw), AuditLog.resource.ilike(kw)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    items = (await db.execute(stmt.order_by(desc(AuditLog.id)).offset(skip).limit(limit))).scalars().all()
    return {"total": total, "items": items}


@router.get("/stats")
async def admin_stats(
    admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """管理后台仪表盘统计。"""
    user_total = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    active_users = (
        await db.execute(select(func.count()).select_from(User).where(User.is_active))
    ).scalar() or 0
    contract_total = (await db.execute(select(func.count()).select_from(Contract))).scalar() or 0
    review_total = (await db.execute(select(func.count()).select_from(ReviewSession))).scalar() or 0
    completed_reviews = (
        await db.execute(
            select(func.count()).select_from(ReviewSession).where(ReviewSession.status == "completed")
        )
    ).scalar() or 0

    level_rows = (
        await db.execute(select(Finding.level, func.count()).group_by(Finding.level))
    ).all()
    risk_levels = {level: count for level, count in level_rows}

    since = datetime.now(timezone.utc) - timedelta(days=7)
    trend_rows = (
        await db.execute(
            select(func.date(ReviewSession.created_at), func.count())
            .where(ReviewSession.created_at >= since)
            .group_by(func.date(ReviewSession.created_at))
            .order_by(func.date(ReviewSession.created_at))
        )
    ).all()

    risk_type_rows = (
        await db.execute(
            select(Finding.risk_type, func.count())
            .group_by(Finding.risk_type)
            .order_by(desc(func.count()))
            .limit(5)
        )
    ).all()

    return {
        "user_total": user_total,
        "active_users": active_users,
        "contract_total": contract_total,
        "review_total": review_total,
        "completed_reviews": completed_reviews,
        "risk_levels": {
            "high": risk_levels.get("high", 0),
            "medium": risk_levels.get("medium", 0),
            "low": risk_levels.get("low", 0),
        },
        "review_trend": [
            {"date": str(day), "count": count} for day, count in trend_rows
        ],
        "top_risk_types": [
            {"type": risk_type, "count": count} for risk_type, count in risk_type_rows
        ],
    }
