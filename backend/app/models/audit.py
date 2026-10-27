from sqlalchemy import JSON, Column, DateTime, Integer, String, func

from app.core.database import Base


class AuditLog(Base):
    """审计日志：记录用户写操作，供后台追溯。"""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    email = Column(String(255), nullable=True)
    action = Column(String(50), index=True)  # HTTP 方法或 LOGIN
    resource = Column(String(255), index=True)  # API 路径
    detail = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
