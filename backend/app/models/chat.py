from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class ChatRecord(Base):
    """对话记录表。"""

    __tablename__ = "chat_records"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user / assistant
    question = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    selected_text = Column(Text, nullable=True)
    references = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
