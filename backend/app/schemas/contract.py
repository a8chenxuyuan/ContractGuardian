from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class ContractStatus(str, Enum):
    """合同生命周期状态。"""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class ContractCreate(BaseModel):
    """创建合同记录请求体（实际上文件通过 multipart 上传）。"""

    filename: str
    file_type: str


class ContractOut(BaseModel):
    """合同列表/详情响应。"""

    id: int
    filename: str
    file_type: str
    status: ContractStatus
    page_count: int | None
    risk_summary: dict | None
    file_url: str | None = None
    latest_review_session_id: int | None = None
    version_count: int = 1
    nearest_expiry: date | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContractFileVersionOut(BaseModel):
    """合同文件版本信息。"""

    id: int
    version: int
    file_size: int
    is_current: bool
    created_at: datetime


class ContractUploadResponse(BaseModel):
    """上传成功响应。"""

    id: int
    filename: str
    status: ContractStatus
    message: str
