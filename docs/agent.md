# 合同卫士 — Agent 模块深度解析

> 本文档面向负责 Agent 模块开发和面试准备的读者，全面拆解：
> - Agent 整体架构与多 Agent 协作模式
> - 每个 Agent 的功能、实现与调用链
> - 工具函数的设计与实现
> - Agent 之间如何通信
> - ReAct 推理循环
> - 共享记忆图 SessionGraph 的作用
> - Prompt 设计与编写要点
> - 八阶段审查管线详解
>
> 目标：读完本文档后，能够清晰回答任何关于 Agent 模块的面试问题。

---

## 一、Agent 整体架构

### 1.1 多 Agent 模式：编排式 Multi-Agent

本项目采用的是 **编排式 Multi-Agent（Orchestrated Multi-Agent）**，不是 Main Agent + Sub-Agent 的树状模式。

#### 两种模式的区别

**Main Agent + Sub-Agent 模式的特点**：
- 有一个主 Agent 负责理解用户意图、分解任务
- 主 Agent 把子任务派发给各个子 Agent
- 子 Agent 执行完毕后把结果返回给主 Agent
- 主 Agent 汇总后输出最终答案

**编排式 Multi-Agent 模式的特点**：
- 没有主 Agent，由外部调度器统一管理
- 调度器决定哪个阶段启动哪些 Agent
- Agent 之间不直接通信，通过共享存储协作
- 每个 Agent 只关注自己的专业领域

**本项目选择编排式的原因**：

1. **职责分离清晰**：Coordinator 专门做调度，Agent 专门做业务审查，各司其职
2. **并行效率高**：Execute 阶段多个 Agent 可以同时运行，不用等上一个返回
3. **扩展方便**：新增 Agent 只需要在 Coordinator 注册，不需要修改其他 Agent
4. **状态可控**：所有中间结果都写在 SessionGraph，方便调试和追溯

### 1.2 整体架构图

系统的核心由三层组成：

**第一层：调度层（ReviewCoordinator）**
- 负责八阶段管线的流转（Route → Preload → LegalResearch → Execute → Merge+Link → LegalVerify → Debate → Triage）
- 决定每个阶段启动哪些 Agent
- 通过 AgentBus 发布阶段切换事件

**第二层：通信层（AgentBus）**
- 基于 Redis Pub/Sub 实现事件广播
- 让 Coordinator 和 Agent 能实时同步状态
- 生产环境必须直接使用 Redis，不再降级为内存队列

**第三层：Agent 层**
- 15 个专业 Agent 各司其职（含 BaseAgent）
- 从 SessionGraph 读取输入，把结果写回 SessionGraph
- 通过调用工具函数获取外部信息

**第四层：共享存储层（SessionGraph）**
- 存储所有中间结果和最终结论
- 支持 Agent 之间异步协作
- 可以持久化到数据库或快照到 Redis

### 1.3 Coordinator 的作用

Coordinator 是整个审查流程的调度中心，它不直接参与合同审查，而是负责：

**路由分配**：
- 扫描每个合同条款的内容
- 根据关键词判断应该派给哪些 Agent
- 给出初始风险等级预判

**预加载准备**：
- 把合同条款写入 SessionGraph
- 调用 TermExtractionAgent 提取甲乙双方信息
- 把合同条款向量化写入 Qdrant

**动态法律研究（LegalResearch）**：
- 调用 LegalResearchAgent 推断合同适用法律领域
- 检索相关法律条文并生成审查要点
- 将结果写入 SessionGraph 的 Law 节点，供后续 Agent 引用

**并行调度**：
- 用 asyncio.gather 同时启动多个 Agent
- 收集各 Agent 的输出日志
- 处理 Agent 执行过程中的异常

**结果整合**：
- 合并重复风险（基于法律指纹 + 文本相似度）
- 发现跨条款组合风险
- 补充和验证法律依据
- 对高风险项进行辩论裁决
- 最终分类输出结果

**红线检测层（RedFlagDetector）**：
- 作为 RiskReviewAgent 的第一层防线
- 基于通用法律原则（比例原则、权利保留原则等）做确定性红线检测
- 对明显违法条款强制输出，避免 LLM 漏检

### 1.4 Agent 之间的协作方式

Agent 之间主要通过两种方式协作：

**方式一：共享记忆图（主要方式）**

这是 Agent 协作的核心机制。每个 Agent 执行完后，把结果写入 SessionGraph；后续 Agent 从 SessionGraph 读取已有结论继续处理。

例如：
- RiskReviewAgent 发现"试用期超长"，创建 Risk 节点
- LegalBasisAgent 读取所有 Risk 节点，为"试用期超长"查询法条
- SuggestionAgent 再读取 Risk 节点，生成修改建议
- DebateAgent 读取 high 等级的 Risk，进行正反辩论

**方式二：消息总线（实时事件）**

AgentBus 提供 Redis Pub/Sub 广播能力，主要用于：
- Coordinator 发布阶段切换事件，前端 SSE 接收后更新进度条
- Agent 发现风险后广播 finding_added 事件，其他 Agent 可订阅响应
- 审查完成后发布 completed 事件，触发后续流程

**重要说明**：Agent 之间**不是**简单的"上一个 Agent 的输出作为下一个 Agent 的输入"的 Pipeline 模式。而是：
- 多个 Agent 同时往 SessionGraph 写结果
- 后续 Agent 从 SessionGraph 读需要的信息
- Agent 之间没有直接调用关系

---

## 二、Agent 基类设计

### 2.1 BaseAgent 的作用

所有 Agent 都继承自 BaseAgent，它定义了 Agent 运行的统一框架。

**BaseAgent 包含的核心属性**：

1. **name**：Agent 的名称，如 "RiskReviewAgent"、"LegalBasisAgent"
2. **system_prompt**：系统提示词，定义 Agent 的角色、能力和输出格式
3. **tools**：该 Agent 可以调用的工具函数字典
4. **max_turns**：ReAct 循环的最大轮次，防止无限循环
5. **logs**：运行日志，记录每一步的思考和行动
6. **llm_client**：LLM 客户端，用于调用大模型

**BaseAgent 提供的核心方法**：

1. **run 方法**（抽象方法）：每个具体 Agent 必须实现自己的 run 方法，定义具体审查逻辑

2. **_react_loop 方法**：实现 ReAct 推理循环，把任务传给 LLM，解析返回的 JSON

3. **_call_tool 方法**：调用指定工具函数，处理异步调用和异常

4. **publish_progress 方法**：通过 AgentBus 发布进度事件，让前端知道当前状态

5. **_parse_json_output 方法**：从 LLM 输出中解析 JSON，处理多种格式（纯 JSON 或 markdown 代码块）

### 2.2 每个 Agent 的实现模式

所有具体 Agent 都遵循相同的实现模式：

**第一步：初始化**
- 调用父类构造函数，传入 name、system_prompt、tools、max_turns
- 定义自己专有的属性（如果有）

**第二步：实现 run 方法**
- 从 context 或 session_graph 获取输入数据
- 构造 task_prompt，把具体任务描述传给 LLM
- 调用 _react_loop，让 LLM 推理并返回结构化结果
- 解析 LLM 输出的 JSON
- 把结果写入 SessionGraph
- 返回 findings 和 logs

---

## 三、15 个 Agent 的详细说明

### 3.1 Agent 总览表

| 序号 | Agent 名称 | 主要职责 | 主要工具 | 写入节点 |
|------|-----------|----------|----------|----------|
| 1 | TermExtractionAgent | 提取甲乙双方、合同期限、岗位 | read_section | Party |
| 2 | LegalResearchAgent | 动态推断适用法律并检索法条 | search_knowledge、web_search | Law |
| 3 | RiskReviewAgent | 识别不公平/高风险条款（集成 RedFlagDetector + CriticAgent） | search_knowledge、search_document、output_finding | Risk |
| 4 | MissingClauseAgent | 检查必要条款缺失 | read_section | Risk |
| 5 | BalanceAgent | 分析权利义务对等性 | extract_obligations、search_knowledge、output_finding | Risk |
| 6 | CrossReferenceAgent | 检查条款间引用一致性（已启用 function calling） | check_cross_reference、read_section | Risk、RELATES_TO / CONTRADICTS 边 |
| 7 | LegalBasisAgent | 为风险补充法律依据 | search_knowledge、query_knowledge_graph | 更新 Risk 的 law_refs |
| 8 | SuggestionAgent | 生成具体修改建议 | read_section、search_knowledge | 更新 Risk 的 suggestion |
| 9 | IndustryComplianceAgent | 行业特殊合规检查 | search_knowledge、output_finding | Risk |
| 10 | LegalVerifyAgent | 验证法条引用准确性（已启用 function calling） | search_knowledge、web_search、query_knowledge_graph | 更新 Risk 的 verified |
| 11 | DebateAgent | 对高风险项正反辩论（已启用 function calling） | search_knowledge、search_document、read_section | 更新 Risk 的置信度和等级 |
| 12 | BlindSpotAgent | 扫描盲区 | read_section | Risk |
| 13 | HumanReviewAgent | 标记人工复核项 | 无 | 更新 Risk 的 needs_human_review |
| 14 | CriticAgent | 对 RiskReviewAgent 的候选风险做二次校验 | 无（RuleCritic + LLM Critic） | 更新 Risk 的 verdict / confidence |
| 15 | ChatAgent | 基于 SessionGraph 回答用户追问 | search_document、read_section | 无 |

