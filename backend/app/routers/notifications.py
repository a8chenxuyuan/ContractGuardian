from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notify import Notification
from app.models.user import User
from app.routers.auth import get_current_active_user

router = APIRouter()


@router.get("")
async def list_notifications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    is_read: Optional[bool] = None,
):
    """当前用户通知列表（含未读数，可按已读状态过滤）。"""
    base = select(Notification).where(Notification.user_id == current_user.id)
    if is_read is not None:
        base = base.where(Notification.is_read.is_(is_read))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    unread_count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        )
    ).scalar() or 0
    items = (await db.execute(base.order_by(desc(Notification.id)).offset(skip).limit(limit))).scalars().all()
    return {"total": total, "unread_count": unread_count, "items": items}


@router.get("/unread-count")
async def unread_count(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """未读通知数（顶栏铃铛轮询用）。"""
    count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        )
    ).scalar() or 0
    return {"unread_count": count}


@router.put("/read-all")
async def read_all_notifications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """全部标记已读。"""
    from sqlalchemy import update

    await db.execute(
        update(Notification).where(Notification.user_id == current_user.id).values(is_read=True)
    )
    await db.commit()
    return {"message": "已全部标记为已读"}


@router.put("/{notification_id}/read")
async def read_notification(
    notification_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """单条标记已读。"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == current_user.id
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="通知不存在")
    item.is_read = True
    await db.commit()
    return {"message": "已读"}
