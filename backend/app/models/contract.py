from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Contract(Base):
    """合同基本信息表。"""

    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # pdf / docx / image
    status = Column(String(50), default="uploaded")
    page_count = Column(Integer, nullable=True)
    parsed_data = Column(JSON, default=dict)  # Section 树、Chunk 列表等
    risk_summary = Column(JSON, default=dict)  # 高中低风险统计
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # 软删除时间，回收站 30 天后清理
    nearest_expiry = Column(Date, nullable=True)  # 最近到期日（履约日期管家提取，列表页倒计时展示）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner = relationship("User", back_populates="contracts")
    files = relationship(
        "ContractFile", back_populates="contract", lazy="selectin", cascade="all, delete-orphan"
    )
    review_sessions = relationship(
        "ReviewSession", back_populates="contract", lazy="selectin", cascade="all, delete-orphan"
    )


class ContractFile(Base):
    """合同文件存储信息表。支持版本管理。"""

    __tablename__ = "contract_files"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    version = Column(Integer, default=1)
    storage_path = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    contract = relationship("Contract", back_populates="files")
