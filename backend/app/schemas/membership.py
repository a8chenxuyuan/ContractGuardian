"""会员体系相关 schemas。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MembershipPlan(BaseModel):
    """套餐信息。"""

    plan_type: str
    name: str
    price: float
    duration_days: int
    description: str
    features: list[str]
    recommended: bool = False


class MembershipPlansOut(BaseModel):
    """套餐列表响应。"""

    plans: list[MembershipPlan]
    free_limits: dict


class MembershipMeOut(BaseModel):
    """当前用户会员状态与用量。"""

    is_member: bool
    membership_expire_at: datetime | None
    page_limit: int | None  # None 表示无限制
    monthly_reviews_used: int
    monthly_reviews_limit: int | None  # None 表示无限制


class MembershipOrderIn(BaseModel):
    """模拟下单请求。"""

    plan_type: Literal["monthly", "yearly"]


class MembershipOrderOut(BaseModel):
    """下单结果响应（模拟支付成功后返回）。"""

    order_no: str
    amount: float
    plan_type: str
    is_member: bool
    membership_expire_at: datetime | None
    message: str


class RedeemIn(BaseModel):
    """兑换码请求。"""

    code: str


class RedeemOut(BaseModel):
    """兑换结果响应。"""

    plan_type: str
    is_member: bool
    membership_expire_at: datetime | None
    message: str
