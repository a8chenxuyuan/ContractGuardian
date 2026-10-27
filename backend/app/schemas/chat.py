from pydantic import BaseModel


class ChatRequest(BaseModel):
    """对话请求体。"""

    question: str
    selected_text: str | None = None
    page: int | None = None


class ChatResponse(BaseModel):
    """对话响应体。"""

    answer: str
    references: list[dict] = []


class ChatStreamChunk(BaseModel):
    """流式对话单个块。"""

    delta: str
    finish: bool = False
