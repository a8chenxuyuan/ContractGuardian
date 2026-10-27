from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.core.database import Base


class Notification(Base):
    """站内通知：审查完成等事件推送给用户。"""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(String(1000), nullable=True)
    type = Column(String(30), default="review")  # review / system
    contract_id = Column(Integer, nullable=True)
    related_id = Column(Integer, nullable=True)  # 如 review_session_id
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
