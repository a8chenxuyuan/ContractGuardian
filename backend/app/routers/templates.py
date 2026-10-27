from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.template import ContractTemplate
from app.models.user import User
from app.review.report import ReportService
from app.routers.auth import get_current_active_user

router = APIRouter()


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(min_length=2, max_length=100)
    scene: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=50)


def _visible_scope(current_user: User):
    """预置范本人人可见，用户模板仅本人可见。"""
    return or_(
        ContractTemplate.is_preset.is_(True),
        ContractTemplate.user_id == current_user.id,
    )


def _to_dict(t: ContractTemplate, include_content: bool = False) -> dict:
    data = {
        "id": t.id,
        "name": t.name,
        "category": t.category,
        "scene": t.scene,
        "is_preset": t.is_preset,
        "usage_count": t.usage_count,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if include_content:
        data["content"] = t.content
    return data


@router.get("")
async def list_templates(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 12,
    keyword: str | None = None,
    category: str | None = None,
    mine: bool = False,
):
    """模板列表：预置范本 + 本人上传模板，支持关键词/分类筛选与仅看我的。"""
    stmt = select(ContractTemplate).where(_visible_scope(current_user))
    if mine:
        stmt = stmt.where(ContractTemplate.user_id == current_user.id, ContractTemplate.is_preset.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                ContractTemplate.name.ilike(kw),
                ContractTemplate.category.ilike(kw),
                ContractTemplate.scene.ilike(kw),
            )
        )
    if category:
        stmt = stmt.where(ContractTemplate.category == category)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    items = (
        await db.execute(
            stmt.order_by(ContractTemplate.is_preset.desc(), ContractTemplate.id.desc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return {"total": total, "items": [_to_dict(t) for t in items]}


@router.get("/categories")
async def list_categories(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """分类及数量（当前用户可见范围内）。"""
    rows = await db.execute(
        select(ContractTemplate.category, func.count())
        .where(_visible_scope(current_user))
        .group_by(ContractTemplate.category)
        .order_by(func.count().desc())
    )
    return [{"category": c, "count": n} for c, n in rows.all()]


@router.post("")
async def create_template(
    body: TemplateIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """上传自定义模板（私有，仅本人可见与删除）。"""
    tpl = ContractTemplate(
        name=body.name.strip(),
        category=body.category.strip(),
        scene=(body.scene or "").strip(),
        content=body.content,
        is_preset=False,
        user_id=current_user.id,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return _to_dict(tpl, include_content=True)


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    tpl = (
        await db.execute(
            select(ContractTemplate).where(
                ContractTemplate.id == template_id, _visible_scope(current_user)
            )
        )
    ).scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在或无权访问")
    return _to_dict(tpl, include_content=True)


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """仅允许删除本人上传的模板；预置范本不可删。"""
    tpl = await db.get(ContractTemplate, template_id)
    if not tpl or tpl.is_preset:
        raise HTTPException(status_code=403, detail="预置范本不可删除或模板不存在")
    if tpl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="模板不存在或无权访问")
    await db.delete(tpl)
    await db.commit()
    return {"ok": True}


@router.get("/{template_id}/download")
async def download_template(
    template_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """下载模板为 docx，并累加使用次数。"""
    tpl = (
        await db.execute(
            select(ContractTemplate).where(
                ContractTemplate.id == template_id, _visible_scope(current_user)
            )
        )
    ).scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在或无权访问")
    tpl.usage_count = (tpl.usage_count or 0) + 1
    await db.commit()
    path = ReportService.template_to_docx(tpl.name, tpl.content)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{tpl.name}.docx",
    )
