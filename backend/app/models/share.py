from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.core.database import Base


class ShareLink(Base):
    """报告分享链接：凭 token 免登录只读查看审查报告。"""

    __tablename__ = "share_links"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    review_session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
