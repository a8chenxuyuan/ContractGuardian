from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class ReviewSession(Base):
    """审查会话表。"""

    __tablename__ = "review_sessions"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    status = Column(String(50), default="pending")  # pending / running / completed / failed / cancelled
    fail_reason = Column(String(20), nullable=True)  # 失败原因：cancelled/timeout/quota/provider/permission/internal
    base_version = Column(Integer, nullable=True)  # 对比审查的基准版本号，None 为普通审查
    graph_data = Column(JSON, default=dict)  # SessionGraph 序列化结果
    findings = Column(JSON, default=list)
    stats = Column(JSON, default=dict)
    diff_summary = Column(JSON, nullable=True)  # 条款级版本对比结果（对比审查时写入）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    contract = relationship("Contract", back_populates="review_sessions")
    human_reviews = relationship(
        "HumanReview", back_populates="review_session", lazy="selectin", cascade="all, delete-orphan"
    )


class Finding(Base):
    """风险发现细粒度表，便于单独查询和统计。"""

    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    review_session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    clause_text = Column(Text, nullable=True)
    risk_type = Column(String(100), nullable=False)
    level = Column(String(20), nullable=False)  # high / medium / low
    confidence = Column(Float, default=0.0)
    reason = Column(Text, nullable=True)
    law_refs = Column(JSON, default=list)
    suggestion = Column(JSON, default=dict)
    bbox = Column(JSON, nullable=True)
    status = Column(String(50), default="active")  # active / confirmed / dismissed / resolved
    resolution_note = Column(Text, nullable=True)  # 整改备注（自动核对时记录关闭原因）
    resolved_at = Column(DateTime(timezone=True), nullable=True)  # 关闭时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HumanReview(Base):
    """人工复核记录表。"""

    __tablename__ = "human_reviews"

    id = Column(Integer, primary_key=True, index=True)
    review_session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    finding_id = Column(Integer, ForeignKey("findings.id"), nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(String(50), default="pending")  # pending / approved / rejected
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    review_session = relationship("ReviewSession", back_populates="human_reviews")
