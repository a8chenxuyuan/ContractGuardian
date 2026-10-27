# 多轮 ReAct 落地方案

> 制定时间：2026-07-22
> 作用：调研业界多轮 ReAct 的主流实现方式，结合合同卫士项目特点，给出最适合的落地策略。

---

## 一、多轮 ReAct 的核心思想

ReAct 是 Reasoning（推理）+ Acting（行动）的结合。

**单轮 ReAct**：输入问题 → LLM 直接给出答案。

**多轮 ReAct**：输入问题 → LLM 决定调用什么工具 → 获取工具结果 → LLM 再次思考 → 决定继续调用工具或给出最终答案。

多轮 ReAct 的核心价值是：让 LLM 具备"边查边想"的能力，而不是一次性给出所有结论。

---

## 二、业界主流实现方式

### 方式一：LangChain AgentExecutor

**代表项目**：大量早期的 LangChain 应用。

**实现思路**：
- 定义一组工具，每个工具有名字和描述。
- Agent 根据工具描述选择调用哪个工具。
- AgentExecutor 负责循环：调用 Agent → 解析 Action → 执行工具 → 把结果返回给 Agent → 继续循环。
- 循环结束条件：Agent 输出 "Final Answer"。

**优点**：
- 实现简单，工具注册方便。
- 生态成熟，文档和示例多。
- 对新手友好。

**缺点**：
- 控制力弱，循环过程被封装，难以自定义。
- 容易出现"工具选择错误"导致死循环。
- 对输出格式解析依赖强，稳定性一般。

**适合场景**：快速原型、工具数量少、任务开放式。

---

### 方式二：LangGraph ReAct

**代表项目**：LangGraph 官方示例、需要状态管理的复杂 Agent 系统。

**实现思路**：
- 把 ReAct 建模为图：节点包括 "agent" 和 "tools"。
- 边表示状态流转：agent 节点调用 LLM，tools 节点执行工具。
- 用状态对象存储消息历史、工具结果、中间结论。
- 通过条件边决定是否继续循环或结束。

**优点**：
- 状态管理清晰，每轮的状态都明确可见。
- 支持复杂分支：比如根据条件走不同工具路径。
- 可持久化状态，适合长任务和断点续跑。

**缺点**：
- 学习曲线较陡。
- 需要把任务拆解为图结构，前期设计成本高。
- 对简单任务来说有点重。

**适合场景**：复杂多步骤任务、需要状态持久化、Agent 数量多的系统。

---

### 方式三：OpenAI Function Calling / Tool Calling

**代表项目**：GPT-4 Function Calling、Claude Tool Use、通义千问工具调用。

**实现思路**：
- 把工具定义成 schema，传给 LLM。
- LLM 在需要调用工具时，输出结构化的 tool_calls。
- 代码解析 tool_calls，执行对应函数。
- 把函数结果以 tool 消息的形式返回给 LLM。
- LLM 再次输出，可能是继续调用工具，也可能是最终答案。

**优点**：
- LLM 原生支持工具调用，解析稳定。
- 不需要在 Prompt 中写复杂的格式说明。
- 工具参数有 schema 校验，减少错误。

**缺点**：
- 依赖 LLM 是否支持 function calling。
- 工具描述写得好不好直接影响效果。
- 对非 OpenAI 兼容模型可能需要适配。

**适合场景**：LLM 支持 function calling、对稳定性要求高的生产环境。

---

### 方式四：自定义 ReAct（本项目当前方向）

**实现思路**：
- 不依赖 LangChain 或 LangGraph。
- 在 BaseAgent 中自己实现循环。
- Prompt 中要求 LLM 输出 thought / action / action_input / final_answer。
- 代码解析输出，调用工具，把结果加入消息历史。

**优点**：
- 完全可控，没有框架黑盒。
- 不依赖特定 LLM 的能力（function calling）。
- 容易根据业务需求调整循环逻辑。

**缺点**：
- Prompt 工程要求高。
- 输出解析可能不稳定。
- 需要自己管理消息历史和状态。

**适合场景**：对框架依赖敏感、需要深度定制、LLM 不一定支持 function calling。

---

## 三、四种方式对比表

| 维度 | LangChain AgentExecutor | LangGraph ReAct | OpenAI Function Calling | 自定义 ReAct |
|------|------------------------|-----------------|------------------------|-------------|
| 开发速度 | 快 | 中 | 快 | 慢 |
| 可控性 | 低 | 高 | 中 | 高 |
| 状态管理 | 弱 | 强 | 中 | 需自己实现 |
| 稳定性 | 中 | 中 | 高 | 依赖 Prompt |
| 框架依赖 | 重 | 重 | 轻 | 无 |
| LLM 兼容性 | 较宽 | 较宽 | 需支持 function calling | 最宽 |
| 适合复杂任务 | 一般 | 非常适合 | 适合 | 适合 |