### 3.2 TermExtractionAgent（信息提取 Agent）

**职责**：从合同中提取基础商务信息。

**提取的内容**：
- 甲方名称（用人单位）
- 乙方名称（劳动者）
- 合同期限
- 工作岗位

**实现方式**：

这个 Agent 没有调用 LLM，而是使用正则表达式直接从合同文本中提取信息。原因是：
- 甲方/乙方的位置在合同中相对固定，通常以"甲方："、"乙方："开头
- 正则提取速度快、成本低、准确性高
- 不需要 LLM 的创造性推理能力

**具体提取逻辑**：

1. **提取甲方/乙方名称**：
   - 用正则匹配"甲方：XXX"或"甲方：XXX"的格式
   - 提取冒号后面的内容作为名称
   - 过滤掉括号内的补充说明

2. **提取合同期限**：
   - 用正则匹配"合同期限：XXX"的格式
   - 提取期限描述，如"三年"、"自2024年1月1日至2027年1月1日"

3. **提取工作岗位**：
   - 用正则匹配"工作岗位："、"职位："、"职务："等关键词
   - 提取冒号后面的职位名称

**输出**：在 SessionGraph 中创建两个 Party 节点，分别代表甲方和乙方。

### 3.3 LegalResearchAgent（动态法律研究 Agent）

LegalResearchAgent 是正式审查前的**法律情报准备阶段**。它不看完整合同，而是快速判断"这份合同可能涉及哪些法律、要重点查什么"，然后把查到的法条和审查重点交给 RiskReviewAgent 使用。

它的核心目标是三个：**推断法律领域、检索相关法条、生成审查清单**。

#### 核心流程

整个 Agent 可以概括为四步：

**第一步：读合同摘要**

把合同 chunks 拼成一段精简摘要，控制在 3500 字以内。这里不需要读全文，只需要让 LLM 判断合同类型和可能涉及的法律问题。

**第二步：推断法律领域和风险信号**

用一次 LLM 调用，同时完成两件事：

- **法律领域**：输出合同可能涉及的法律领域、法律名称、条款号和检索关键词。例如"试用期 | 劳动合同法 | 第十九条 | 试用期 合同期限 上限"。
- **风险信号**：输出合同中是否出现值得警惕的异常表述。例如"试用期约定可能超过法定上限"。

这两个任务合并成一次调用，是为了减少 LLM 调用次数。推断结果会做后处理：去重、过滤明显不匹配合同类型的法律。如果 LLM 调用失败，则按合同类型返回默认领域兜底。

**第三步：分层检索法条**

对每个推断出的法律领域，按三层策略找法条：

1. **本地知识库优先**：用关键词检索 Qdrant / PostgreSQL 里的法律知识。
2. **精准联网检索**：如果 LLM 已经明确给出了法律名称和条款号，直接抓这条原文。
3. **泛化联网检索兜底**：用 Tavily 做 broader 搜索，但**每个合同最多 3 次**。

这里有一个关键优化：**如果本地和精准检索都没命中，且该领域风险信号弱，就直接跳过泛化联网搜索**。这样不会在明显合法的合同上空转，是解决之前合法合同审查耗时过长的主要手段之一。

检索到的法条会经过合并、去重和相关性过滤，每个领域最终只保留最相关的 **1 条**法条，避免后续审查被过多法条淹没。

**第四步：生成审查要点并写入图谱**

把法条转成 RiskReviewAgent 能用的"审查要点"。转换时优先走缓存和预制模板，常见法条不调用 LLM；只有冷门法条才让 LLM 总结。如果 LLM 不可用，就从法条原文中提取完整句子兜底。

处理好的法条作为 `Law` 节点写入 SessionGraph。如果一条法条都没找到，会保底写入"诚实信用与公平原则"这个通用节点，确保后续审查有法可依。

最后，根据已发现的法律和识别的风险信号，生成一份**动态审查清单**，一起返回给 Coordinator。

#### 输出内容

LegalResearchAgent 返回三类关键信息：

- **discovered_laws**：检索到的法条及审查要点。
- **review_checklist**：本次审查应重点关注的检查项。
- **risk_signals**：合同中识别出的风险信号。

#### 关键设计思想

这个 Agent 的设计核心是**"先判断有没有事，再决定花多大代价查"**。

- 合同明显正常时，减少 LLM 和联网调用，快速通过；
- 合同有可疑信号时，才深入检索法条、生成详细清单；
- 高频法条和常见查询走缓存与模板，不重复调用模型；
- 每个领域只保留一条核心法条，控制下游 prompt 长度。

下游的 RiskReviewAgent 会拿着这些法条和清单，逐条核对合同条款是否存在风险。

### 3.4 RiskReviewAgent（风险审查 Agent）

RiskReviewAgent 是合同审查的**主审律师**。它逐条审查合同条款，识别不公平、违法或高风险内容，也是 RedFlagDetector 和 CriticAgent 的集成入口。

它的核心目标是三个：**逐条发现风险、过滤误报、保留高质量结论**。

#### 核心流程

**第一步：获取审查上下文**

从上游 LegalResearchAgent 拿到 `discovered_laws`、`review_checklist`、`risk_signals`，从 Preload 拿到 `chunks`。这些是它的"参考资料"和"检查清单"。

**第二步：逐条审查每个 chunk**

RiskReviewAgent 对每个合同段落都走一条"由硬到软、由快到慢"的处理流水线。整个流程像工厂质检：先过红外检测仪，再过人工抽检，最后由复核员把关。

**2.1 红线扫描**

首先调用 RedFlagDetector，对当前条款做原则性红线检测。红线分两类：

- **数值型红线**：从条款文本中提取数字并和法定阈值比对。例如日违约金超过 0.1%、一次性违约金超过合同标的 30%、年利率超过 12%、试用期超过法定上限等。这类红线不依赖 LLM，命中即给出高置信结论。
- **语义型红线**：对不好直接用规则判断的表述，先用向量模型召回可能触犯的法律原则，再用轻量 LLM 实例化判断。例如"工伤概不负责""自愿放弃社保"等表述，语义上明显违反法律原则，会被命中。

红线扫描的输出会告诉后续步骤：这条条款是否触碰了明确红线、触碰了哪类红线、严重程度如何。

**2.2 关键词过滤**

如果一条条款既没有命中确定性红线，也不包含任何可疑关键词（如涉及违约金、解除、赔偿、社保、竞业限制、试用期等），这条条款通常不需要进入 LLM 审查。

这一步是为了减少无效调用。大量合同条款只是普通的权利义务描述，没必要每次都让 LLM 看一遍。

**2.3 LLM 审查**

对需要通过 LLM 审查的条款，会把以下信息打包进任务提示：

- 当前条款原文；
- 从 LegalResearchAgent 拿到的相关法律依据和审查清单；
- 当前合同类型的风险提示；
- 红线扫描的命中信息；
- 若干相似案例作为参考。

LLM 被要求输出结构化的风险结论，包括风险类型、等级、置信度、原因说明和修改建议。这样结果可以直接写入 SessionGraph，不需要额外解析。

**2.4 红线兜底覆盖**

有时候会出现规则已经明确判断为 high 风险，但 LLM 出于保守或理解偏差给出了 low 风险。这种情况下，系统会以红线结果为准，强制把风险等级提升为 high，并同步更新原因和修改建议。

这一步的关键是**同步更新**：不能只改等级而不改理由，否则会出现"等级 high，但原因里写着没问题"这种自相矛盾的报告。

**2.5 Critic 二次校验**

LLM 审查完成后，候选风险还会进入 CriticAgent 做二次校验。但不是所有风险都过 Critic：

- **高置信证据类型直接保留**：例如数值型违法、明确违反法律禁止性规定的情况，规则已经给出确定性结论，不需要再让 Critic 浪费时间。
- **其他候选风险进入 Critic**：先用 15 条通用法律常识规则快速判断。如果规则明确说这是误报，直接过滤或降级；如果规则拿不准，再交给轻量 LLM Critic 做最终判断。

经过 Critic 后，剩下的风险才是真正要保留的。

**第三步：整体性审查**

如果逐条审查没发现任何 high/medium 风险，也没有 surviving 的确定性红线，就**跳过全文 LLM 审查**，避免在合法合同上硬找问题。否则对合同整体做一次审查，发现跨条款的结构性风险。

**第四步：写入 SessionGraph**

对保留的 high/medium 风险创建 Risk 节点，建立 Clause 到 Risk 的关联，并记录证据类型、法律原则、法律依据等溯源信息。

#### 输出内容

每个风险包含：风险类型、等级（high/medium/low）、置信度、原因说明、修改建议、法条引用、证据类型。

#### 关键设计思想

- **先规则、后 LLM**：确定性红线不依赖 LLM，又快又稳；
- **Critic 兜底**：LLM 可能过度敏感，用规则反常识过滤器把误报降下来；
- **合法合同快速通过**：没有风险信号时跳过整体审查，减少空转。

### 3.5 MissingClauseAgent（缺失条款 Agent）

MissingClauseAgent 负责检查劳动合同是否缺少《劳动合同法》第 17 条规定的必要条款。

它的核心目标是：**识别法定必备条款的缺失项**。

#### 核心流程

**第一步：合并合同文本**

