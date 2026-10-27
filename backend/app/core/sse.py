import json
from typing import AsyncGenerator

import redis.asyncio as redis

from app.core.config import get_settings

settings = get_settings()


class SSEManager:
    """SSE 进度推送管理器。

    通过 Redis Pub/Sub 实现多 Worker 场景下的进度广播。
    单机环境下也可使用 asyncio.Queue 做内存广播。

    采用单例模式，确保整个应用生命周期内只有一个 Redis 连接实例，
    便于在 FastAPI lifespan 中统一关闭。
    """

    _instance: "SSEManager | None" = None

    def __new__(cls) -> "SSEManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._redis_client = None
        return cls._instance

    def __init__(self):
        # __new__ 已负责初始化，此处留空避免重复创建属性
        pass

    async def _get_redis(self) -> redis.Redis:
        if self._redis_client is None:
            self._redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis_client

    def channel_name(self, review_session_id: int) -> str:
        # 频道命名单一事实源：与 AgentBus 共用（事件协议 docs/protocols/event_protocol.md）
        from app.agentkit.events import review_channel

        return review_channel(review_session_id)

    async def publish(self, review_session_id: int, event: dict) -> None:
        """发布一个 SSE 事件。"""
        r = await self._get_redis()
        message = json.dumps(event, ensure_ascii=False)
        await r.publish(self.channel_name(review_session_id), message)

    async def subscribe(
        self, review_session_id: int
    ) -> AsyncGenerator[str, None]:
        """订阅某个审查会话的 SSE 事件，以 async generator 形式产出。"""
        r = await self._get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(self.channel_name(review_session_id))

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    yield f"data: {data}\n\n"
        finally:
            await pubsub.unsubscribe(self.channel_name(review_session_id))
            await pubsub.aclose()

    async def close(self) -> None:
        """关闭 SSEManager 持有的 Redis 连接。"""
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception:
                # close 阶段的连接清理失败无恢复手段，静默即可
                pass
            self._redis_client = None
