# 事件协议（M0 冻结，只实现不修改）

版本：v1.0 ｜ 对应里程碑：M1' 事件流层（架构 L3）

## 1. 事件信封（envelope）

所有事件在总线上传输时必须是以下 JSON 结构（`AgentBus.publish` 自动补齐时间与会话）：

| 字段 | 类型 | 说明 |
|---|---|---|
| event_type | str | 必须取自 §2 注册表，未知类型 emit 时告警 |
| session_id | int | 审查会话 ID |
| timestamp | str | UTC ISO8601 |
| payload | dict | 业务载荷，按事件类型各有约定 |

代码侧唯一事实源：`app/agentkit/events.py`（EventType 常量 + `emit()` + `review_channel()`）。

## 2. 事件类型注册表

| 分类 | event_type | payload 关键字段 | 发布方 |
|---|---|---|---|
| 生命周期 | phase_changed | phase, message | graph.py |
| | completed / error | message | pipeline.py |
| Agent 执行 | agent_started / agent_completed | agent_name, chunk_id? | base.py |
| 风险产出 | finding_added | agent_name, finding | bus.broadcast_finding |
| | risk_escalated / evidence_found / contradiction_detected | 各业务字段 | base.py 等 |
| 上下文（M2' 新增） | context_assembled | report（ContextReport 各层占用/丢弃） | ContextManager |
| | skills_matched | matched[], question | ChatAgent |
| | memory_loaded | entries_count, user_id | ChatAgent |
| 工具治理（M3' 新增） | tool_permission_denied / tool_permission_pending | tool_name, agent_name, reason | BaseAgent 权限钩子 |
| | tool_permission_approved / tool_permission_rejected | approval_id, tool_name, agent_name | HITL 审批裁决（agentkit/approval.py，HITL_ENABLED 开启时） |
| 面向前端 | progress | step, percent, message | pipeline |

新增事件类型：先在本表登记 + `events.py` 加常量，**禁止**在业务代码里散写字符串字面量。

## 3. 频道命名（单一事实源）

- Redis 频道统一由 `events.review_channel(session_id)` 生成，格式 `review:{session_id}:events`
- `AgentBus` 与 `SSEManager` 必须调用该函数，禁止各自硬编码频道串
- SSE 端点是事件流的普通订阅方；trace（ReviewLogger）是进程内订阅方；两者不得绕过总线直连 Redis

## 4. 消费方规则

1. 一个事件发布一次，所有消费方（SSE / trace / 进度 UI / 未来的回放）通过订阅获得
2. 消费方失败不得影响发布方（订阅侧自行容错）
3. trace 落盘格式：与 `ReviewLogger._append` 记录同构（timestamp/session_id/event_type/elapsed/payload）