把合同 chunks 拼接成完整文本，截取前 3000 字左右传给 LLM。

**第二步：让 LLM 核对必备条款清单**

必备条款包括：用人单位信息、劳动者信息、合同期限、工作内容与地点、工作时间与休息休假、劳动报酬、社会保险、劳动保护与条件。

**第三步：解析并写入 SessionGraph**

LLM 返回缺失的条款项，Agent 为每个缺失项创建 Risk 节点，并标记为缺失条款类问题。

#### 关键设计思想

- 用法定清单约束 LLM，避免漏检；
- 只适用于劳动合同，对其他合同类型不强行套用；
- 缺失条款通常风险等级偏中低，但属于硬性合规问题。

### 3.6 BalanceAgent（公平性 Agent）

BalanceAgent 负责从全局视角审视合同双方权利义务是否对等。

它的核心目标是：**发现整体结构上的不公平，而不是单条条款的违法**。

#### 核心流程

**第一步：合并合同文本**

把合同关键内容拼接后传给 LLM。

**第二步：LLM 横向对比分析**

让 LLM 从以下角度审查：
- 是否只有一方承担义务；
- 违约金、赔偿责任是否明显偏向一方；
- 解除权、变更权是否不公平分配；
- 竞业限制、保密义务是否单方面强加。

**第三步：写入 SessionGraph**

对发现的不对等问题创建 Risk 节点，标记为公平性问题。

#### 关键设计思想

- 与 RiskReviewAgent 互补：RiskReviewAgent 查"是否违法"，BalanceAgent 查"是否公平"；
- 公平性需要从整体看，不能靠逐条审查发现；
- 适合发现"多个条款组合起来对某一方明显不利"的情况。

### 3.7 CrossReferenceAgent（交叉引用 Agent）

CrossReferenceAgent 负责检查合同前后条款是否存在矛盾或冲突。

它的核心目标是：**发现条款之间的内在不一致**。

#### 核心流程

**第一步：读取所有 Clause 节点**

从 SessionGraph 获取合同的段落结构。

**第二步：识别潜在关联条款对**

通过关键词匹配，找出可能相关的条款对，例如都提到"试用期"、"期限"、"工作地点"、"社保"的条款。

**第三步：检查冲突**

对关联条款对进行规则比对，典型场景包括：
- 试用期长度与合同期限是否匹配；
- 是否既约定放弃社保又约定工资含社保补贴；
- 工作地点的明确约定与"服从调配"是否冲突。

**第四步：写入 SessionGraph**

发现冲突后创建 Risk 节点，并在两个 Clause 之间建立关联或冲突关系。

#### 关键设计思想

- 单条条款可能没问题，但组合起来可能违法或不合理；
- 用规则做明确冲突检测，避免全凭 LLM 判断；
- 跨条款风险往往需要人工重点关注。

### 3.8 LegalBasisAgent（法律依据 Agent）

LegalBasisAgent 负责为已经发现的风险补充法律依据。

它的核心目标是：**让每个风险都有法条支撑**。

#### 核心流程

**第一步：读取 Risk 节点**

从 SessionGraph 拿到所有风险。

**第二步：跳过已有法条的风险**

如果 Risk 节点已经有 `law_refs`，说明法律依据已补齐，不再重复查询。

**第三步：根据风险内容检索法条**

根据风险类型和原因构造关键词，调用法律知识库检索。例如"试用期超长"检索"试用期"，"社保规避"检索"社会保险"。

**第四步：更新 Risk 节点**

把检索到的法条引用写入 Risk 节点的 `law_refs` 字段。

#### 关键设计思想

- 提高审查报告的可信度，让用户看到"为什么这条有风险"；
- 为后续 LegalVerifyAgent 验证法条做准备；
- 本身不产生新风险，只给已有风险"找依据"。

### 3.9 SuggestionAgent（修改建议 Agent）

SuggestionAgent 负责为已经发现的风险生成具体、可执行的修改建议。

它的核心目标是：**把风险结论转化成用户能直接用的修改方案**。

#### 核心流程

**第一步：汇总风险信息**

从 SessionGraph 读取风险，整理每个风险的类型、等级、条款原文、原因，批量汇总（通常一次处理最多 10 条）。

**第二步：批量请求 LLM 生成建议**

把多个风险一起传给 LLM，让它为每个风险输出：原文内容、修改后的文本、修改理由。

**第三步：匹配并更新 Risk 节点**

按风险类型把建议匹配回对应 Risk 节点，更新 `suggestion` 字段。

#### 关键设计思想

- 批量处理减少 LLM 调用次数；
- LLM 同时看多个风险，能给出更一致的修改风格；
- 建议要具体，最好给出修改后文本，而不是泛泛地说"请合法约定"。

### 3.10 IndustryComplianceAgent（行业合规 Agent）

IndustryComplianceAgent 负责检查合同是否满足特定行业的特殊合规要求。

它的核心目标是：**发现通用审查容易忽略的行业特有风险**。

#### 核心流程

**第一步：确定行业关注重点**

根据合同类型和行业信息，选择该行业的重点合规维度。例如医药行业关注临床试验规范、药品推广合规；金融行业关注反洗钱、适当性义务、信息披露。

**第二步：LLM 识别行业风险**

让 LLM 从行业合规角度审查合同，返回结构化风险列表。

**第三步：规则兜底**

同时用规则检查一些明显违法的通用表述，例如"自愿放弃社保""工伤概不负责"等，即使 LLM 漏掉也能被抓到。

**第四步：写入 SessionGraph**

发现的风险创建 Risk 节点，标记为行业合规问题。

#### 关键设计思想

- 行业差异大，纯规则覆盖不全，所以用 LLM 做灵活识别；
- 但纯 LLM 可能漏掉明显违法项，所以保留规则兜底；
- 扩展新行业时，只需要补充行业关注点和相关法规。

### 3.11 LegalVerifyAgent（法条验证 Agent）

LegalVerifyAgent 负责验证 Risk 节点引用的法条是否真实、准确、有效。

它的核心目标是：**防止 LLM 编造法条或引用过时法条**。

#### 核心流程

**第一步：读取 Risk 节点的法条引用**

从 SessionGraph 获取每个风险关联的 `law_refs`。

**第二步：逐条验证**

在知识库中精确匹配法条编号，核对法条内容是否与原文一致，检查是否存在更新或废止的版本。

**第三步：更新验证状态**

验证通过的法条标记为已验证；验证失败的标记为未通过，并适当降低风险置信度。

#### 关键设计思想

- LLM 可能"幻觉"出不存在或编号的法条，需要独立验证；
- 验证失败不代表风险一定不存在，但要在报告中提示法律依据存疑；
- 是报告可信度的最后一道把关。

### 3.12 DebateAgent（辩论 Agent）

DebateAgent 负责对高风险或低置信度的风险进行正反辩论，减少误判。

它的核心目标是：**对不确定的风险做二次确认**。

#### 核心流程

**第一步：筛选需要辩论的风险**

通常选择 high 等级风险、置信度低于 0.7 的风险，或存在争议的风险。

**第二步：正方论证**

论证"这确实是一个风险"，引用法条和合同原文，说明应该修改的理由。

**第三步：反方论证**

论证"这可能不是风险"或"存在例外"，引用可以减轻或豁免的条款，说明特殊场景。

**第四步：输出并应用辩论结论**

DebateAgent 会针对每个 high 风险输出一个结论：保留、降级或撤销，并附上理由。这个结论会被写回对应 Risk 节点的 `debate_conclusion` 属性中。

在 Triage 阶段，Coordinator 会读取每个 Risk 节点的 `debate_conclusion` 并执行相应操作：
- **保留**：风险原样进入最终报告；
- **降级**：风险等级降一级（high → medium，medium → low），再进入报告；
- **撤销**：该风险被过滤掉，不进入最终报告。

这样辩论不再只是参考记录，而是真正参与了最终结果的裁决。

#### 关键设计思想

- LLM 可能过度敏感，通过正反观点平衡可以减少误报；
- 高风险项尤其需要谨慎确认；
- 辩论结论直接作用于最终输出，提高自动化程度；
- 只处理 high 风险且最多 5 个，避免辩论本身成为性能瓶颈。

### 3.13 BlindSpotAgent（盲区扫描 Agent）

BlindSpotAgent 负责从全局视角扫描其他 Agent 可能遗漏的风险。

它的核心目标是：**补全审查盲区，发现隐藏问题**。

#### 核心流程

**第一步：读取已有审查结果**

从 SessionGraph 获取所有已发现的 Risk 节点和所有 Clause 节点，了解合同全貌和已有结论。

**第二步：LLM 全局扫描**

让 LLM 从全局角度发现遗漏，明确要求不要重复已有风险。关注点包括：合同提到某主题但缺少配套约定、多个风险之间的叠加效应、行业特殊但常见的问题。

**第三步：规则兜底**

用规则检查"提到关键主题但缺少配套约定"的情况，例如提到竞业限制却没有补偿金、提到培训却没有服务期约定。

**第四步：写入 SessionGraph**

发现的新风险创建 Risk 节点，标记为盲区扫描结果。

#### 关键设计思想

- 必须等其他 Agent 执行完再运行，否则不知道"哪些已经查过了"；
- 重点发现"隐含的、组合的、遗漏的"问题；
- 避免重复，只做补充。

