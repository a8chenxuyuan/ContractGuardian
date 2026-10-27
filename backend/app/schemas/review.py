from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class ReviewDiffIn(BaseModel):
    """对比审查请求体（可选）。"""

    base_version: int | None = None


class ReviewStartResponse(BaseModel):
    """启动审查响应。"""

    review_session_id: int
    message: str


class ReviewEventType(str, Enum):
    """SSE 事件类型。"""

    PHASE = "phase"
    AGENT_PROGRESS = "agent_progress"
    FINDING_ADDED = "finding_added"
    COMPLETED = "completed"
    ERROR = "error"


class ReviewEvent(BaseModel):
    """单个 SSE 事件。"""

    event: ReviewEventType
    data: dict


class ReviewResultOut(BaseModel):
    """审查结果响应。"""

    id: int
    contract_id: int
    status: str
    fail_reason: str | None = None  # cancelled/timeout/quota/provider/permission/internal
    findings: list[dict]
    graph_data: dict | None
    stats: dict | None
    created_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class ReviewFeedbackIn(BaseModel):
    """审查反馈请求。"""

    finding_id: int | None = None
    is_correct: bool
    correct_label: str | None = None  # high / medium / low
    comment: str | None = None


class ReviewFeedbackOut(BaseModel):
    """审查反馈响应。"""

    id: int
    review_session_id: int
    finding_id: int | None
    status: str
    reason: str
    comment: str | None
    created_at: datetime


class FindingStatusIn(BaseModel):
    """风险项整改状态更新请求。"""

    status: Literal["active", "confirmed", "dismissed", "resolved"]
    note: str | None = None


class RectificationOut(BaseModel):
    """整改进度统计（close_rate 为百分比，保留两位小数）。"""

    total: int
    active: int
    confirmed: int
    dismissed: int
    resolved: int
    close_rate: float


class AskIn(BaseModel):
    """划词追问请求体（finding_id 指定追问的风险项上下文）。"""

    question: str
    selected_text: str | None = None
    finding_id: int | None = None


class AskOut(BaseModel):
    """划词追问响应体。"""

    answer: str
    references: list[dict] = []
    degraded: bool = False
