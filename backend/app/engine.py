"""
文件：app/engine.py
作用：引擎门面（L7，协议 docs/protocols/plugin_registry.md §3）。

外部系统（含未来大型项目集成）的唯一接入点，与 FastAPI / Celery / 数据库解耦：
    facade = ReviewFacade()
    for event in facade.review(doc):        # 纯文本进，事件流逐条出
        ...
    result = facade.state_store.load(sid)   # 终态结果经 StateStore 取回（sid 在事件信封里）

设计动机（为什么）：
- 无状态门面：facade 自身不持有任何会话数据，会话状态全部落 StateStore，
  多实例/多线程可各自 new ReviewFacade 共享同一 StateStore 实现；
- StateStore 抽象（L6 状态恢复）：默认内存实现，后续换 Redis/DB 实现不动门面；
- 事件即协议：产出的就是 event_protocol.md 的标准信封，消费方式与 SSE/trace 一致。
"""

from __future__ import annotations

import asyncio
import queue as thread_queue
import threading
import uuid
from collections.abc import Iterator
from typing import Any, Protocol

# 门面迭代的终止事件（与事件协议终态一致）
TERMINAL_EVENTS = frozenset({"completed", "error", "cancelled"})


class StateStore(Protocol):
    """审查状态存取抽象：session_id -> 终态状态。"""

    def save(self, session_id: int | str, state: dict[str, Any]) -> None: ...

    def load(self, session_id: int | str) -> dict[str, Any] | None: ...


class InMemoryStateStore:
    """内存实现：进程内字典，进程退出即失联，适合单机/测试场景。"""

    def __init__(self) -> None:
        self._states: dict[int | str, dict[str, Any]] = {}

    def save(self, session_id: int | str, state: dict[str, Any]) -> None:
        self._states[session_id] = state

    def load(self, session_id: int | str) -> dict[str, Any] | None:
        return self._states.get(session_id)


class RedisStateStore:
    """Redis 实现（多实例共享）：键 review:state:{sid}，JSON 序列化 + TTL 过期。

    Redis 不可用时直接抛错——不静默吞，避免"审查成功但结果取不回"被误判为审查失败。
    """

    def __init__(self, redis_url: str, ttl_seconds: int):
        import redis

        self._client = redis.Redis.from_url(redis_url)
        self._ttl = ttl_seconds

    @staticmethod
    def _key(session_id: int | str) -> str:
        return f"review:state:{session_id}"

    def save(self, session_id: int | str, state: dict[str, Any]) -> None:
        import json

        self._client.set(self._key(session_id), json.dumps(state, ensure_ascii=False), ex=self._ttl)

    def load(self, session_id: int | str) -> dict[str, Any] | None:
        import json

        raw = self._client.get(self._key(session_id))
        return json.loads(raw) if raw else None


def build_state_store() -> StateStore:
    """按配置 STATE_STORE 选型（memory/redis），默认内存保持既有行为。"""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.STATE_STORE == "redis":
        return RedisStateStore(settings.REDIS_URL, settings.STATE_STORE_TTL)
    return InMemoryStateStore()


