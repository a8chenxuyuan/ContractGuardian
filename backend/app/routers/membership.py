"""会员体系路由：套餐、当前状态、模拟下单、兑换码。"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.quota import (
    activate_membership,
    count_monthly_reviews,
    is_membership_valid,
)
from app.models.payment import Membership, Payment, RedeemCode
from app.models.user import User
from app.routers.admin import get_current_admin
from app.routers.auth import get_current_active_user
from app.schemas.membership import (
    MembershipMeOut,
    MembershipOrderIn,
    MembershipOrderOut,
    MembershipPlan,
    MembershipPlansOut,
    RedeemIn,
    RedeemOut,
)

router = APIRouter()
settings = get_settings()


def _build_plans() -> list[MembershipPlan]:
    return [
        MembershipPlan(
            plan_type="monthly",
            name="月度会员",
            price=settings.MEMBERSHIP_PRICE_MONTHLY,
            duration_days=30,
            description="适合短期项目合同审查",
            features=[
                "单合同页数无限制",
                "每月审查次数无限制",
                "14 Agent 全维度交叉审查",
                "审查报告 Word / PDF 导出",
            ],
        ),
        MembershipPlan(
            plan_type="yearly",
            name="年度会员",
            price=settings.MEMBERSHIP_PRICE_YEARLY,
            duration_days=365,
            description="长期法务高频使用，立省 40%",
            features=[
                "单合同页数无限制",
                "每月审查次数无限制",
                "14 Agent 全维度交叉审查",
                "审查报告 Word / PDF 导出",
                "优先体验新功能（对比审查等）",
            ],
            recommended=True,
        ),
    ]


def _free_limits() -> dict:
    return {
        "page_limit": settings.FREE_PAGE_LIMIT,
        "monthly_reviews": settings.FREE_MONTHLY_REVIEWS,
    }


def _generate_order_no() -> str:
    return f"CG{datetime.now(timezone.utc):%Y%m%d%H%M%S}{uuid.uuid4().hex[:8].upper()}"


async def _activate_and_record(
    db: AsyncSession, user: User, plan_type: str, days: int, amount: float | None
) -> str:
    """激活会员并落库：订单（可选）+ 会员记录 + User 冗余字段。"""
    now = datetime.now(timezone.utc)
    order_no = ""
    if amount is not None:
        order_no = _generate_order_no()
        db.add(
            Payment(
                user_id=user.id,
                order_no=order_no,
                amount=amount,
                payment_type=plan_type,
                status="paid",
                paid_at=now,
            )
        )
    activate_membership(user, days=days, plan_type=plan_type)
    db.add(
        Membership(
            user_id=user.id,
            membership_type=plan_type,
            expire_at=user.membership_expire_at,
        )
    )
    await db.commit()
    return order_no


@router.get("/plans", response_model=MembershipPlansOut)
async def list_plans():
    """获取会员套餐列表与免费版限制。"""
    return MembershipPlansOut(plans=_build_plans(), free_limits=_free_limits())


@router.get("/me", response_model=MembershipMeOut)
async def my_membership(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户会员状态与本月用量。"""
    member = is_membership_valid(current_user)
    used = await count_monthly_reviews(db, current_user.id)
    return MembershipMeOut(
        is_member=member,
        membership_expire_at=current_user.membership_expire_at if member else None,
        page_limit=None if member else settings.FREE_PAGE_LIMIT,
        monthly_reviews_used=used,
        monthly_reviews_limit=None if member else settings.FREE_MONTHLY_REVIEWS,
    )


@router.post("/order", response_model=MembershipOrderOut)
async def create_order(
    body: MembershipOrderIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """模拟下单并即时支付成功，开通会员。

    TODO: 对接真实支付时，此处应改为创建 pending 订单并返回支付参数，
    由支付回调接口完成激活；当前为演示环境直接模拟成功。
    """
    plan = next((p for p in _build_plans() if p.plan_type == body.plan_type), None)
    if not plan:
        raise HTTPException(status_code=400, detail="套餐不存在")

    order_no = await _activate_and_record(db, current_user, plan.plan_type, plan.duration_days, plan.price)
    return MembershipOrderOut(
        order_no=order_no,
        amount=plan.price,
        plan_type=plan.plan_type,
        is_member=True,
        membership_expire_at=current_user.membership_expire_at,
        message=f"{plan.name}开通成功，有效期至 {current_user.membership_expire_at:%Y-%m-%d}",
    )


@router.post("/redeem", response_model=RedeemOut)
async def redeem_code(
    body: RedeemIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
):
    """使用兑换码开通会员。"""
    code = body.code.strip().upper()
    result = await db.execute(select(RedeemCode).where(RedeemCode.code == code))
    redeem = result.scalar_one_or_none()
    if not redeem or redeem.is_used:
        raise HTTPException(status_code=400, detail="兑换码无效或已被使用")

    days = 30 if redeem.plan_type == "monthly" else 365
    redeem.is_used = True
    redeem.used_by = current_user.id
    redeem.used_at = datetime.now(timezone.utc)
    await _activate_and_record(db, current_user, redeem.plan_type, days, None)

    return RedeemOut(
        plan_type=redeem.plan_type,
        is_member=True,
        membership_expire_at=current_user.membership_expire_at,
        message=f"兑换成功，会员有效期至 {current_user.membership_expire_at:%Y-%m-%d}",
    )


class RedeemCodeGenerateIn(BaseModel):
    """管理员生成兑换码请求。"""

    plan_type: str  # monthly / yearly
    count: int = 1


@router.post("/admin/codes")
async def generate_redeem_codes(
    body: RedeemCodeGenerateIn,
    _admin: Annotated[User, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
):
    """管理员批量生成兑换码。"""
    if body.plan_type not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="套餐类型仅支持 monthly / yearly")
    if not 1 <= body.count <= 50:
        raise HTTPException(status_code=400, detail="单次生成数量需在 1-50 之间")

    prefix = "CG-M" if body.plan_type == "monthly" else "CG-Y"
    codes = [f"{prefix}-{uuid.uuid4().hex[:12].upper()}" for _ in range(body.count)]
    for code in codes:
        db.add(RedeemCode(code=code, plan_type=body.plan_type))
    await db.commit()
    return {"codes": codes}
