"""
文件：app/routers/approvals.py
作用：HITL 审批接口（协议 plugin_registry.md §2 approve 态）——待审列表与裁决，仅管理员。

流程：Agent 挂起的 approve 工具调用登记在 Redis（agentkit/approval.py），
管理员经本接口裁决后，等待中的 _call_tool 立即恢复执行或拒绝。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.agentkit.approval import decide, list_pending
from app.models.user import User
from app.routers.admin import get_current_admin

router = APIRouter()


@router.get("")
async def get_pending_approvals(
    admin: Annotated[User, Depends(get_current_admin)],
) -> list[dict]:
    """待审批请求列表（含 approval_id、工具名、Agent、输入摘要）。"""
    return list_pending()


@router.post("/{approval_id}/approve")
async def approve_request(
    approval_id: str,
    admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """放行：等待中的工具调用恢复执行。"""
    result = decide(approval_id, "approved", decided_by=str(admin.username))
    if result is None:
        raise HTTPException(status_code=404, detail="审批不存在或已裁决")
    return result


@router.post("/{approval_id}/deny")
async def deny_request(
    approval_id: str,
    admin: Annotated[User, Depends(get_current_admin)],
) -> dict:
    """拒绝：等待中的工具调用收到错误观察，Agent 换路径处理。"""
    result = decide(approval_id, "denied", decided_by=str(admin.username))
    if result is None:
        raise HTTPException(status_code=404, detail="审批不存在或已裁决")
    return result
