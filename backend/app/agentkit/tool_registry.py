"""
文件：app/agentkit/tool_registry.py
作用：工具注册表 + 权限三态解析（协议 docs/protocols/plugin_registry.md §1/§2）。

设计动机（为什么）：
- 新增工具 = 写函数 + @register_tool 装饰器，禁止改装配逻辑；
- 权限声明在代码里（装饰器），运行时可被配置 TOOL_PERMISSION_OVERRIDES 覆盖，
  权限调整不改代码不发版。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 权限三态
ALLOW = "allow"  # 直通
APPROVE = "approve"  # 审批钩子（HITL 未实现前等同 ALLOW，记 pending 审计事件）
DENY = "deny"  # 直接拒绝，发 tool_permission_denied 事件
PERMISSIONS = frozenset({ALLOW, APPROVE, DENY})


@dataclass(frozen=True)
class ToolSpec:
    """一条工具登记：名字、函数对象、声明权限。"""

    name: str
    func: Any
    permission: str = ALLOW


# 全局工具注册表：工具名 -> ToolSpec（进程内唯一事实源）
TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(name: str | None = None, permission: str = ALLOW) -> Callable:
    """工具装饰器：@register_tool("web_search", permission="approve")。

    name 缺省取函数名；permission 非法值直接抛错（注册即校验，不带病上线）。
    """

    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        if permission not in PERMISSIONS:
            raise ValueError(f"非法权限 {permission!r}，可选：{sorted(PERMISSIONS)}")
        TOOL_REGISTRY[tool_name] = ToolSpec(tool_name, func, permission)
        return func

    return decorator


def resolve_permission(tool_name: str) -> str:
    """解析工具最终权限：配置覆盖 > 装饰器声明 > 默认 allow。

    配置值非法时忽略覆盖（防配置手误导致全部工具失效）。
    """
    from app.core.config import get_settings

    override = get_settings().TOOL_PERMISSION_OVERRIDES.get(tool_name)
    if override in PERMISSIONS:
        return override
    spec = TOOL_REGISTRY.get(tool_name)
    return spec.permission if spec else ALLOW
