"""
文件：app/llm/usage.py
作用：LLM token 用量埋点的上下文归因（contextvar）。

为什么用 contextvar：
- LLM 客户端是单例，不知道调用属于哪次审查；ReviewLogger 在 llm 层之上（依赖只准向下），
  llm 层不能反向 import review 层；
- 审查协程启动时 bind_trace_logger() 绑入当前上下文，其内所有 LLM 调用自动归因，
  并发审查互不串账；未绑定（如快车道问答）则静默跳过。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_trace_logger_var: ContextVar[Any] = ContextVar("trace_logger", default=None)


def bind_trace_logger(logger: Any) -> Any:
    """绑定当前审查的 trace 记录器，返回 token。"""
    return _trace_logger_var.set(logger)


def unbind_trace_logger(token: Any) -> None:
    """解绑（token 无效时静默忽略，保证 detach 幂等）。"""
    try:
        _trace_logger_var.reset(token)
    except ValueError:
        pass


def record_usage(usage: dict[str, Any]) -> None:
    """上报一次 LLM 调用的 token 用量；无绑定或记录失败均不影响主链路。"""
    logger = _trace_logger_var.get()
    if logger is None:
        return
    try:
        logger.log_usage(usage)
    except Exception:  # noqa: BLE001 —— 埋点只锦上添花，绝不阻断生成
        pass