### 3.14 HumanReviewAgent（人工复核 Agent）

HumanReviewAgent 负责在最终输出前，判断哪些风险需要人工专家复核。

它的核心目标是：**把最需要专家把关的问题挑出来**。

#### 核心流程

**第一步：遍历所有 Risk 节点**

读取每个风险的等级、置信度、法条引用、各种标记字段和条款原文。

**第二步：多维度判断是否需要复核**

需要复核的典型情况包括：
- high 等级风险；
- 置信度低于 0.7 的风险；
- 跨条款组合风险；
- 公平性争议；
- 缺少法律依据或法条验证未通过；
- 多个 Agent 交叉发现的同类风险；
- 涉及违约金、解除、工伤、社保、竞业限制等重大利益；
- 行业合规问题和盲区扫描发现的问题。

**第三步：生成复核建议并排序**

为每个需要复核的项生成复核原因和建议操作，按风险等级降序、置信度升序排列，高风险且低置信度的排在最前。

#### 关键设计思想

- LLM 不是万能的，高风险决策需要人工最后把关；
- 把复核项按优先级排序，方便专家高效处理；
- 本身不做裁决，只给出"建议人工再看一遍"的提示。

### 3.15 CriticAgent（二次校验 Agent）

CriticAgent 负责对 RiskReviewAgent 提出的候选风险做二次校验，减少误报。它本身不独立参与 Coordinator 管线，而是由 RiskReviewAgent 在逐条审查时调用。

它的核心目标是：**过滤掉明显是误报的风险**。

#### 核心流程

**第一步：RuleCritic 规则快速判断**

用 15 条通用法律常识规则快速审查候选风险：
- 结论与理由是否自相矛盾；
- 是否把合法限制误判为违法（如"不得用于赌博"）；
- 是否把正常商业安排误判为风险（如违约金与赔偿损失并用）；
- 是否忽略法律默认规则（如未约定质量标准不等于排除质保）。

规则判断有三种结果：明确误报直接过滤、明确成立直接保留、不确定进入下一步。

**第二步：LLM Critic 轻量复核**

对规则不确定的边界情况，用轻量 LLM 做最终判断，输出保留、调整等级或过滤的结论。

#### 关键设计思想

- 规则处理 obvious 误报，速度快、成本低；
- LLM 处理边界情况，保证灵活性；
- 规则基于通用法律原则，不能做成测试集补丁；
- 误报样本可以进入反例库，持续学习。

### 3.16 ChatAgent（对话 Agent）

ChatAgent 负责基于合同审查结果回答用户的追问。

它的核心目标是：**让用户看懂审查结果，并给出针对性的法律建议**。

#### 核心流程

**第一步：读取问题和对话历史**

从 context 拿到用户当前问题和最近几轮对话记录。

**第二步：导出审查结果**

把 SessionGraph 中的关键风险和条款导出为自然语言文本，优先保留高风险项，避免超出 LLM 上下文窗口。

**第三步：生成回答**

把审查结果、历史对话、当前问题一起传给 LLM，生成结构化回答，包含回答内容和引用的风险类型。

#### 关键设计思想

- 回答必须基于 SessionGraph 中的审查结果，不编造不存在的内容；
- 只回答与合同、审查结果、法律建议相关的问题，超出范围礼貌拒绝；
- 多轮对话保留上下文，能理解追问；
- 不预测具体司法判决，不推荐具体律师。

---

## 四、工具函数详解

### 4.1 工具总览表

| 工具名称 | 作用 | 主要使用者 |
|----------|------|-----------|
| search_knowledge | 法律知识库检索（Qdrant 语义 + SQL 关键词降级） | RiskReviewAgent、LegalBasisAgent、SuggestionAgent、LegalResearchAgent |
| search_document | 合同内条款检索（Qdrant 语义 + 本地关键词降级） | RiskReviewAgent、CrossReferenceAgent、DebateAgent、ChatAgent |
| read_section | 读取指定章节内容 | TermExtractionAgent、MissingClauseAgent、CrossReferenceAgent |
| output_finding | 把风险写入 SessionGraph | RiskReviewAgent、BalanceAgent、IndustryComplianceAgent |
| check_cross_reference | 检查两个条款是否一致 | CrossReferenceAgent |
| extract_obligations | 提取双方权利义务 | BalanceAgent |
| validate_calculation | 验证数字计算合理性 | RiskReviewAgent |
| compare_with_template | 与标准模板对比 | RiskReviewAgent |
| query_knowledge_graph | 查询 Neo4j 法律知识图谱 | LegalBasisAgent、LegalVerifyAgent |
| web_search | 联网搜索最新法规（Tavily，每个合同最多 3 次泛化搜索） | LegalVerifyAgent、LegalResearchAgent |

### 4.2 工具注册方式

工具函数的注册分两步：

**第一步：在 Coordinator 中注册工具**

在 ReviewCoordinator._register_tools 方法中，把每个工具函数导入并注册到 tools 字典中。key 是工具名称，value 是函数对象。

**第二步：按需传给 Agent**

在 ReviewCoordinator._register_agents 方法中，根据每个 Agent 的需要，传入对应的工具字典。例如：
- RiskReviewAgent 需要 search_knowledge、search_document、read_section、output_finding
- LegalBasisAgent 只需要 search_knowledge 和 query_knowledge_graph

### 4.3 search_knowledge 工具详解

**作用**：查询法律知识库，返回相关法条。

**检索策略：双层架构**

**第一层：向量语义检索（优先）**

- 用 BGE-M3 模型把查询文本编码成 1024 维向量
- 在 Qdrant 的 knowledge_articles collection 中做相似度搜索
- 返回相似度最高的 top-k 条法条
- 优点：能命中语义相关但关键词不同的法条

**第二层：SQL 关键词检索（降级）**

- 当 Qdrant 服务未启动、模型加载失败或向量检索失败时，自动降级
- 在 PostgreSQL/SQLite 中用 LIKE 语句做关键词匹配
- 搜索范围包括：law_name、article_number、article_text、article_title
- 多个关键词用 OR 连接

**输入参数**：
- query：查询文本，如"试用期限制"
- category：可选，限定法律类别，如"劳动合同法"
- limit：返回条数，默认 5

**输出结构**：
- results：法条数组，每个元素包含 law_name、article_number、article_title、article_text、score
- count：返回条数

### 4.4 search_document 工具详解

**作用**：在合同文档中搜索与查询语义相关的条款。

**检索策略：同样采用双层架构**

**向量语义检索**：
- 在 Qdrant 的 contract_clauses collection 中搜索
- 按 contract_id 过滤，确保只搜索当前合同
- 支持跨合同搜索（当不传 contract_id 时）

**本地关键词匹配**：
- 遍历 SessionGraph 中的 Clause 节点
- 检查文本是否包含所有查询关键词
- 匹配成功的条款加入结果列表

**使用场景**：
- Agent 想知道合同中是否还有其他相关条款
- CrossReferenceAgent 查找可能有冲突的条款
- DebateAgent 查找支持正反观点的条款

### 4.5 output_finding 工具详解

**作用**：把发现的风险写入 SessionGraph。

**工作流程**：

1. **接收风险信息**：
   - clause_id：关联的条款 ID（可选）
   - risk_type：风险类型
   - level：风险等级
   - confidence：置信度
   - reason：原因说明
   - suggestion：修改建议
   - law_refs：法条引用

2. **创建 Risk 节点**：
   - 调用 SessionGraph.add_node 创建节点
   - 节点类型为 "Risk"
   - properties 包含上述所有字段

3. **建立关联边**：
   - 如果 clause_id 存在且对应节点存在
   - 创建 Clause 到 Risk 的 HAS_RISK 边

**返回结果**：
- status：success 或 error
- risk_id：新创建的 Risk 节点 ID

### 4.6 check_cross_reference 工具详解

**作用**：检查两个条款是否一致或存在冲突。

**检查逻辑**：

1. **读取条款内容**：
   - 调用 read_section 工具读取两个条款的文本

2. **应用规则检查**：

   **规则一：试用期与合同期限匹配**
   - 从条款 A 提取试用期月数（如"试用期六个月"）
   - 从条款 B 提取合同期限年数（如"合同期限两年"）
   - 判断试用期是否超过法定上限（1 年期 1 个月，2 年期 2 个月，3 年及以上 6 个月）

   **规则二：社保放弃与工资条款**
   - 如果条款 A 包含"放弃社保"、"不缴纳社保"等表述
   - 且条款 B 涉及工资内容
   - 判定为冲突（放弃社保约定违法）

3. **返回结果**：
   - consistent：是否一致（true/false）
   - issues：冲突描述列表

### 4.7 extract_obligations 工具详解

**作用**：从条款文本中提取甲乙双方的权利义务。

**提取逻辑**：

1. **句子分割**：按句号和分号切分文本

2. **判断主语**：
   - 如果句子开头或前 10 个字包含"甲方"，主语为甲方
   - 如果包含"乙方"，主语为乙方

3. **判断类型**：
   - 包含"不得"、"禁止"的为"禁止性义务"
   - 包含"享有"、"有权"的为"权利"
   - 其他包含"应当"、"必须"的为"义务"

4. **过滤**：只保留包含"应当"、"必须"、"不得"、"有权"等关键词的句子

### 4.8 validate_calculation 工具详解

**作用**：验证合同中的数字计算是否合理。