---

## 四、合同卫士项目适合哪种方式

### 项目特点

1. **任务结构化强**：合同审查有明确流程，大部分任务不需要多轮。
2. **工具数量有限**：目前 10 个工具，未来可能扩展到 15-20 个。
3. **对稳定性要求高**：风险等级、法条引用需要确定性输出。
4. **LLM 是 OpenAI 兼容接口**：使用的是阿里云百炼 qwen-max，支持 function calling。
5. **Agent 数量多**：14 个内置 Agent + 1 个抽象基类 `BaseAgent`，需要统一基类管理。
6. **状态管理重要**：SessionGraph 已经承担了大量状态存储职责。

### 推荐方案：混合策略

**主体保留自定义 ReAct + 关键 Agent 使用 function calling 增强**

理由：
- 自定义 ReAct 可控性高，适合统一基类管理。
- 不强制所有 Agent 都多轮，避免成本和延迟爆炸。
- 对需要多轮的 Agent（如 DebateAgent、LegalVerifyAgent），可以走 function calling 路线提升稳定性。

---

## 五、具体落地方案

### 方案一：保守方案（当前已实现）

**内容**：BaseAgent 支持多轮 ReAct，但主要靠 Prompt 让 LLM 输出 action。

**适用 Agent**：所有 Agent 可选启用。

**优点**：改动小，向后兼容。

**缺点**：依赖 Prompt 质量，解析不够稳定。

**实施成本**：低。

### 方案二：function calling 增强方案（推荐）

**内容**：
- 在 BaseAgent 中检测当前 LLM 是否支持 function calling。
- 如果支持，把工具列表以 schema 形式传给 LLM。
- LLM 输出 tool_calls，代码解析并执行。
- 把执行结果以 tool 消息返回给 LLM，继续循环。
- 如果不支持 function calling，回退到方案一。

**适用 Agent**：
- DebateAgent（需要多轮辩论）
- LegalVerifyAgent（需要主动查法条验证）
- CrossReferenceAgent（需要多次检索条款）

**优点**：
- 工具调用解析稳定。
- 不需要在 Prompt 中写复杂格式说明。
- LLM 自主选择工具的能力更强。

**缺点**：
- 需要 LLM 支持 function calling。
- 工具 schema 需要维护。
- 调用成本略高于单轮。

**实施成本**：中。

### 方案三：LangGraph 重构方案

**内容**：
- 把审查流程建模为 LangGraph 图。
- 节点：Route、Preload、LegalResearch、Execute、Merge+Link、LegalVerify、Debate、Triage。
- Execute 节点内部再用 ReAct 循环驱动每个 Agent。
- 状态对象保存 SessionGraph、消息历史、审查进度。

**适用场景**：项目规模扩大后，需要更强的状态管理和可视化。

**优点**：
- 状态管理最清晰。
- 支持断点续跑、人机介入。
- 图结构可视化方便调试。

**缺点**：
- 改造成本高。
- 需要团队熟悉 LangGraph。
- 对当前项目来说可能过度设计。

**实施成本**：高。

---

## 六、分阶段落地建议

### 第一阶段：完善当前自定义 ReAct（已完成 + 继续优化）

**目标**：让所有 Agent 都能稳定运行，单轮为主。

**工作项**：
1. 优化 Prompt，让 LLM 在需要时正确使用 action。
2. 完善 `_parse_react_output`，兼容更多 LLM 输出格式。
3. 增加每轮日志，方便调试。
4. 为 DebateAgent、LegalVerifyAgent 写多轮 Prompt。

### 第二阶段：接入 function calling（推荐做）

**目标**：提升关键 Agent 的多轮稳定性。

**工作项**：
1. 在 LLM 客户端中封装 function calling 调用。
2. 把 10 个工具写成 schema。
3. 在 BaseAgent 中增加 function calling 分支。
4. 对 DebateAgent、LegalVerifyAgent 启用 function calling。
5. 对比 function calling 和自定义 ReAct 的效果。

### 第三阶段：LangGraph 重构（未来可选）

**目标**：当 Agent 数量进一步增加、流程更复杂时，用 LangGraph 重构。

**触发条件**：
- Agent 数量超过 20 个
- 审查流程需要支持人机介入和断点续跑
- 团队有人熟悉 LangGraph

---

## 七、在我们的项目中 function calling 怎么落地

### 7.1 工具 schema 示例

每个工具需要一个描述和参数 schema：

