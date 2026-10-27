# 合同卫士平台化改进方案 v2.1（存档）

状态：已批准执行 ｜ 配套协议：`docs/protocols/`（三份，M0 冻结）

## 设计原则

| 原则 | 含义 |
|---|---|
| 接口先行，机制后长 | 先定死接口，实现按触发条件补，将来只加不改 |
| 一切皆插件 | 新 Agent / prompt 层 / 工具 / 模型 / 租户 = 注册一个实现，不碰主链路 |
| 触发式生长 | 每个重机制写明触发信号，不为不存在的需求写空架子 |

## 目标能力架构（终态 7 层）

| 层 | 职责 | 现状→目标 |
|---|---|---|
| L1 引擎核心 | 审查编排、13 Agent、ReAct | ✅ |
| L2 装配层 | ContextManager 分层预算装配全部 prompt 层 | 拼接散落 → context/ 四模块 |
| L3 事件流层 | 类型化事件，一个流供 SSE/trace/审计/UI | SSE+死代码 trace → 总线统一订阅 |
| L4 工具治理 | 注册表、权限三态、HITL 钩子 | 硬编码 dict → @register_tool |
| L5 能力沉淀 | 技能、记忆、反例闭环、黄金集评测 | 零件齐（M1 已闭环）→ 挂统一入口 |
| L6 状态恢复 | 会话状态持久化、断点续跑 | 内存态 → StateStore 抽象 |
| L7 接入部署 | Engine Facade 无状态化、被大项目集成 | 与 FastAPI 耦合 → ReviewFacade |

## 里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M0 协议 | 三份协议文档冻结 | 文档评审通过 |
| M1 ✅ | 回测→反例→prompt 闭环 + 报告（已完成） | 保留，未来改走 Layer 注册 |
| M1' 事件流 | events.py 协议实现 + 频道单一源 + ReviewLogger 复活为总线订阅方 + SSE 显式化 | 一次审查 trace 有全量事件 |
| M2' 装配层 | context/ 四模块（budget/strategy/tokens/manager）+ 技能运行时化 + 跨会话记忆，三者全走 assemble() | 见 §M2 细则 |
| M3' 工具治理 | @register_tool 装饰器 + 权限三态 + HITL 钩子留位 | 配置即可改权限 |
| M4' 引擎门面 | ReviewFacade + StateStore 抽象 | 无 FastAPI 可跑审查 |

## M2' 三大能力细则

### 上下文自动管理（L2 骨架）
- `agentkit/context/`：budget.py 分层预算（config 可调）、strategy.py 策略协议（首发 truncate，预留 offload/compress）、tokens.py token 计数抽象（首发 CharEstimator：ASCII 4 字符≈1 token，非 ASCII 权重 2）、manager.py 唯一装配入口
- 首接线点：ChatAgent 历史装配（唯一无限增长处）；存量手工 `[:3000]` 按 Boy Scout 逐步迁
- 每次装配发布 context_assembled 事件（ContextReport 各层占用/丢弃），接入 M1' 可审计
- 触发式：落盘←万字级工具返回；压缩←history 成为报告 top 消耗；真 tokenizer←第二模型

### 技能仓库运行时化
- 注册方式：`skills/<name>/SKILL.md` 正文 + `skills/index.json` 清单（entry 路径 + keywords 触发词；实现最终未用 frontmatter，以清单为唯一事实源）+ 修正过期路径
- `agentkit/skills.py`：load_skills / match_skills（关键词匹配）/ render_skills
- ChatAgent 问答前匹配 → Layer("skills") 注册进 assemble()；不做 embedding 匹配（匹配不够准再升级）

### 跨会话记忆
- `agentkit/memory.py`：`memory/users/{user_id}.md`，行格式 `[时间] 类型: 内容`
- 写入：用户 dismiss 风险时（复用反馈链路加一行）+ 追问中的显式偏好
- 读取：ChatAgent 回答前加载 top 条目 → Layer("memory") 进 assemble()
- 防膨胀：封顶 20 条留最新、每条 200 字内；不做向量化检索

## 扩展场景检查表

| 未来需求 | 落在插槽 | 改动量 |
|---|---|---|
| 加第 N 个 Agent | L1 注册 | 只写 Agent |
| 新 prompt 层 | L2 新 Layer + 配额 | 十几行 |
| 换/加模型 | L2 配置 + L1 client | 配置为主 |
| 大项目集成 | L7 Facade | 调 API |
| 审计新指标 | L3 订阅事件流 | 不碰审查代码 |
| 断点续跑/滚动升级 | L6 换存储实现 | 换一个类 |
| 大文档多文件审查 | L2 offload 实例化 | 启用预留策略 |

## 执行顺序

M0 → M1' → M2'（骨架→技能→记忆）→ M3' → M4'，每里程碑验证 + 报告；git 操作由用户自行完成。
