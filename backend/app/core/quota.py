"""会员状态与审查配额服务。"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.contract import Contract
from app.models.review import ReviewSession
from app.models.user import User

settings = get_settings()


def is_membership_valid(user: User) -> bool:
    """会员资格判断：管理员与未过期会员均视为有效会员。"""
    if user.is_admin:
        return True
    if not user.is_member or not user.membership_expire_at:
        return False
    expire = user.membership_expire_at
    if expire.tzinfo is None:
        expire = expire.replace(tzinfo=timezone.utc)
    return expire > datetime.now(timezone.utc)


async def count_monthly_reviews(db: AsyncSession, user_id: int) -> int:
    """统计用户本月已发起的审查次数（自然月）。"""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count(ReviewSession.id))
        .join(Contract, ReviewSession.contract_id == Contract.id)
        .where(Contract.owner_id == user_id, ReviewSession.created_at >= month_start)
    )
    return int(result.scalar() or 0)


def quota_error(reason: str, used: int, limit: int) -> HTTPException:
    """构造 402 配额不足异常，前端据此弹出升级引导。"""
    return HTTPException(
        status_code=402,
        detail={"code": "QUOTA_EXCEEDED", "reason": reason, "used": used, "limit": limit},
    )


async def check_review_quota(db: AsyncSession, user: User) -> None:
    """审查启动前的配额校验：非会员检查月度次数。"""
    if is_membership_valid(user):
        return
    used = await count_monthly_reviews(db, user.id)
    if used >= settings.FREE_MONTHLY_REVIEWS:
        raise quota_error("monthly_reviews", used, settings.FREE_MONTHLY_REVIEWS)


def check_page_quota(user: User, page_count: int | None) -> None:
    """页数配额校验：非会员合同页数超限拒绝。"""
    if page_count is None or is_membership_valid(user):
        return
    if page_count > settings.FREE_PAGE_LIMIT:
        raise quota_error("page_limit", page_count, settings.FREE_PAGE_LIMIT)


def activate_membership(user: User, days: int, plan_type: str) -> None:
    """激活/续期会员：已有有效会员则从原到期日顺延。"""
    now = datetime.now(timezone.utc)
    base = now
    if is_membership_valid(user) and user.membership_expire_at:
        expire = user.membership_expire_at
        if expire.tzinfo is None:
            expire = expire.replace(tzinfo=timezone.utc)
        base = max(base, expire)
    user.is_member = True
    user.membership_expire_at = base + timedelta(days=days)