**检查内容**：

1. **违约金金额检查**：
   - 提取条款中的金额数字
   - 如果提供了月工资，计算违约金是否超过月工资的 12 倍
   - 超过则标记为可能过高

2. **试用期与合同期限匹配**：
   - 从条款中提取试用期月数和合同期限年数
   - 判断试用期是否超过法定上限

### 4.9 compare_with_template 工具详解

**作用**：将合同条款与标准模板进行对比，标出差异。

**对比方式**：

- 使用 Python 的 difflib 库做文本差异对比
- 逐行比较，标记增加和删除的内容
- 返回差异列表，每项包含 type（增加/删除）和 content

---

## 五、Agent 通信机制

### 5.1 两种通信方式详解

**方式一：共享记忆图（SessionGraph）**

这是 Agent 协作的主要方式。SessionGraph 是一个内存图结构，存储一次审查会话中的所有实体和关系。

**SessionGraph 包含的节点类型**：

- Session：审查会话根节点
- Clause：合同条款节点
- Risk：风险发现节点
- Law：法律条文节点
- Party：合同主体节点
- Suggestion：修改建议节点
- Evidence：证据节点

**SessionGraph 包含的边类型**：

- HAS_RISK：从 Clause 到 Risk，表示条款存在风险
- BASED_ON：从 Risk 到 Law，表示风险基于某法条
- RELATES_TO：从 Clause 到 Clause，表示条款之间有关联
- CONTRADICTS：从 Clause 到 Clause，表示条款之间相互矛盾

**Agent 如何使用 SessionGraph**：

- 写入：Agent 发现风险后，调用 add_node 创建 Risk 节点，调用 add_edge 建立关联
- 读取：Agent 调用 find_nodes 查询特定类型的节点，调用 get_neighbors 获取邻居节点
- 更新：Agent 调用 update_node 修改节点属性

**方式二：消息总线（AgentBus）**

AgentBus 提供基于 Redis Pub/Sub 的事件广播能力，用于实时通知。

**核心事件类型**：

- agent_started：Agent 开始工作
- agent_completed：Agent 完成工作
- finding_added：发现新风险
- risk_escalated：风险等级上调
- evidence_found：找到关键证据
- contradiction_detected：发现条款冲突
- phase_changed：阶段切换
- completed：审查完成
- error：发生错误

**AgentBus 的工作原理**：

1. **发布事件**：
   - Agent 或 Coordinator 调用 publish 方法
   - 事件被写入 Redis 频道（格式：review:{session_id}:events）
   - 同时写入本地内存队列

2. **订阅事件**：
   - 调用 subscribe 方法创建异步队列
   - 后台任务从 Redis 读取消息，推送到队列
   - 订阅者通过 async for 循环读取队列

### 5.2 不是 Pipeline 模式

**Pipeline 模式的特点**：
- Agent A 的输出直接作为 Agent B 的输入
- 严格串行，必须等上一个完成
- 数据流是单向的

**本项目的模式**：
- 多个 Agent 并行执行，各自往 SessionGraph 写结果
- 后续 Agent 从 SessionGraph 读取需要的信息
- Agent 之间没有直接调用关系
- 数据流是多对多的

---

## 六、ReAct 推理循环

### 6.1 什么是 ReAct

ReAct 是 Reasoning（推理）和 Acting（行动）的组合，是一种让 LLM 像人一样思考和行动的框架。

**核心思想**：
- LLM 不是直接给出最终答案
- 而是：先观察、再思考、决定采取什么行动、执行行动、观察结果、再思考...循环往复
- 直到收集足够信息，才输出最终结论

**标准 ReAct 循环**：

1. Observation（观察）：了解当前情况
2. Thought（思考）：分析应该做什么
3. Action（行动）：决定采取什么行动
4. Execution（执行）：调用工具或查询信息
5. Observation（观察）：看执行结果
6. 继续下一轮思考...

### 6.2 本项目的 ReAct 实现

**当前版本：多轮 ReAct**

本项目的 `BaseAgent._react_loop` 已经实现多轮 ReAct 循环，同时保持对旧 Agent 的兼容：

1. **构造消息**：system_prompt 定义角色，task_prompt 传入具体任务
2. **动态追加 ReAct 格式说明**：`_react_loop` 会自动在 system_prompt 后追加可用工具列表和输出格式要求
3. **多轮循环**：
   - 调用 LLM，解析输出中的 `thought`、`action`、`action_input`、`final_answer`
   - 如果 `action` 是 `final_answer` 或直接返回 `final_answer`，结束循环
   - 如果 `action` 是已注册工具名，调用该工具，把结果作为 Observation 加入上下文
   - 继续下一轮，直到得出结论或达到 `max_turns`
4. **兼容旧 Agent**：如果 LLM 没有按 ReAct 格式输出，直接把解析结果作为结论返回

**输出格式要求**：

LLM 需要按以下 JSON 格式输出：

```json
{
  "thought": "当前思考内容",
  "action": "工具名称 或 final_answer",
  "action_input": {"参数名": "参数值"},
  "final_answer": {"risk_type": "...", "level": "...", ...}
}
```

### 6.3 为什么保留单轮兼容

虽然底层已支持多轮，但现有大部分 Agent 的 Prompt 仍然让 LLM 直接输出结论（即第一轮就返回 `final_answer`）：

- **成本考虑**：多轮调用 token 消耗更高，单轮足以处理大部分结构化审查任务
- **稳定性**：合同审查需要确定性输出，单轮 Prompt 约束更强
- **可控性**：复杂工具调用顺序可以在 Agent 的 `run` 方法中显式控制

**实际运行中**：
- RiskReviewAgent、MissingClauseAgent 等通常第一轮就给出结论
- 如果需要多轮，可以在 Prompt 中引导 LLM 使用 `action` 调用工具
- `max_turns` 默认是 5，防止无限循环

### 6.4 多轮 ReAct 的使用场景

多轮 ReAct 更适合以下场景：

- **DebateAgent**：正方说完反方说，需要多轮攻防
- **LegalVerifyAgent**：发现法条引用后，主动去知识库验证
- **CrossReferenceAgent**：先查一个条款，再查另一个条款，然后判断冲突
- **复杂合同审查**：合同条款多、关系复杂，需要逐步收集信息

### 6.5 如何观察 ReAct 执行过程

每次 `_react_loop` 执行都会把每轮的 thought、action、action_input、observation 记录到 `self.logs` 中：

```json
{
  "turn": 1,
  "thought": "需要查询相关法律依据",
  "action": "search_knowledge",
  "action_input": {"query": "试用期"},
  "observation": {"result": {...}}
}
```

这些日志可以通过 AgentBus 的 `agent_completed` 事件输出，也可以存入数据库用于后续分析。

---

## 七、RAG 实现细节

RAG（Retrieval-Augmented Generation，检索增强生成）是本项目 Agent 获取外部知识的核心方式。它的本质是让大模型在生成结论之前，先从知识库中检索相关资料，把检索结果作为上下文，再让大模型基于这些资料作答。

### 7.1 RAG 的两层检索架构

本项目的 RAG 采用双层检索架构，优先做语义检索，失败时降级为关键词检索。

#### 第一层：向量语义检索

**向量化模型 BGE-M3**：
- BGE-M3 是北京智源人工智能研究院开源的多语言文本向量模型
- 可以把一段中文文本压缩成一个 1024 维的向量
- 语义相近的文本，向量距离也更近
- 支持延迟加载，第一次调用时才从 Hugging Face 或镜像站点下载模型

**向量数据库 Qdrant**：
- Qdrant 是专门存储和搜索向量的数据库
- 支持高维向量的相似度搜索
- 本项目使用两个 Collection（数据集合）：
  - knowledge_articles：存储法律条文的向量
  - contract_clauses：存储合同条款的向量

**语义检索的流程**：
1. Agent 传入查询文本，例如"试用期最长可以约定多久"
2. 系统用 BGE-M3 把查询文本转成向量
3. 在 Qdrant 的 knowledge_articles 中搜索与该向量最接近的 top-k 个法条向量
4. 返回这些法条的具体内容，以及它们和查询的相似度分数

**语义检索的优势**：
- 能找到关键词不同但语义相关的法条
- 例如查询"试用期"，能命中"同一用人单位与同一劳动者只能约定一次试用期"
- 支持自然语言提问，Agent 不需要精确匹配法条编号

#### 第二层：关键词检索（降级）

**为什么需要降级**：
- 开发环境可能没有启动 Qdrant
- BGE-M3 模型首次下载可能超时或失败
- 向量检索偶尔会出现异常

**降级机制**：
- 当 Qdrant 不可用时，自动切换到 SQL 关键词检索
- 在 PostgreSQL 或 SQLite 的 knowledge_articles 表中用 LIKE 语句做模糊匹配
- 搜索范围包括：law_name、article_number、article_title、article_text
- 多个关键词用 OR 连接，保证召回率

**降级后的效果**：
- 语义能力变弱，但仍然能找到包含关键词的法条
- 保证系统在没有 Qdrant 时也能正常运行
- 对主审查流程没有影响

### 7.2 两类 RAG 检索

本项目的 RAG 分为两类：法律知识库检索和合同文档检索。

#### 法律知识库检索

**使用工具**：search_knowledge

**作用**：为 Agent 提供法律条文作为审查依据。