```text
工具名：search_knowledge
描述：在法律知识库中搜索相关法律法规
参数：
  query: string, 搜索关键词
  top_k: integer, 返回结果数量，默认 5

工具名：output_finding
描述：把发现的风险写入 SessionGraph
参数：
  risk_type: string, 风险类型
  level: string, 风险等级，枚举 high/medium/low
  reason: string, 风险原因
  suggestion: string, 修改建议
```

### 7.2 调用流程

```text
1. Agent.run 构造任务提示
2. BaseAgent._react_loop 准备工具 schema
3. 调用 LLM，传入 messages 和 tools
4. LLM 输出：
   - 如果要调用工具：tool_calls = [{"name": "search_knowledge", "arguments": {"query": "试用期"}}]
   - 如果直接给出结论：content = final_answer
5. 解析 tool_calls，执行工具
6. 把工具执行结果加入 messages
7. 重复 3-6，直到 LLM 给出结论或达到 max_turns
```

### 7.3 哪些工具适合被 function calling 调用

| 工具 | 是否适合多轮调用 | 原因 |
|------|----------------|------|
| search_knowledge | 是 | 需要根据推理动态查询法条 |
| search_document | 是 | 需要动态检索合同内相关条款 |
| read_section | 是 | 需要按需读取章节 |
| output_finding | 是 | 作为最终动作写入风险 |
| check_cross_reference | 是 | 需要多次检查条款关系 |
| validate_calculation | 是 | 复杂金额计算可多次验证 |
| web_search | 是 | 联网搜索可多次补充 |
| extract_obligations | 否 | 一次性任务 |
| compare_with_template | 否 | 一次性任务 |
| query_knowledge_graph | 是 | 复杂关系查询 |

---

## 八、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| LLM 反复调用工具不收敛 | 成本增加、延迟变高 | 设置 max_turns；增加 Prompt 约束；设置 tool 调用次数上限 |
| 工具选择错误 | 得到无关结果 | 优化工具描述；增加工具参数校验；必要时人工复核 |
| function calling 解析失败 | 流程中断 | 提供降级到自定义 ReAct 的路径 |
| 多轮导致上下文过长 | token 成本增加、输出质量下降 | 控制每轮 Observation 长度；摘要化历史消息 |
| 输出格式不稳定 | 后续处理困难 | 使用 Pydantic 校验；失败时重试 |

---

## 九、实施状态

**已完成的改动**：

1. **LLM 客户端增强**：`app/llm.py` 新增 `chat_completion_with_tools` 方法，支持 function calling / tool calling。
2. **BaseAgent 多模式支持**：`app/agentkit/base.py` 重构 `_react_loop`，根据 `use_function_calling` 自动切换：
   - `True`：走 function calling 多轮循环
   - `False`：走 Prompt 驱动的单轮/多轮循环（兼容现有 Agent）
3. **Coordinator 注册启用**：对 DebateAgent、LegalVerifyAgent、CrossReferenceAgent 传入 `use_function_calling=True`。
4. **Agent Prompt 优化**：这三个 Agent 的 system_prompt 明确说明可以调用哪些工具。

**未启用 function calling 的 Agent**：

RiskReviewAgent、LegalResearchAgent、MissingClauseAgent、BalanceAgent、LegalBasisAgent、SuggestionAgent、IndustryComplianceAgent、BlindSpotAgent、HumanReviewAgent、ChatAgent、CriticAgent。

这些 Agent 当前单轮即可满足需求，或已在内部通过规则/轻量 LLM 完成校验，后续根据跑测效果再决定是否开启。

---

## 十、推荐决策

**短期（已完成）**：
- ✅ LLM 客户端支持 function calling
- ✅ BaseAgent 支持两种模式切换
- ✅ 对 DebateAgent、LegalVerifyAgent、CrossReferenceAgent 启用

**中期（下一步）**：
- 跑测试合同，对比启用 function calling 和未启用的 Agent 的稳定性
- 根据效果决定是否对其他 Agent 启用
- 优化工具 schema 的参数定义（当前是通用 schema，可以更精确）

**长期（可选）**：
- 如果项目规模扩大，考虑 LangGraph 重构
- 引入状态持久化，支持人机介入和断点续跑

---

## 十一、总结

多轮 ReAct 不是必须，但对复杂 Agent 很有价值。

合同卫士项目当前采用"自定义 ReAct + function calling 增强"的混合策略：
- 主体保留自定义 ReAct，确保可控性和兼容性
- 关键 Agent（Debate、LegalVerify、CrossReference）启用 function calling，提升多轮推理的稳定性

这种策略的好处是改动最小、风险可控、效果显著。
