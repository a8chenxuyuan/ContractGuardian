"""
文件：app/agentkit/bus.py
作用：实现 Agent 之间的实时消息总线 AgentBus，用于广播事件和订阅事件。

实现方式：基于 Redis Pub/Sub。
- 同一个 session 的 Coordinator 与所有 Agent 共享一个 Redis 频道。
- 发布事件时同时写入 Redis 频道和本地内存队列，保证同进程订阅者能立即收到。
- Redis 为必需依赖，不可用时直接抛异常，不再降级为纯内存广播。

核心事件类型说明：
- agent_started:   Agent 开始审查某个 Chunk
- agent_completed: Agent 完成某个 Chunk 审查
- finding_added:   Agent 写入新的 Risk 节点
- risk_escalated:  风险等级被动态上调
- evidence_found:  找到关键证据
- contradiction_detected: 发现条款冲突
- phase_changed:   Coordinator 阶段切换
- completed:       整个审查流程完成
- error:           发生错误
"""

# ============================================================
# 1. 导入需要的库
# ============================================================

# asyncio 提供异步编程支持，包括 Queue、Task、异步迭代器等
import asyncio

# json 用于把事件对象序列化成字符串，便于通过 Redis 传输
import json

# logging 用于记录连接、发布、订阅过程中的日志
import logging

# datetime 和 timezone 用于给每条事件打上 UTC 时间戳
from datetime import datetime, timezone

# typing 提供类型提示，让代码更清晰，也便于 IDE 自动补全
from typing import Any, AsyncIterator, Iterator

# redis.asyncio 是 Redis 官方提供的异步客户端，支持 Pub/Sub
import redis.asyncio as aioredis

# 从项目配置中读取 REDIS_URL 等全局设置
from app.core.config import get_settings

# 获取当前模块的日志记录器，日志名称会显示为 app.agentkit.bus
logger = logging.getLogger(__name__)


# ============================================================
# 2. 定义 AgentBus 类
# ============================================================