**知识库来源**：
- 劳动合同法、劳动法、社会保险法等基础法规
- 民法典合同编相关条文
- 最高人民法院相关司法解释
- 行业特殊规定

**数据入库流程**：
1. 使用 scripts/seed_knowledge.py 把法条写入 PostgreSQL/SQLite
2. 同时调用 BGE-M3 把法条向量化
3. 把向量写入 Qdrant 的 knowledge_articles collection

**调用时机**：
- RiskReviewAgent 审查条款时，需要查相关法律
- LegalBasisAgent 为风险补充法条引用
- SuggestionAgent 生成修改建议时参考法条
- DebateAgent 辩论时需要法条支持

#### 合同文档检索

**使用工具**：search_document

**作用**：在合同内部搜索与查询语义相关的条款。

**数据入库流程**：
1. 在 Preload 阶段，Coordinator 调用 VectorStore.upsert_clauses
2. 把每个 Clause 节点的文本用 BGE-M3 编码成向量
3. 把向量写入 Qdrant 的 contract_clauses collection
4. 每个向量都带有 contract_id 标记，方便按合同过滤

**调用时机**：
- RiskReviewAgent 想确认合同中是否有其他相关条款
- CrossReferenceAgent 查找可能冲突的条款
- DebateAgent 查找支持正方或反方观点的合同内容

### 7.3 RAG 在 Agent 中的具体使用流程

以 RiskReviewAgent 审查"试用期六个月"条款为例：

1. **Agent 收到条款**：
   - 当前条款原文是"试用期为六个月，自入职之日起计算"

2. **Agent 决定查询法条**：
   - Agent 识别到关键词"试用期"
   - 认为需要查询相关法律规定

3. **调用 search_knowledge 工具**：
   - 查询关键词为"试用期"
   - 工具内部先做向量语义检索
   - 返回《劳动合同法》第十九条等法条

4. **LLM 基于检索结果推理**：
   - 把条款原文和法条原文一起放入 Prompt
   - 让 LLM 判断是否违法
   - LLM 输出风险类型、等级、原因、建议

5. **写入 SessionGraph**：
   - 创建 Risk 节点
   - 把法条引用写入 law_refs

### 7.4 RAG 的优势与不足

**优势**：
- 减少 LLM 幻觉：有法条原文作为依据，不容易编造法律
- 提高专业性：检索到真实法条，结论更可信
- 支持时效性更新：知识库更新后，Agent 的回答自动更新
- 降低成本：不需要把大量法条都塞进 Prompt，只检索相关的

**不足**：
- 依赖知识库质量：法条不全或错误会影响结果
- 语义检索有阈值：太生僻的问题可能检索不到
- 需要维护向量库：新增法条需要重新向量化
- 首次启动需要下载模型：BGE-M3 体积较大

---

## 八、记忆层构建与使用

### 8.1 记忆层的两层设计

本项目的记忆层分为两层：

| 层级 | 名称 | 存储内容 | 作用 |
|------|------|----------|------|
| 第一层 | SessionGraph | 单次审查的完整图结构 | Agent 之间的共享记忆 |
| 第二层 | AgentBus | 实时事件消息 | 进度同步和事件通知 |

### 8.2 SessionGraph 的构建过程

SessionGraph 不是一开始就完整的，而是在审查过程中逐步构建的。

#### 第一阶段：创建根节点

审查开始时，Coordinator 创建一个 Session 节点作为根节点。
- 节点属性包括 session_id、contract_id、contract_type、status
- 代表这次审查会话本身

#### 第二阶段：写入 Clause 节点

在 Preload 阶段，把合同解析后的每个 chunk 写入 SessionGraph：
- 每个 chunk 对应一个 Clause 节点
- 属性包括 chunk_id、text、section_path、page、bbox、risk_level
- 这些节点是后续所有审查的基础

#### 第三阶段：写入 Law 节点

同样在 Preload 阶段，把常用法条写入 SessionGraph：
- 每个法条对应一个 Law 节点
- 属性包括 law_name、article_number、article_title、article_text
- 预加载的法条供所有 Agent 直接引用，减少数据库查询

#### 第四阶段：写入 Party 节点

TermExtractionAgent 从合同中提取甲方、乙方、合同期限、岗位等信息：
- 创建 Party 节点代表合同主体
- 属性包括 party_type、name、role、contract_term、position

#### 第五阶段：写入 Risk 节点

Execute 阶段各 Agent 发现风险后：
- 创建 Risk 节点
- 属性包括 risk_type、level、confidence、reason、suggestion、law_refs、clause_text
- 同时建立 Clause 到 Risk 的 HAS_RISK 边

#### 第六阶段：补充和关联

Merge+Link、LegalVerify、Debate 阶段会进一步丰富图：
- 建立 Clause 之间的 RELATES_TO 或 CONTRADICTS 边
- 为 Risk 节点添加 Law 节点的 BASED_ON 边
- 更新 Risk 的 verified、needs_human_review 等属性

### 8.3 SessionGraph 的使用方式

#### 写入使用

每个 Agent 在执行过程中会写入不同类型的节点和边：
- RiskReviewAgent 写入 Risk 节点
- TermExtractionAgent 写入 Party 节点
- CrossReferenceAgent 写入 RELATES_TO / CONTRADICTS 边
- LegalBasisAgent 更新 Risk 的 law_refs
- SuggestionAgent 更新 Risk 的 suggestion

#### 读取使用

后续 Agent 通过读取 SessionGraph 获取已有信息：
- LegalBasisAgent 读取 Risk 节点，为其补充法条
- SuggestionAgent 读取 Risk 节点，为其生成建议
- DebateAgent 读取 Risk 节点，挑选高风险项辩论
- HumanReviewAgent 读取 Risk 节点，判断是否需要人工复核

#### 查询方式

SessionGraph 支持多种查询：
- 按节点类型查询：查询所有 Risk、所有 Clause
- 按属性过滤：查询 level 为 high 的风险
- 按关系查询：查询某个 Clause 关联的所有 Risk
- 邻居查询：查询某个 Risk 对应的 Clause
- 子图导出：导出某个节点周围的局部图给 LLM 作为上下文

### 8.4 AgentBus 的构建与使用

#### AgentBus 的构建

AgentBus 初始化时需要传入 session_id 和 Redis URL：
- session_id 决定 Redis 频道名称，格式为 review:{session_id}:events
- Redis URL 来自配置文件中的 REDIS_URL

AgentBus 基于 Redis Pub/Sub 实现，用于跨进程、跨 Worker 的广播。生产环境必须直接使用 Redis，不再降级为内存队列；审查结束或应用关闭时必须调用 `agent_bus.aclose()` 释放连接。

#### AgentBus 的使用

**发布事件**：
- Agent 或 Coordinator 调用 publish 方法发布事件
- 事件发送到 Redis 频道 `review:{session_id}:events`

**订阅事件**：
- 调用 subscribe 方法创建一个异步队列
- 后台任务从 Redis 读取消息并推入队列
- 订阅者通过 async for 循环消费事件

**典型事件类型**：
- agent_started / agent_completed：Agent 开始/完成工作
- finding_added：发现新风险
- phase_changed：阶段切换
- completed：审查完成

### 8.5 记忆层的价值

**对 Agent 的价值**：
- 让 Agent 能够"看到"其他 Agent 的工作成果
- 不需要 Agent 之间直接通信，降低耦合
- 支持 Agent 在后续阶段修正或补充前面阶段的结论

**对系统的价值**：
- 审查过程完全可追溯
- 每个 Risk 都能找到原始 Clause 和法律依据
- 方便生成报告和原文高亮
- 支持审查中断后恢复

**对用户的价值**：
- 报告可信度高，每条结论都有出处
- 支持点击查看法律依据和原文位置
- 人工复核时可以看到完整推理链

### 8.6 记忆层与 RAG 的关系

| 组件 | 作用 | 关系 |
|------|------|------|
| RAG | 从外部知识库检索资料 | 为 Agent 提供法律条文和合同内相关条款 |
| SessionGraph | 存储审查过程中的所有中间结果 | 记录 Agent 的输入、输出和关联关系 |
| AgentBus | 实时广播事件 | 让 Coordinator、Agent、前端保持同步 |

**工作流程关系**：
1. Agent 通过 RAG 从知识库获取外部资料
2. Agent 基于资料推理，把结论写入 SessionGraph
3. AgentBus 广播进度事件，通知各方
4. 后续 Agent 从 SessionGraph 读取已有结论，继续工作

### 8.7 面试话术

**关于 RAG**：
> "我们项目的 RAG 采用双层架构。优先用 BGE-M3 模型把查询文本编码成 1024 维向量，在 Qdrant 中做语义检索，找到语义相关但关键词不同的法条。如果 Qdrant 不可用，就降级为 SQL 关键词 LIKE 检索。RAG 主要用在 search_knowledge 和 search_document 两个工具中，前者查法条，后者查合同内条款。"

**关于记忆层**：
> "我们的记忆层分为 SessionGraph 和 AgentBus 两层。SessionGraph 是单次审查的共享记忆图，Preload 阶段写入 Clause、Law、Party 节点，Execute 阶段写入 Risk 节点和 HAS_RISK 边，后续阶段再补充 RELATES_TO、BASED_ON 等边。AgentBus 负责实时事件广播，比如阶段切换、发现风险、审查完成。Agent 之间主要通过 SessionGraph 共享状态，而不是直接传递输出。"

