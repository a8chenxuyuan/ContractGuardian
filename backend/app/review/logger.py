"""
文件：app/review/logger.py
作用：审查过程日志记录。

记录内容：
- 输入：合同文本、chunk、法律依据；
- 中间输出：detector 结果、LLM raw 输出、Critic 输出；
- 最终输出：风险列表；
- 元数据：耗时、模型、版本号。

存储方式：
- 详细 trace 写入 logs/reviews/{review_id}.jsonl；
- 摘要写入 ReviewSession.graph_data，便于后续分析。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings

settings = get_settings()

LOG_DIR = Path(getattr(settings, "REVIEW_LOG_DIR", "logs/reviews"))


class ReviewLogger:
    """审查过程日志记录器。"""

    def __init__(self, review_session_id: int | str, log_dir: Path | None = None):
        self.review_session_id = str(review_session_id)
        self.log_dir = Path(log_dir) if log_dir else LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"{self.review_session_id}.jsonl"
        self._trace: list[dict[str, Any]] = []
        self._start_time = time.time()
        self._bus_task: Any = None
        self._usage_token: Any = None  # LLM usage contextvar 绑定句柄

    def _append(self, event_type: str, payload: dict[str, Any]) -> None:
        """追加一条日志事件到文件和内存。"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "review_session_id": self.review_session_id,
            "event_type": event_type,
            "elapsed": round(time.time() - self._start_time, 4),
            "payload": payload,
        }
        self._trace.append(record)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_input(
        self,
        contract_text: str,
        contract_type: str,
        model: str,
        version: str = "1.0",
    ) -> None:
        """记录审查输入。"""
        self._append(
            "input",
            {
                "contract_type": contract_type,
                "model": model,
                "version": version,
                "contract_text_length": len(contract_text),
                # 不存储完整长文本，避免日志过大；需要时可去数据库查
                "contract_text_preview": contract_text[:500],
            },
        )

    def log_chunk(
        self,
        chunk_id: str,
        clause_text: str,
        linked_context: dict[str, Any] | None = None,
    ) -> None:
        """记录当前审查的条款 chunk。"""
        self._append(
            "chunk",
            {
                "chunk_id": chunk_id,
                "clause_text": clause_text[:1000],
                "linked_context": linked_context,
            },
        )

    def log_detector_result(
        self,
        detector_name: str,
        findings: list[dict[str, Any]],
    ) -> None:
        """记录 detector 输出。"""
        self._append(
            "detector_result",
            {
                "detector": detector_name,
                "finding_count": len(findings),
                "findings": findings,
            },
        )

    def log_llm_raw(
        self,
        agent_name: str,
        prompt: str,
        response: str,
        latency: float | None = None,
    ) -> None:
        """记录 LLM 原始输入输出。"""
        self._append(
            "llm_raw",
            {
                "agent": agent_name,
                "prompt_preview": prompt[:800],
                "response_preview": response[:800],
                "latency": latency,
            },
        )

    def log_critic_result(
        self,
        critic_source: str,
        verdict: str,
        reason: str,
        confidence_adjustment: float,
    ) -> None:
        """记录 Critic 输出。"""
        self._append(
            "critic_result",
            {
                "source": critic_source,
                "verdict": verdict,
                "reason": reason,
                "confidence_adjustment": confidence_adjustment,
            },
        )

    def log_final_findings(
        self,
        findings: list[dict[str, Any]],
        total_latency: float | None = None,
    ) -> None:
        """记录最终风险列表。"""
        self._append(
            "final_findings",
            {
                "finding_count": len(findings),
                "findings": findings,
                "total_latency": total_latency,
            },
        )

    def log_usage(self, usage: dict[str, Any]) -> None:
        """记录一次 LLM 调用的 token 用量（由 llm.usage 经 contextvar 归因调入）。"""
        self._append("llm_usage", usage)

    def get_trace(self) -> list[dict[str, Any]]:
        """获取内存中的 trace。"""
        return self._trace

    def get_summary(self) -> dict[str, Any]:
        """获取日志摘要，用于写入 ReviewSession.graph_data。"""
        event_counts: dict[str, int] = {}
        for record in self._trace:
            event_type = record["event_type"]
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        return {
            "review_session_id": self.review_session_id,
            "total_events": len(self._trace),
            "event_counts": event_counts,
            "total_elapsed": round(time.time() - self._start_time, 4),
            "log_file": str(self.log_file),
        }

    # ---------- 事件流订阅（事件协议 docs/protocols/event_protocol.md §4）----------

    async def attach(self, bus: Any) -> None:
        """订阅事件总线，把全部事件落盘为 trace。

        trace 消费方失败不得影响审查主流程：泵任务内部全量容错。
        """
        import asyncio

        async def _pump() -> None:
            try:
                async for event in bus.subscribe():
                    payload = dict(event.get("payload") or {})
                    payload.setdefault("origin_timestamp", event.get("timestamp"))
                    self._append(event.get("event_type") or "unknown", payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Redis 不可用等外部故障：放弃 trace，不阻断审查
                print(f"[ReviewLogger] trace 订阅中断: {e}")

        # 同时绑定 LLM token 用量归因（本审查内的所有 LLM 调用写进同一 trace）
        from app.llm.usage import bind_trace_logger

        self._usage_token = bind_trace_logger(self)
        self._bus_task = asyncio.create_task(_pump())

    async def detach(self) -> None:
        """停止订阅（审查结束后调用，先于 bus.close）。"""
        # 先解绑 usage 归因，避免后续其他调用误写入本 trace
        if self._usage_token is not None:
            from app.llm.usage import unbind_trace_logger

            unbind_trace_logger(self._usage_token)
            self._usage_token = None
        if getattr(self, "_bus_task", None) is not None:
            # 让出一轮调度：把队列里尚未消费的收尾事件（completed/error）落盘后再取消
            import asyncio

            await asyncio.sleep(0)
            self._bus_task.cancel()
            try:
                await self._bus_task
            except asyncio.CancelledError:
                # detach 主动取消产生的 CancelledError 属预期，吞掉即可
                pass
            except Exception:
                # 取消泵任务的其他收尾异常无恢复手段，静默即可
                pass
            self._bus_task = None
