from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.knowledge import KnowledgeArticle
from app.models.user import User
from app.routers.auth import get_current_active_user

router = APIRouter()


@router.get("/articles")
async def list_articles(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    keyword: str | None = None,
    category: str | None = None,
):
    """法规条目检索（登录用户可用，支持关键词与分类筛选）。"""
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
    items = (
        await db.execute(stmt.order_by(KnowledgeArticle.id).offset(skip).limit(limit))
    ).scalars().all()
    return {"total": total, "items": items}


@router.get("/categories")
async def list_categories(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """法规分类及条数（筛选 chips 用）。"""
    rows = await db.execute(
        select(KnowledgeArticle.category, func.count())
        .group_by(KnowledgeArticle.category)
        .order_by(func.count().desc())
    )
    return [{"category": c, "count": n} for c, n in rows.all()]