**关于 RAG 和记忆层的配合**：
> "RAG 为 Agent 提供外部知识，SessionGraph 记录 Agent 的推理结果。Agent 先用 RAG 查法条，再结合 SessionGraph 中的 Clause 节点做判断，最后把结论写回 SessionGraph。这样既保证结论有法可依，又保证审查过程可追溯、可复用。"

---

## 九、共享记忆图 SessionGraph

### 9.1 SessionGraph 的作用

SessionGraph 是整个 Agent 系统的核心数据结构，作用包括：

**1. 共享状态**：
- 所有 Agent 看到同一份数据
- 避免 Agent 之间直接传递数据

**2. 解耦 Agent**：
- Agent 不需要知道其他 Agent 的存在
- 只需要读写 SessionGraph

**3. 可追溯性**：
- 每个 Risk 可以追溯到原始 Clause
- 每个 Clause 可以追溯到页码和坐标
- 方便报告生成和原文高亮

**4. 支持组合推理**：
- 通过图结构发现跨条款风险
- 建立 Clause 之间的关系边

**5. 持久化中间结果**：
- 可以在阶段结束时 snapshot 到 Redis
- 可以序列化后存入数据库

### 9.2 SessionGraph 的使用时机

**贯穿整个审查流程**：

- **Preload 阶段**：创建 Clause 节点、Law 节点、Party 节点
- **Execute 阶段**：Agent 创建 Risk 节点，建立 HAS_RISK 边
- **Merge+Link 阶段**：建立 RELATES_TO 和 CONTRADICTS 边
- **LegalVerify 阶段**：为 Risk 节点添加 Law 节点和 BASED_ON 边
- **Triage 阶段**：从 SessionGraph 汇总所有 Risk 输出结果

### 9.3 SessionGraph 的核心方法

**节点操作**：
- add_node：添加节点，返回节点 ID
- get_node：根据 ID 获取节点
- update_node：更新节点属性
- remove_node：删除节点
- find_nodes：按类型和属性过滤查询节点

**边操作**：
- add_edge：添加边
- find_edges：查询满足条件的边
- get_neighbors：获取邻居节点

**风险处理**：
- merge_duplicate_risks：合并重复风险
- find_cross_clause_risks：发现跨条款组合风险

**序列化**：
- to_dict：把图序列化为字典
- from_dict：从字典反序列化
- export_for_llm：导出某个节点周围的子图给 LLM 作为上下文

---

## 十、Prompt 设计与编写

### 10.1 Prompt 写在哪里

**system_prompt 的位置**：

每个 Agent 的 system_prompt 写在各自的 Agent 类构造函数中。这样做的原因：
- 每个 Agent 有不同的角色定义
- 输出格式要求不同
- 方便独立维护和调试

**task_prompt 的位置**：

task_prompt 在 Agent 的 run 方法中动态构造。这样做的原因：
- 任务内容每次不同，需要动态生成
- 可以根据 SessionGraph 中的数据构造上下文
- 可以传入当前审查的条款原文

### 10.2 哪些地方需要 Prompt

| 位置 | 作用 | 内容 |
|------|------|------|
| Agent system_prompt | 定义 Agent 角色、能力、输出格式 | 角色描述、输出字段说明、示例 |
| Agent task_prompt | 传入当前具体任务 | 条款原文、审查要求 |
| 工具函数内部 | 部分工具会构造给 LLM 的查询 | 查询关键词、上下文 |
| Coordinator 阶段提示 | 阶段切换时给前端的提示文字 | 阶段名称、进度说明 |
| ChatAgent | 对话系统的提示词 | 对话角色、知识范围、回答风格 |

### 10.3 Prompt 编写要点

**1. 角色定义清晰**

明确告诉 LLM 它扮演什么角色、擅长什么领域。例如：
- "你是一名合同风险审查专家"
- "你擅长识别劳动合同中的不公平、违法或高风险条款"

**2. 输出格式明确**

详细列出期望的输出字段及其含义。例如：
- risk_type：风险类型
- level：风险等级（只能是 high、medium、low）
- confidence：置信度（0-1 之间）
- reason：风险原因说明
- suggestion：修改建议

**3. 给出示例**

提供 1-2 个输入输出示例，让 LLM 模仿。例如：
- 输入："试用期六个月，合同期限两年"
- 输出：{"risk_type": "试用期超长", "level": "high", ...}

**4. 约束边界条件**

告诉 LLM 特殊情况如何处理。例如：
- "如果没有发现风险，level 填 low，risk_type 填 无明显风险"
- "风险等级只能是 high、medium、low 三种，不要使用其他值"

**5. 使用中文**

因为是中文合同审查，Prompt 用中文效果更好，LLM 理解更准确。

### 10.4 Prompt 调试技巧

**从简单开始**：先写基本角色和格式，再逐步增加约束

**添加 few-shot 示例**：给 1-2 个输入输出示例，让 LLM 模仿

**temperature 调低**：审查任务需要确定性，用 0.1-0.3

**Pydantic 校验输出**：用 schema 校验 LLM 输出，失败时重试

**记录 bad case**：把 LLM 输出错误的例子整理成测试集，迭代优化 Prompt

**A/B 测试**：同时跑两个版本的 Prompt，比较准确率

---

## 十一、八阶段管线详解

Coordinator 的八阶段管线是整个审查流程的骨架。

### 11.1 阶段总览

八个阶段的顺序和作用：

```text
Route → Preload → LegalResearch → Execute → Merge+Link → LegalVerify → Debate → Triage
```

| 阶段 | 主要职责 | 是否并行 | 涉及 Agent |
|------|----------|----------|-----------|
| Route | 根据条款特征分配 Agent | 否 | 无 |
| Preload | 写入 SessionGraph、提取主体信息、条款向量化 | 否 | TermExtractionAgent |
| LegalResearch | 动态推断适用法律并检索法条 | 否 | LegalResearchAgent |
| Execute | 并行执行多个 Agent 审查 | **是** | RiskReview / MissingClause / Balance / CrossReference / IndustryCompliance |
| Merge+Link | 合并重复风险、发现组合风险 | 否 | 无 |
| LegalVerify | 补充和验证法律依据 | 否 | LegalBasisAgent、LegalVerifyAgent |
| Debate | 高风险项正反辩论 | 否 | DebateAgent |
| Triage | 分类输出结果 | 否 | HumanReviewAgent |

### 11.1.1 阶段总览的通俗解释

可以把八阶段管线理解为一条合同审查流水线：

1. **Route（分诊）**：先看每个条款大概属于哪个科室、紧急程度如何；
2. **Preload（建档）**：把合同条款、甲乙双方信息写入档案系统（SessionGraph）；
3. **LegalResearch（查法规）**：根据合同类型去查可能适用的法律条文；
4. **Execute（会诊）**：多个专科 Agent 同时审查；
5. **Merge+Link（合并关联）**：把重复报告合并，发现条款组合风险；
6. **LegalVerify（核法条）**：给每个风险配上准确的法律依据；
7. **Debate（辩论）**：对高风险项正反论证；
8. **Triage（分流）**：输出最终报告，把拿不准的转人工复核。

### 11.2 阶段一：Route（路由分配）

**职责**：扫描每个合同条款，判断应该派给哪些 Agent 审查。

**工作内容**：

1. **遍历所有条款**：对每个 chunk（合同切分后的条款）

2. **关键词匹配**：
   - 如果条款包含"试用期"，分配给 RiskReviewAgent
   - 如果条款包含"违约金"，分配给 RiskReviewAgent 和 BalanceAgent
   - 如果条款包含"社保"或"社会保险"，分配给 RiskReviewAgent，初始风险等级设为 high

3. **生成分配表**：输出 (chunk, agent_names, risk_level) 三元组列表

**为什么用关键词而不是向量检索**：
- 路由阶段需要快速判断，关键词匹配足够
- 向量检索开销大，适合后续的 search_knowledge

### 11.3 阶段二：Preload（预加载）

**职责**：准备审查所需的共享上下文，不再预加载固定法条（法律依据改由 LegalResearchAgent 动态推断和检索）。

**工作内容**：

1. **创建 Clause 节点**：
   - 把每个 chunk 写成 SessionGraph 中的 Clause 节点
   - 属性包括：chunk_id、text、section_path、page、bbox

2. **合同条款向量化**：
   - 调用 VectorStore.upsert_clauses
   - 用 BGE-M3 把条款编码成向量
   - 写入 Qdrant 的 contract_clauses collection

3. **提取合同主体信息**：
   - 调用 TermExtractionAgent
   - 提取甲方名称、乙方名称、合同期限、工作岗位
   - 写入 Party 节点

### 11.4 阶段三：LegalResearch（动态法律研究）

**职责**：根据合同内容动态推断适用法律领域，检索法条并生成审查要点。

**工作内容**：

1. **拼接合同文本**：控制长度，避免 token 超限。

2. **一次 LLM 推断**：
   - 推断可能适用的法律领域（如劳动合同法、民法典合同编、民间借贷司法解释等）；
   - 输出各领域风险信号强度（strong / medium / weak）。

3. **分层检索法条**：
   - 本地知识库（Qdrant / SQL）优先；
   - 若推断出具体法律 + 条款号，尝试精准检索；
   - 必要时通过 Tavily 联网搜索兜底（每个合同最多 3 次泛化 web search）。

