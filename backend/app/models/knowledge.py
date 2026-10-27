from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class KnowledgeArticle(Base):
    """法律法规条目表。"""

    __tablename__ = "knowledge_articles"

    id = Column(Integer, primary_key=True, index=True)
    law_name = Column(String(255), nullable=False)
    article_number = Column(String(100), nullable=False)
    article_title = Column(String(255), nullable=True)
    article_text = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    effective_date = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeCase(Base):
    """典型案例表。"""

    __tablename__ = "knowledge_cases"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    court = Column(String(255), nullable=True)
    verdict = Column(Text, nullable=True)
    related_articles = Column(JSON, default=list)
    source_url = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
