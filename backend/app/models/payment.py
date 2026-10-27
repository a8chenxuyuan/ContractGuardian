from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Payment(Base):
    """支付订单表。"""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_no = Column(String(100), unique=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    payment_type = Column(String(50), nullable=False)  # per_use / monthly / yearly / enterprise
    status = Column(String(50), default="pending")  # pending / paid / cancelled / refunded
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    """会员信息表。"""

    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    membership_type = Column(String(50), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    expire_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")


class RedeemCode(Base):
    """会员兑换码表。"""

    __tablename__ = "redeem_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, index=True, nullable=False)
    plan_type = Column(String(50), nullable=False)  # monthly / yearly
    is_used = Column(Boolean, default=False)
    used_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