4. **生成审查要点**：
   - 高频法条使用 `REVIEW_POINT_TEMPLATES` 预制模板，跳过 LLM；
   - 其他法条调用轻量 LLM 生成审查要点；
   - 类级缓存避免重复调用。

5. **写入 Law 节点**：把检索到的法条写入 SessionGraph，供后续 Agent 引用。

**快速路径优化**：
- 当本地 + 精准检索无结果且整体风险信号弱时，跳过泛化 web search，避免在明显合法的合同上空转。

### 11.5 阶段四：Execute（并行执行）

**职责**：并行启动多个 Agent，让它们各自审查分配到的条款。

**工作内容**：

1. **构造任务列表**：
   - 遍历 Route 阶段生成的分配表
   - 为每个 (chunk, agent_names, risk_level) 三元组构造任务
   - 每个 Agent.run 是异步方法，可以并行

2. **并行执行**：
   - 用 asyncio.gather 同时启动所有任务
   - 各 Agent 独立运行，不需要等待其他 Agent

3. **收集结果**：
   - 各 Agent 把发现的风险写入 SessionGraph
   - Coordinator 收集各 Agent 的日志

**并行执行的 Agent**：
- RiskReviewAgent：识别高风险条款
- MissingClauseAgent：检查缺失的必要条款
- BalanceAgent：分析权利义务对等性
- CrossReferenceAgent：检查条款间冲突
- IndustryComplianceAgent：行业特殊合规（如果合同类型匹配）

**为什么可以并行**：
- 各 Agent 之间没有依赖关系
- 它们都是从 SessionGraph 读取输入，各自写入输出
- asyncio.gather 自动调度协程

### 11.6 阶段五：Merge+Link（合并关联）

**职责**：整合各 Agent 的审查结果，发现组合风险。

**工作内容**：

1. **合并重复风险**：
   - 不同 Agent 可能发现相似风险
   - 按 risk_type 分组
   - 用 2-gram Jaccard 相似度比较 clause_text
   - 检查 clause_ids 是否有交集
   - 合并时保留最高 level 和最高 confidence
   - 合并 law_refs 和 suggestion

2. **发现跨条款组合风险**：
   - 从 cross_clause_rules.json 读取规则
   - 检查是否存在满足条件的条款组合
   - 例如：试用期 6 个月 + 合同期限 2 年 → 试用期超长

3. **建立条款间关系**：
   - 对于有关联的条款，建立 RELATES_TO 边
   - 对于有冲突的条款，建立 CONTRADICTS 边

4. **再次合并**：
   - 跨条款风险可能与单条款风险重复
   - 再次调用合并逻辑去重

### 11.7 阶段六：LegalVerify（法条验证）

**职责**：为风险补充法律依据，并验证准确性。

**工作内容**：

1. **LegalBasisAgent 执行**：
   - 查询所有 Risk 节点
   - 跳过已有 law_refs 的 Risk
   - 根据 risk_type 和 reason 构建查询关键词
   - 调用 search_knowledge 工具查询法条
   - 更新 Risk 节点的 law_refs 字段

2. **LegalVerifyAgent 执行**：
   - 遍历所有 Risk 节点
   - 检查每个 law_refs 是否在知识库中存在
   - 验证法条内容是否准确
   - 更新 Risk 节点的 verified 字段和 confidence

### 11.8 阶段七：Debate（辩论）

**职责**：对高风险或低置信度项进行正反辩论，减少误报。

**工作内容**：

1. **筛选需要辩论的风险**：
   - level 为 high 的风险
   - confidence 低于 0.7 的风险

2. **正方论证**：
   - 论证"这确实是一个风险"
   - 引用相关法条和合同原文
   - 说明为什么应该修改

3. **反方论证**：
   - 论证"这可能不是风险"或"存在例外情况"
   - 引用可能减轻或豁免的条款
   - 说明某些行业或场景下的特殊性

4. **Coordinator 裁决**：
   - 综合正反双方观点
   - 做出最终判断：
     - keep：保留风险
     - adjust：调整风险等级
     - remove：撤销风险

**为什么需要辩论**：
- LLM 可能过度敏感，把一些正常条款误判为风险
- 正反观点平衡可以减少误报
- 高风险项更需要谨慎确认

### 11.9 阶段八：Triage（分流输出）

**职责**：汇总所有风险，分类输出最终结果。

**工作内容**：

1. **查询所有 Risk 节点**：从 SessionGraph 获取所有 Risk

2. **构造 findings 数组**：
   - 遍历每个 Risk 节点
   - 提取 risk_type、level、confidence、reason、suggestion、law_refs、clause_text
   - 加入 findings 数组

3. **构造 human_review_items 数组**：
   - 对于 confidence 低于 0.6 的风险
   - 对于标记了 needs_human_review 的风险
   - 构造人工复核项，包含 risk_id 和 reason

4. **计算风险统计**：
   - 统计 high、medium、low 各有多少个
   - 计算总数

5. **返回结果**：
   - session_id：审查会话 ID
   - findings：风险列表
   - human_review_items：人工复核列表
   - stats：风险统计
   - graph_data：SessionGraph 序列化（可选）

---

## 十二、面试常见问题与回答

### Q1：你们项目用了什么多 Agent 架构？

> 我们采用编排式 Multi-Agent。由 ReviewCoordinator 统一调度多个专业 Agent，Agent 之间通过 SessionGraph 共享状态和 AgentBus 广播事件协作，而不是 Main Agent 加 Sub-Agent 的树状模式。

### Q2：Agent 之间怎么通信？

> 主要通过两种方式：一是共享记忆图 SessionGraph，Agent 把结果写上去，其他 Agent 读取；二是消息总线 AgentBus，基于 Redis Pub/Sub 实时广播事件。不是简单的上一个 Agent 输出传给下一个 Agent 的 Pipeline 模式。

### Q3：每个 Agent 内部是怎么推理的？

> 目前采用简化版 ReAct。通过 system_prompt 定义角色和输出格式，task_prompt 传入当前任务，调用 LLM 得到结构化 JSON。未来可以扩展为带工具调用的多轮 ReAct，让 Agent 自主决定什么时候查法条、什么时候读条款。

### Q4：用了哪些工具？怎么注册给 Agent？

> 我们有 10 个工具函数，包括 search_knowledge（法条检索）、search_document（合同检索）、read_section（读取章节）、output_finding（写入风险）、check_cross_reference（检查条款一致性）等。工具在 Coordinator 中统一注册，然后按需传给每个 Agent。

### Q5：共享记忆图 SessionGraph 有什么用？

> SessionGraph 让所有 Agent 看到同一份数据，解耦 Agent 之间的依赖。比如 RiskReviewAgent 写完 Risk，LegalBasisAgent 可以直接读到并补充法条，SuggestionAgent 再读到并生成建议。它还支持建立条款之间的关系边，发现跨条款组合风险。

### Q6：Prompt 怎么设计？

> Prompt 写在每个 Agent 的 system_prompt 里，task_prompt 在 run 方法中动态构造。设计要点：角色清晰、输出格式明确、给出示例、约束边界条件。输出用 JSON，方便后续解析和 Pydantic 校验。

### Q7：向量检索在 Agent 中怎么用？

> Agent 通过 search_knowledge 工具查询法条。优先用 BGE-M3 模型加 Qdrant 做语义检索，能命中语义相关但关键词不同的法条；Qdrant 不可用时降级为 SQL 关键词 LIKE 检索。search_document similarly 用于合同内条款检索。

### Q8：审查流程分几个阶段？

> 八个阶段：Route 做路由分配，Preload 预加载，LegalResearch 动态法律研究，Execute 并行执行 Agent，Merge+Link 合并风险，LegalVerify 补充和验证法条，Debate 对高风险项辩论，Triage 输出结果。阶段之间有序，但 Execute 阶段内多个 Agent 可以用 asyncio.gather 并行运行。

### Q9：如果让你优化 Agent，你会怎么做？

> 可以从几个方向优化：
> 1. 把单轮 ReAct 扩展为多轮 ReAct，让 Agent 自主调用工具
> 2. 引入更细粒度的 Agent，比如专门审试用期、专门审违约金
> 3. 增加 Agent 输出校验和重试机制
> 4. 用 evaluation 框架定期评估各 Agent 准确率
> 5. 引入 reflection 机制，让 Agent 能自我修正

---

## 十一、总结

Agent 模块是合同卫士项目的核心智能层：

- **架构**：编排式 Multi-Agent，Coordinator 统一调度
- **数量**：15 个专业 Agent（含 BaseAgent），覆盖提取、审查、验证、建议、复核全流程
- **通信**：SessionGraph 共享状态 + AgentBus 实时事件
- **推理**：简化版 ReAct，通过 Prompt 约束 LLM 输出结构化 JSON
- **工具**：10 个工具函数，支持法条检索、合同检索、风险写入等
- **Prompt**：写在 Agent 类中，强调角色、格式、示例、边界
- **记忆**：SessionGraph 贯穿整个审查流程，是 Agent 协作的基础
- **阶段**：八阶段管线（Route → Preload → LegalResearch → Execute → Merge+Link → LegalVerify → Debate → Triage），阶段间有序，Execute 阶段内并行

掌握以上内容，可以应对绝大多数关于本项目 Agent 模块的面试问题。