from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class ContractTemplate(Base):
    """合同模板表：is_preset=True 为系统预置范本（人人可读、不可删），否则为用户上传的私有模板。"""

    __tablename__ = "contract_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, index=True)
    scene = Column(String(500), nullable=True, default="")
    content = Column(Text, nullable=False)
    is_preset = Column(Boolean, nullable=False, default=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    usage_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