class ReviewFacade:
    """审查引擎门面：文本进 → 事件流出 + 状态入库。"""

    def __init__(self, state_store: StateStore | None = None):
        self.state_store: StateStore = state_store or build_state_store()

    # ------------------------------------------------------------------
    # 对外入口（协议约定签名）：review(doc, config) -> Iterator[event]
    # ------------------------------------------------------------------
    def review(self, doc: str, config: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """对纯文本合同发起一次审查，同步逐条产出标准事件信封。

        终止于 completed / error / cancelled 事件；终止事件产出时，
        结果已写入 state_store（用事件信封里的 session_id 取回）。

        config 支持字段：
        - session_id     : 指定会话 ID（默认自动生成）
        - contract_type  : 合同类型（默认按文本自动分类）
        - coordinator    : 传给 ReviewCoordinator 的配置 dict
        """
        out_queue: thread_queue.Queue[dict[str, Any]] = thread_queue.Queue()
        loop = asyncio.new_event_loop()

        def _worker() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._drive(doc, config or {}, out_queue))
            except Exception as e:  # noqa: BLE001 —— 门面兜底：任何异常转 error 事件
                out_queue.put(
                    {
                        "event_type": "error",
                        "session_id": (config or {}).get("session_id"),
                        "payload": {"phase": "failed", "message": f"引擎门面异常：{e}"},
                    }
                )
            finally:
                loop.close()

        worker = threading.Thread(target=_worker, name="review-facade", daemon=True)
        worker.start()

        while True:
            event = out_queue.get()
            yield event
            if event.get("event_type") in TERMINAL_EVENTS:
                break
        worker.join(timeout=5)

    # ------------------------------------------------------------------
    # 内部驱动：在独立事件循环里完成 解析 → 订阅 → 跑管线 → 落状态
    # ------------------------------------------------------------------
    async def _drive(
        self,
        doc: str,
        config: dict[str, Any],
        out_queue: thread_queue.Queue[dict[str, Any]],
    ) -> None:
        session_id: int | str = config.get("session_id") or (uuid.uuid4().int % (10**12))
        terminal_buffer: list[dict[str, Any]] = []
        bus = None
        pump: asyncio.Task | None = None
        try:
            # 1) 纯文本 -> chunks / section_tree（复用解析器的条款聚合逻辑，不落库）
            chunks, section_tree, contract_type = self._parse_doc(doc, config)

            # 2) 订阅与 run_review 同频道的事件流，非终态事件实时转发给消费者
            from app.agentkit.bus import AgentBus
            from app.core.config import get_settings

            bus = AgentBus(session_id=session_id, redis_url=get_settings().REDIS_URL)

            async def _pump() -> None:
                async for event in bus.subscribe():
                    if event.get("event_type") in TERMINAL_EVENTS:
                        # 终态先缓存：等结果落 StateStore 后再放行，避免消费者拿到终态时状态未就绪
                        terminal_buffer.append(event)
                        break
                    out_queue.put(event)

            pump = asyncio.create_task(_pump())
            # 等订阅真正就绪（队列注册 + Redis 频道订阅完成），防止丢失早期事件
            running_loop = asyncio.get_running_loop()
            deadline = running_loop.time() + 5
            while not bus._connected and not pump.done():
                if running_loop.time() > deadline:
                    raise ConnectionError("事件总线订阅超时（检查 Redis 是否可用）")
                await asyncio.sleep(0.01)
            if pump.done():
                exc = pump.exception()
                if exc:
                    raise exc

            # 3) 跑完整审查管线（与 Celery 线路同入口，只是 contract_id=0 离线语义）
            from app.review.pipeline import ReviewCoordinator

            coordinator = ReviewCoordinator(config=config.get("coordinator") or {})
            result = await coordinator.run_review(
                contract_id=0,
                chunks=chunks,
                section_tree=section_tree,
                vector_index="default",
                contract_type=contract_type,
                review_session_id=session_id,
            )
            self.state_store.save(
                session_id, {"status": "completed", "result": result}
            )
        except Exception as e:  # noqa: BLE001 —— 门面兜底：失败也必须留终态
            self.state_store.save(session_id, {"status": "failed", "error": str(e)})
            terminal_buffer.append(
                {
                    "event_type": "error",
                    "session_id": session_id,
                    "payload": {"phase": "failed", "message": f"审查失败：{e}"},
                }
            )
        finally:
            if pump is not None and not pump.done():
                pump.cancel()
            if bus is not None:
                await bus.close()

        # 4) 终态事件最后放行（completed 来自管线，error 可能来自上方兜底）
        for event in terminal_buffer:
            out_queue.put(event)
        if not terminal_buffer:
            out_queue.put(
                {
                    "event_type": "error",
                    "session_id": session_id,
                    "payload": {"phase": "failed", "message": "审查未产生终态事件"},
                }
            )

    # ------------------------------------------------------------------
    # 文本解析（离线路径：不经过上传/DB，直接走解析器的条款聚合）
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_doc(
        doc: str, config: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        from app.contracts.parser import ContractParser

        paragraphs = [
            {"text": line, "page": 1} for line in (doc or "").splitlines() if line.strip()
        ]
        parser = ContractParser()
        chunks = parser._build_clauses(paragraphs)  # noqa: SLF001 —— 同包复用解析核心
        if not chunks:
            raise ValueError("doc 解析后没有可用条款内容")
        section_tree = parser._build_section_tree(chunks)  # noqa: SLF001
        contract_type = config.get("contract_type") or ContractParser.classify_contract_type(
            {"section_tree": section_tree, "chunks": chunks}
        )
        return chunks, section_tree, contract_type