class AgentBus:
    """
    Agent 之间的事件总线，基于 Redis Pub/Sub 实现。
    作用：让 Coordinator 和所有 Agent 能够实时互相通知。
    """

    def __init__(self, session_id: int, redis_url: str | None = None):
        """
        初始化消息总线。

        参数：
            session_id：当前审查会话 ID，不同会话使用不同 Redis 频道隔离
            redis_url：Redis 地址，如果传 None 则读取项目配置
        """
        # 保存当前会话 ID，后面构造频道名和事件时会用到
        self.session_id = session_id

        # 如果调用者没传 redis_url，就从 app.config 里读；否则用传入的地址
        self.redis_url = redis_url or get_settings().REDIS_URL

        # ------------------------------------------------------------------
        # 内存广播用的数据结构
        # ------------------------------------------------------------------

        # _queues 按 event_type 分组保存订阅者队列
        # key 是事件类型字符串，value 是该类型订阅者的 asyncio.Queue 列表
        # 每个调用 subscribe(event_type=...) 的订阅者都会在这里注册一个队列
        self._queues: dict[str, list[asyncio.Queue]] = {}

        # _all_queues 保存订阅了所有事件的订阅者队列
        # 调用 subscribe() 时不传 event_type，就会在这里注册
        self._all_queues: list[asyncio.Queue] = []

        # ------------------------------------------------------------------
        # Redis 相关对象
        # ------------------------------------------------------------------

        # _redis_client 是真正的 Redis 连接客户端，用于执行 publish 命令
        self._redis_client: aioredis.Redis | None = None

        # _pubsub 是 Redis 的 Pub/Sub 客户端，用于订阅频道并接收消息
        self._pubsub: aioredis.client.PubSub | None = None

        # _listener_task 是后台监听 Redis 消息的任务
        # 每个 AgentBus 实例只启动一个，避免为每个订阅者都开一条 Redis 连接
        self._listener_task: asyncio.Task | None = None

        # _channel 是当前会话对应的 Redis 频道名（事件协议统一入口，见 events.py）
        # 不同 session 用不同频道，避免消息互相串扰
        from app.agentkit.events import review_channel

        self._channel = review_channel(session_id)

        # _connected 标记是否已经和 Redis 建立过连接
        self._connected = False

        # _closed 标记总线是否已经关闭，关闭后不再尝试重连
        self._closed = False

    # ============================================================
    # 3. Redis 连接管理
    # ============================================================

    async def _connect(self) -> None:
        """
        懒加载 Redis 客户端并启动监听任务。
        Redis 为必需依赖，连接失败时直接抛出异常，禁止降级为纯内存广播。
        """
        # 如果已经连接过，或者总线已经关闭，就直接返回，避免重复连接
        if self._connected or self._closed:
            return

        try:
            # 根据 redis_url 创建异步 Redis 客户端
            # decode_responses=True 表示返回的字符串自动解码成 Python str
            self._redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
            )

            # 从 Redis 客户端创建 Pub/Sub 对象，用于订阅频道
            self._pubsub = self._redis_client.pubsub()

            # 订阅当前会话的专属频道
            await self._pubsub.subscribe(self._channel)

            # 启动后台任务，持续监听 Redis 发来的消息
            self._listener_task = asyncio.create_task(self._redis_listener())

            # 标记连接成功
            self._connected = True

            # 记录日志，方便排查时知道哪个 session 连上了哪个频道
            logger.info(
                f"AgentBus(session={self.session_id}) 已连接到 Redis 频道 {self._channel}"
            )
        except Exception as e:
            # Redis 为必需依赖，连接失败必须让上层感知，不能静默降级
            logger.error(
                f"AgentBus(session={self.session_id}) Redis 连接失败: {e}"
            )
            raise ConnectionError(
                f"AgentBus 无法连接到 Redis ({self.redis_url})，请确认 Redis 服务已启动。"
            ) from e

    # ============================================================
    # 4. Redis 消息监听与本地分发
    # ============================================================

    async def _redis_listener(self) -> None:
        """
        后台任务：从 Redis PubSub 读取消息，并分发给本地订阅队列。
        这个方法作为后台 Task 运行，不直接暴露给调用方。
        """
        # 如果 PubSub 对象不存在，说明 Redis 没连上，直接结束监听
        if self._pubsub is None:
            return

        try:
            # 无限循环，持续监听 Redis 频道消息
            async for message in self._pubsub.listen():
                # Redis PubSub 会发送多种类型的消息，比如 subscribe、message 等
                # 我们只处理真正的业务消息，类型为 "message"
                if message["type"] != "message":
                    continue

                try:
                    # 把 Redis 传来的 JSON 字符串解析成 Python 字典
                    event: dict[str, Any] = json.loads(message["data"])
                except json.JSONDecodeError:
                    # 如果收到的不是合法 JSON，记录警告并跳过
                    logger.warning(f"AgentBus 收到非法 JSON 消息: {message.get('data')}")
                    continue

                # 取出事件类型，用于分发给对应的订阅者
                event_type = event.get("event_type")

                # ----------------------------------------------------------
                # 把事件分发给订阅了该 event_type 的队列
                # ----------------------------------------------------------
                for queue in self._queues.get(event_type, []):
                    try:
                        # put_nowait 是非阻塞写入
                        # 如果队列已满（maxsize=100），直接丢弃，避免卡住监听任务
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        pass

                # ----------------------------------------------------------
                # 把事件分发给订阅了所有事件的队列
                # ----------------------------------------------------------
                for queue in self._all_queues:
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        pass

        except asyncio.CancelledError:
            # 当 close() 取消这个任务时，会抛出 CancelledError
            # 这里重新抛出，让 asyncio 正常回收任务
            raise
        except Exception as e:
            # 其他异常（比如 Redis 断开）记录日志，任务结束
            logger.warning(f"AgentBus Redis 监听异常: {e}")

    # ============================================================
    # 5. 事件发布
    # ============================================================

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        发布一个事件。

        参数：
            event_type：事件类型，如 "finding_added" / "phase_changed"
            payload：事件内容，会被自动加上时间戳和 session_id
        """
        # 构造标准事件对象，包含类型、会话 ID、UTC 时间戳和业务载荷
        event = {
            "event_type": event_type,          # 事件类型
            "session_id": self.session_id,     # 所属会话
            "timestamp": datetime.now(timezone.utc).isoformat(),  # UTC 时间戳
            "payload": payload,                # 具体业务数据
        }

        # ----------------------------------------------------------
        # 1. 内存广播：发给订阅了该 event_type 的队列
        # ----------------------------------------------------------
        # 从 _queues 中取出所有订阅了 event_type 的队列
        for queue in self._queues.get(event_type, []):
            try:
                # 非阻塞方式把事件放入队列
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 队列满时直接丢弃，避免发布者被阻塞
                pass

        # ----------------------------------------------------------
        # 2. 内存广播：发给订阅了所有事件的队列
        # ----------------------------------------------------------
        for queue in self._all_queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

        # ----------------------------------------------------------
        # 3. Redis 广播：把事件发到 Redis 频道
        # ----------------------------------------------------------
        # 先确保 Redis 客户端已初始化
        await self._connect()

        # 如果 Redis 客户端存在，说明连接成功，执行 Redis 发布
        if self._redis_client is not None:
            try:
                # 把事件序列化成 JSON 字符串，通过 Redis 广播出去
                await self._redis_client.publish(
                    self._channel,
                    json.dumps(event, ensure_ascii=False),
                )
            except Exception as e:
                # Redis 发布失败只记录日志，不影响本地内存广播
                logger.warning(f"AgentBus Redis publish 失败: {e}")

    # ============================================================
    # 6. 事件订阅
    # ============================================================

    async def subscribe(
        self,
        event_type: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        订阅事件。

        参数：
            event_type：可选，只订阅某类事件；None 表示订阅所有事件

        返回：
            异步生成器，可以 for 循环读取事件
        """
        # 为当前订阅者创建一个本地队列，最大长度 100
        # 这个队列会同时接收内存广播和 Redis 广播的消息
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        # 根据 event_type 决定把队列注册到哪一组
        if event_type:
            # 如果有指定事件类型，放到 _queues 里对应的分组
            self._queues.setdefault(event_type, []).append(queue)
        else:
            # 如果没有指定，放到 _all_queues，接收所有事件
            self._all_queues.append(queue)

        # 确保 Redis 监听任务已经启动
        # 这样从其他进程或 Worker 发来的 Redis 消息也能进入这个队列
        await self._connect()

        try:
            # 无限循环，从队列里取事件并 yield 给调用方
            while True:
                # await queue.get() 会在队列空时挂起，直到有新事件
                event = await queue.get()
                yield event
        finally:
            # 当订阅者停止迭代（比如断开 SSE 连接）时，finally 块会执行
            # 这里把当前队列从注册列表中移除，防止内存泄漏
            if event_type:
                if queue in self._queues.get(event_type, []):
                    self._queues[event_type].remove(queue)
            else:
                if queue in self._all_queues:
                    self._all_queues.remove(queue)

    # ============================================================
    # 7. 同步订阅（供 Celery Worker 使用）
    # ============================================================

    def subscribe_sync(
        self,
        event_type: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        同步订阅。

        这个版本主要给 Celery Worker 内部使用，
        但实际 Celery 任务也建议用异步方式。

        注意：当前是占位实现，需要外部协程把事件 push 进 buffer。
        """
        # 用一个普通列表作为事件缓冲区
        buffer: list[dict[str, Any]] = []

        # 直接返回 buffer 的迭代器
        # 实际使用时，需要另外启动一个协程把事件 push 进 buffer
        return iter(buffer)

    # ============================================================
    # 8. 便捷方法：广播发现的风险
    # ============================================================

    async def broadcast_finding(
        self,
        agent_name: str,
        finding: dict[str, Any],
    ) -> None:
        """
        便捷方法：广播发现的风险。

        参数：
            agent_name：发现风险的 Agent 名称
            finding：风险详情字典
        """
        # 构造 finding_added 事件并调用 publish 发布
        from app.agentkit.events import EventType

        await self.publish(
            EventType.FINDING_ADDED,
            {
                "agent_name": agent_name,
                "finding": finding,
                "message": f"{agent_name} 发现新的风险：{finding.get('risk_type', '')}",
            },
        )

    # ============================================================
    # 9. 便捷方法：广播阶段切换
    # ============================================================

    async def broadcast_phase(self, phase: str, message: str) -> None:
        """
        便捷方法：广播阶段切换。

        参数：
            phase：阶段名称，如 "parse" / "review" / "report"
            message：阶段说明文字
        """
        # 构造 phase_changed 事件并调用 publish 发布
        from app.agentkit.events import EventType

        await self.publish(
            EventType.PHASE_CHANGED,
            {
                "phase": phase,
                "message": message,
            },
        )

    # ============================================================
    # 10. 关闭总线
    # ============================================================

    async def close(self) -> None:
        """
        关闭 Redis 连接与监听任务。
        在审查会话结束时调用，释放资源。
        """
        # 标记总线已关闭，后续 _connect 不再重连
        self._closed = True

        # ----------------------------------------------------------
        # 1. 取消 Redis 监听任务
        # ----------------------------------------------------------
        if self._listener_task is not None:
            # cancel() 会给任务发送取消信号
            self._listener_task.cancel()
            try:
                # 等待任务真正结束
                await self._listener_task
            except asyncio.CancelledError:
                # 取消任务时会抛出 CancelledError，这是预期行为，忽略即可
                pass
            # 清空任务引用
            self._listener_task = None

        # ----------------------------------------------------------
        # 2. 关闭 PubSub 客户端
        # ----------------------------------------------------------
        if self._pubsub is not None:
            try:
                # 先退订当前频道
                await self._pubsub.unsubscribe(self._channel)
                # 再关闭 PubSub 连接（redis-py >= 5.0.1 推荐使用 aclose）
                await self._pubsub.aclose()
            except Exception as e:
                # 关闭失败只记录日志，不影响整体关闭流程
                logger.warning(f"AgentBus 关闭 PubSub 失败: {e}")
            self._pubsub = None

        # ----------------------------------------------------------
        # 3. 关闭 Redis 客户端
        # ----------------------------------------------------------
        if self._redis_client is not None:
            try:
                # 关闭底层 Redis 连接池（redis-py >= 5.0.1 推荐使用 aclose）
                await self._redis_client.aclose()
            except Exception as e:
                logger.warning(f"AgentBus 关闭 Redis 客户端失败: {e}")
            self._redis_client = None

        # 重置连接状态
        self._connected = False
