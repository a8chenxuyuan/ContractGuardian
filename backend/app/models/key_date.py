from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class KeyDate(Base):
    """合同关键履约日期（审查完成时自动提取，按合同覆盖更新）。"""

    __tablename__ = "key_dates"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    review_session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    date_value = Column(Date, nullable=False, index=True)
    date_type = Column(String(20), nullable=False)  # signing/effective/expiry/payment/delivery/other
    raw_text = Column(String(100), nullable=False)  # 日期原文
    context = Column(Text, nullable=True)  # 所在条款上下文摘要
    created_at = Column(DateTime(timezone=True), server_default=func.now())
