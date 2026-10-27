# 合同卫士 —— AI 审查引擎（Agent 模块）设计说明书

> 文档更新时间：2026-07-26

---

## 一、为什么要做 Agent 模块

合同审查不是一个"问一句、答一句"的简单任务。它需要同时完成：

- 读懂一份几十页的合同，拆成条款；
- 从多个维度（风险、缺失、平衡、引用、行业等）检查；
- 引用真实法律法规，不能胡说；
- 发现条款之间的联系，比如"试用期"和"合同期限"要一起看；
- 给出可执行的修改建议；
- 回答用户"这条为什么这么判"的追问。

如果只用一个大模型一次性处理整份合同，会遇到三个问题：

1. **上下文太长**：合同动辄几十页，容易漏看、看错。
2. **专业能力单一**：一个模型 Prompt 里塞满所有审查维度，容易互相干扰。
3. **结论不可追溯**：模型直接给结论，但说不清是哪条法律、哪个条款、哪一步推理得出的。

所以合同卫士采用 **Multi-Agent（多智能体）架构**：把审查任务拆给多个专业 Agent 并行处理，再通过一个 **Coordinator（调度中心）** 汇总、验证、输出。

---

## 二、设计目标

Agent 模块围绕四个目标设计：

- **专业化**：每个 Agent 只负责一个审查维度，Prompt 更聚焦，结论更专业。
- **可协作**：Agent 之间共享记忆，能发现单个 Agent 看不出来的组合风险。
- **可追溯**：每个风险都有来源 Clause、法律依据、修改建议，推理过程可审计。
- **可进化**：审查经验能沉淀到法律知识库和 few-shot 案例库，系统越用越准。

---

## 三、技术栈与框架选型

| 层级 | 选型 | 理由 |
|------|------|------|
| 后端框架 | FastAPI（Python） | 异步能力强，和 LLM/Agent 生态结合好 |
| Agent 编排 | 自定义 Coordinator | 不依赖外部框架，完全可控 |
| ReAct 循环 | 自定义实现 + function calling 增强 | 控制思考-行动-观察流程，关键 Agent 启用 function calling |
| LLM | 通义千问（qwen-max / qwen-plus） | 国内模型优先，成本低，中文法律场景表现较好 |
| Embedding | BGE-M3 | 中文效果好，支持本地部署 |
| 向量检索 | Qdrant | 合同内语义搜索 + 法律知识库检索 |
| 图数据库 | Neo4j | 法规-条款-案例关系网，支撑跨实体推理 |
| 消息总线 | Redis Pub/Sub | Agent 间实时广播 + SSE 进度推送 |
| 任务队列 | Celery | 文档解析、审查任务异步执行 |

**通俗解释**：

Coordinator 是审查流水线的"工头"，决定每一步具体做什么。每个 Agent 是流水线上的工人，各自有专业技能。SessionGraph 是车间的"公共白板"，所有人都能看到别人写了什么。AgentBus 是车间的"对讲机"，发现紧急情况可以立即广播。RedFlagDetector 是"安全红线仪"，对明显违法条款给出确定性警报。

---

## 四、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户请求                                 │
│          上传合同  →  启动审查  →  查看报告  →  对话追问          │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Coordinator（调度中心）                     │
│                                                                  │
│   Route → Preload → LegalResearch → Execute → Merge+Link →      │
│   LegalVerify → Debate → Triage                                  │
│                                                                  │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   专业 Agent     │    │   专业 Agent     │    │   专业 Agent     │
│  (并行审查)      │    │  (并行审查)      │    │  (并行审查)      │
│                 │    │                 │    │                 │
│ RiskReviewAgent │    │ MissingClauseAgent│   │ BalanceAgent    │
│ LegalBasisAgent │    │ CrossReferenceAgent│  │ SuggestionAgent │
│ LegalResearch   │    │ IndustryCompliance│   │ LegalVerifyAgent│
│ ...             │    │ ...             │    │ ...             │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SessionGraph（共享记忆图）                   │
│                                                                  │
│   Clause ──HAS_RISK──▶ Risk ──BASED_ON──▶ Law                   │
│     │                              │                             │
│     └────RELATES_TO──▶ Clause      ▼                             │
│                              Suggestion                           │
│                                                                  │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AgentBus（消息总线）                        │
│                                                                  │
│   agent_started / finding_added / risk_escalated /              │
│   contradiction_detected / phase_changed / completed            │
│                                                                  │
└─────────────────────────────────┬───────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RedFlagDetector（红线检测层）                 │
│                                                                  │
│   比例原则 / 权利保留原则 / 诚信公平原则 / 最低保障原则 /         │
│   信息披露原则 / 违法目的原则 / 明确性原则 / 法定责任不可免除原则 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、Coordinator：八阶段审查管线

Coordinator 是 Agent 模块的大脑。一次完整的合同审查被拆成八个阶段：

### 5.1 Route（路由分配）

**作用**：决定哪些 Chunk 派给哪些 Agent，以及初始风险等级。

**流程**：
1. 读取文档解析后的 Chunk 列表；
2. 用关键词初筛：匹配"试用期""社保""竞业限制""违约金"等高风险词；
3. 给每个 Chunk 分配默认 Agent（risk_review、missing_clause），命中关键词时追加 balance、legal_basis 等；
4. 风险等级统一为 `high` / `medium` / `low`；
5. 生成 `(chunk, agent_names, risk_level)` 分配表。

**通俗解释**：这一步像医院分诊台，先判断每个条款大概属于哪个科室、紧急程度如何。

### 5.2 Preload（预加载上下文）

**作用**：把合同结构写入 SessionGraph，并提取主体信息。

**流程**：
1. 把所有 Chunk 写入 SessionGraph 作为 `Clause` 节点；
2. 调用 TermExtractionAgent 提取主体信息，写入 `Party` 节点；
3. 将合同条款向量化写入 Qdrant，供后续语义检索使用；
4. 不再预加载固定法条：法律依据改由 LegalResearchAgent 动态推断和检索，避免对非劳动合同类型造成干扰。

### 5.3 LegalResearch（动态法律研究）

**作用**：根据合同内容动态推断适用法律领域，检索法条并生成审查要点。

**流程**：
1. 拼接合同文本，调用一次 LLM 同时推断法律领域和风险信号；
2. 对每个法律领域依次执行：本地知识库检索 → 精准联网检索（若推断出具体法律+条款）→ 泛化联网检索兜底；
3. 快速路径：当本地+精准检索无结果且风险信号弱时，跳过泛化 web search，避免在合法合同上空转；
4. 生成审查要点并写入 `Law` 节点；
5. 返回 `discovered_laws`、`review_checklist`、`risk_signals` 给 Coordinator。

**优化点**：
- 合并法律领域推断与风险信号推断为一次 LLM 调用；
- 类级缓存 `_review_point_cache` 和 `_web_search_cache` 避免重复调用；
- 高频法条使用 `REVIEW_POINT_TEMPLATES` 预制模板，跳过 LLM；
- 泛化 web search 限制每个合同最多 3 次。

### 5.4 Execute（并行执行）

**作用**：多个专业 Agent 同时审查各自负责的 Chunk。

**流程**：
1. Coordinator 根据 Route 结果并行启动 Agent；
2. 每个 Agent 内部运行独立的 ReAct 循环或单轮 LLM 调用；
3. Agent 发现风险后写入 SessionGraph；
4. 高风险发现通过 AgentBus 实时广播；
5. 所有 Agent 完成后，Coordinator 汇总执行日志。

### 5.5 Merge+Link（合并与关联）

**作用**：合并重复风险，发现跨条款组合风险。

**流程**：
1. 去重：调用 `merge_duplicate_risks`，先按法律指纹分组，再按 `risk_type + clause_text` 相似度合并；
2. 关联：对语义相关的 Clause 建立 `RELATES_TO` 边；
3. 冲突：对互相矛盾的 Clause 建立 `CONTRADICTS` 边；
4. 组合风险：根据 `cross_clause_rules.json` 预定义规则生成新的风险，例如：
   - 试用期 6 个月 + 合同期限 2 年 → 试用期超长
   - 放弃社保 + 工资拆分 → 规避社保缴费基数
5. LLM 兜底：只有当规则命中了组合风险，或图中已存在 high/medium 风险时，才调用 LLM 跨条款检测，避免在合法合同上浪费一次 LLM 调用。

### 5.6 LegalVerify（法条验证）

**作用**：验证 Agent 引用的法条是否真实、准确。

**流程**：
1. 先调用 LegalBasisAgent 为 Risk 节点补充 `law_refs`；
2. 再调用 LegalVerifyAgent 在知识库中核对法条内容；
3. 对无法验证的法条调用 `web_search` 二次确认；
4. 标记 Law 节点状态：`verified` / `unverified` / `incorrect`；
5. 对 unverified/incorrect 的，降低关联 Risk 的置信度。

### 5.7 Debate（正反辩论）

**作用**：对高风险或低置信度发现进行正反辩论，降低误判率。

**流程**：
1. 筛选需要辩论的 Risk（high 等级、confidence < 0.8、Agent 冲突等）；
2. 正方 Agent 论证这是风险，反方 Agent 论证不是风险或存在例外；
3. Coordinator 根据辩论结果裁决：保留 / 降级 / 撤销；
4. 更新 SessionGraph 中的 Risk 状态。

### 5.8 Triage（结果分流）

**作用**：输出最终审查结果，并把需要人工复核的项分流出去。

**流程**：
1. 按 level 和 confidence 对所有 Risk 分类；
2. 生成最终 `findings` 列表；
3. 低置信度、组合风险、Agent 冲突、法条验证失败项进入 `human_review_items`；
4. 生成审查统计 `stats`；
5. 把 SessionGraph 序列化为 `graph_data`。

---

## 六、SessionGraph：共享记忆图

SessionGraph 是单次审查会话的"公共白板"，所有 Agent 都可以读写。

### 6.1 节点类型

| 节点 | 含义 | 关键属性 |
|------|------|---------|
| `Session` | 会话根节点 | session_id, contract_id, contract_type, status |
| `Clause` | 合同条款/Chunk | chunk_id, text, page, bbox, section_path |
| `Risk` | 风险发现 | risk_type, level, confidence, reason, status |
| `Law` | 法律依据 | law_name, article_number, article_text, source |
| `Case` | 典型案例 | title, summary, court, verdict |
| `Party` | 合同主体 | party_type, name, role |
| `Suggestion` | 修改建议 | original_text, revised_text, rationale |
| `Evidence` | 支持证据 | evidence_type, content, source_chunk_id |
| `AgentState` | Agent 执行状态 | agent_name, chunk_id, status, logs |

### 6.2 边类型

| 边 | 起点 | 终点 | 含义 |
|---|------|------|------|
| `HAS_CLAUSE` | Session | Clause | 会话包含某条款 |
| `HAS_RISK` | Clause | Risk | 某条款存在某风险 |
| `BASED_ON` | Risk | Law | 风险依据某法条 |
| `SUPPORTED_BY` | Risk | Evidence | 风险被某证据支持 |
| `SUGGESTS` | Risk | Suggestion | 风险对应修改建议 |
| `INVOLVES` | Clause | Party | 条款涉及某主体 |
| `RELATES_TO` | Clause | Clause | 条款之间相互关联 |
| `CONTRADICTS` | Clause | Clause | 条款之间相互冲突 |
| `DEPENDS_ON` | Risk | Risk | 风险之间存在依赖 |
| `PRODUCED_BY` | Risk | AgentState | 风险由某 Agent 产生 |

### 6.3 生命周期

1. **初始化**：创建 Session 根节点；
2. **填充**：写入 Clause、Party 节点；
3. **协作写入**：各 Agent 写入 Risk、Law、Evidence、Suggestion；
4. **合并关联**：去重、建边、生成组合风险；
5. **验证固化**：法条验证、正反辩论、人工复核标记；
6. **持久化与回放**：序列化到数据库，ChatAgent 可重新加载。

### 6.4 风险去重：法律指纹

`merge_duplicate_risks` 不再仅依赖文本相似度，而是先用 `_legal_fingerprint` 把同一法律问题的不同表述归一化：

- 比例原则 + 日违约金 5% → `proportionality:daily:5%`
- 试用期超长 + 6个月 → `minimum_guarantee:probation:6months`
- 违法目的 + 赌博 → `illegal_purpose:赌博`

同一指纹组内再做文本相似度合并，保留最高等级和最高置信度，合并 `law_refs`、`suggestion`、`clause_text`。

---

## 七、AgentBus：实时消息总线

AgentBus 解决 Agent 之间"如何实时通信"的问题。生产环境必须直接使用 Redis Pub/Sub，不再降级为内存队列。

### 7.1 核心事件

| 事件 | 含义 | 消费方 |
|------|------|--------|
| `agent_started` | Agent 开始审查某个 Chunk | Coordinator、前端 SSE |
| `agent_completed` | Agent 完成某个 Chunk | Coordinator |
| `finding_added` | Agent 发现新的风险 | 其他 Agent、前端 SSE |
| `risk_escalated` | 风险等级被上调 | Coordinator、HumanReviewAgent |
| `evidence_found` | 找到关键证据 | 相关 Risk 节点 |
| `contradiction_detected` | 发现条款冲突 | DebateAgent、Coordinator |
| `phase_changed` | Coordinator 阶段切换 | 前端 SSE |
| `completed` | 整个审查流程完成 | 前端 SSE |

### 7.2 为什么需要 AgentBus

SessionGraph 是被动的存储，AgentBus 是主动的通知。如果没有 AgentBus，一个 Agent 发现高风险后，其他 Agent 要一直轮询 SessionGraph 才能知道。有了 AgentBus，发现高风险可以立即广播，触发其他 Agent 关注或 Coordinator 调整策略。

### 7.3 技术实现

- 频道格式：`review:{session_id}:events`
- 必须使用 Redis Pub/Sub，不再支持内存队列降级。
- 应用关闭或审查结束时，必须调用 `agent_bus.aclose()` 释放连接。

---

## 八、Agent 分类与职责

### 8.1 审查前准备

**TermExtractionAgent（条款提取 Agent）**

- 提取关键商务条款：甲方、乙方、合同期限、试用期、工作地点、岗位、工资、工作时间、社保、竞业限制、违约金、保密义务、解除条件。
- 把提取结果写入 SessionGraph 的 Party 节点和 Clause 节点 metadata。

### 8.2 法律研究 Agent

**LegalResearchAgent（动态法律研究 Agent）**

- 读取合同全文，推断可能适用的法律领域、具体法律名称与条款号；
- 调用 `search_knowledge`（含 Tavily 联网缓存兜底）检索相关法律原文；
- 将检索到的法条转化为「审查要点」，写入 SessionGraph 的 Law 节点；
- 把发现的法律依据与动态审查清单返回给 Coordinator，供后续 Agent 使用。

### 8.3 主审查 Agent

| Agent | 职责 |
|-------|------|
| RiskReviewAgent | 识别不公平/高风险条款，集成 RedFlagDetector 与 CriticAgent |
| MissingClauseAgent | 检查必要条款是否缺失 |
| BalanceAgent | 分析甲乙双方权利义务是否对等 |
| CrossReferenceAgent | 检查条款间引用是否准确一致 |
| LegalBasisAgent | 为风险匹配法律依据 |
| SuggestionAgent | 生成具体修改建议 |
| IndustryComplianceAgent | 针对建筑、互联网、医药等行业做特殊合规检查 |

### 8.4 验证与复核 Agent

| Agent | 职责 |
|-------|------|
| LegalVerifyAgent | 验证法条引用是否真实准确 |
| DebateAgent | 对高风险或低置信度项进行正反辩论 |
| BlindSpotAgent | 扫描审查盲区 |
| HumanReviewAgent | 把需要人工复核的项分流到复核工作台 |

### 8.5 对话 Agent

**ChatAgent（对话追问 Agent）**

- 基于 SessionGraph 回答用户对审查结果的追问；
- 支持划词提问；
- 回答必须引用具体 Clause / Risk / Law，不能凭空判断。

---

## 九、RedFlagDetector：原则驱动的红线检测层

RedFlagDetector（当前实现为 `PrincipleBasedDetector`）是审查的第一层防线，确保明显违法/高风险条款不被 LLM 漏掉。

### 9.1 为什么需要 RedFlagDetector

- LLM 面对"抑制误报"和"报告红线"的冲突指令时，容易偏向保守，导致漏检；
- 明显违法条款（如日违约金 5%、排除检验权）应由确定性规则捕获，不依赖模型理解；
- 规则基于通用法律原则，跨合同类型泛化能力强，不是测试集补丁。

### 9.2 检测流程

```
待审条款
   │
   ▼
快速检查（数值/关键词型红线）
   │── 命中 high 红线 → 强制输出，可跳过 Critic
   │
   ▼
语义召回（计算与原则语义中心相似度）
   │
   ▼
轻量 LLM 实例化判断
   │── 确认违反原则 → 输出风险
   └── 未违反 → 不输出
```

### 9.3 通用法律原则

| 原则 ID | 原则名称 | 快速检查类型 | 典型红线 |
|---------|---------|-------------|---------|
| `proportionality` | 比例原则 | `numeric_penalty` | 日违约金 > 0.1%、一次性违约金 > 30%、年利率 > 12% |
| `right_preservation` | 权利保留原则 | `right_exclusion` | 排除检验权、验收权、异议权、退换货权、解除权 |
| `good_faith_fairness` | 诚信公平原则 | `good_faith_fairness` | 任意单方变更/解除/涨租、自动续期未通知 |
| `minimum_guarantee` | 最低保障原则 | `minimum_guarantee` | 试用期超限、试用期工资 < 80%、不缴社保、租赁期限 > 20 年 |
| `illegal_purpose` | 违法目的原则 | `illegal_purpose` | 砍头息、借款用于赌博/非法集资、流质流押、复利 |
| `non_waivable_liability` | 法定责任不可免除原则 | `waive_liability` | 免除故意/重大过失责任、免除质量保证义务 |
| `disclosure` | 信息披露原则 | 无快速检查 | 隐瞒质押、抵押、债务负担等重大信息 |
| `clarity` | 明确性原则 | 无快速检查 | 关键义务、质量标准、计算方式约定不明 |

原则配置位于 `backend/app/contracts/rules/config/legal_principles.json`。

### 9.4 与 RiskReviewAgent 的集成

1. 每条款先跑 `RedFlagDetector.detect()`；
2. 若命中 `level=high` 且 `confidence>=0.9` 的确定性红线：
   - 绕过 keyword filter；
   - 在 prompt 中注入红线命中信息；
   - few-shot 正例加权；
   - 若 LLM 仍输出 `low`，用红线结果兜底（必须同步覆盖 reason/suggestion，避免结论与论证断裂）；
   - 对 `numeric_violation` / `statutory_violation` / `statutory_exclusion` 类型跳过 Critic；
3. 未命中红线时：保持 keyword filter + LLM + Critic 流程；
4. 整体性审查同样增加红线检测，命中则跳过 Critic。

---

## 十、CriticAgent：二次校验层

CriticAgent 由 `RuleCritic` 规则快速路径和 `LLM Critic` 边界复核路径组成。

### 10.1 设计目标

- 把常见、明确的误报模式交给规则快速处理，减少 LLM 调用；
- 把边界、模糊案例留给 LLM Critic；
- 所有规则基于通用法律原则，不能是测试集补丁；
- 输出结构化的校验结论，供上游调整风险等级或置信度。

### 10.2 RuleCritic 规则列表（15 条）

| 规则 | 说明 |
|------|------|
| 结论与理由自相矛盾 | 理由说合法但等级为 high/medium |
| 否定语境下的违法目的误判 | "不得用于赌博"被误判为违法目的 |
| 试用期未结合合同期限 | 未按劳动合同法第 19 条判断 |
| 正常付款结构被误判为失衡 | 预付款/分期付款/验收后付款 |
| 违约金与损失并用被误判为重复 | 中国法下可并用 |
| 有对价的知识产权归属被误判为排除权利 | 委托开发中约定归属属正常商业安排 |
| 未约定某事项被误判为风险 | 法律已提供默认规则 |
| 双方违约金基数不同被误判为失衡 | 比例相同或接近则合法 |
| 择一主张被误判为重复索赔 | "择一/就高/差额补足"合法 |
| 普通押金被误判为惩罚 | 无"一概不退"表述的押金合法 |
| 未约定质量标准被误判为排除质保 | 民法典提供默认规则 |
| 弹性表述被误判为显失公平 | "合理""适当"等原则性措辞 |
| 利率与逾期罚息被简单相加误判为超限 | 适用对象和期间不同 |
| 借款合同生效日期被误判为违法 | "自签字之日起生效"属常见表述 |
| 借款合同付息日与起息日不一致被误判为错配 | 常见日历安排 |

### 10.3 与 RiskReviewAgent 的集成

- 规则返回 `false_positive`：直接降为 `low`；
- 规则返回 `valid`：保留并可能提升置信度；
- 规则返回 `uncertain`：进入 LLM Critic；
- LLM Critic 输出 `verdict`、`confidence_adjustment`、`reason`。

---

## 十一、ReAct 循环与工具调用

每个 Agent 内部可采用 **ReAct（Reasoning + Acting）** 循环或单轮 LLM 调用。

### 11.1 ReAct 循环示例

以 RiskReviewAgent 审查"试用期为六个月"为例：

1. **Thought**：这条提到了试用期，需要判断试用期是否超过法定上限。
2. **Action**：调用 `search_knowledge`，输入 query "劳动合同试用期上限"。
3. **Observation**：返回《劳动合同法》第19条，1-3 年期合同试用期不得超过 2 个月。
4. **Thought**：合同期限是 2 年，试用期 6 个月超过法定上限，构成违法。
5. **Action**：写入 Risk 节点。
6. **Observation**：写入成功，返回 risk_id。
7. **Output**：输出审查结论。

### 11.2 Function Calling 增强

- `LLMClient` 支持 `chat_completion_with_tools`；
- `BaseAgent` 支持 `use_function_calling=True`；
- 已启用 function calling 的 Agent：`DebateAgent`、`LegalVerifyAgent`、`CrossReferenceAgent`；
- 其他 Agent 当前单轮即可满足需求，后续根据跑测效果再决定是否开启。

### 11.3 工具集

| 工具 | 作用 |
|------|------|
| `web_search` | 联网搜索法规和案例 |
| `search_document` | 在合同内部语义/关键词搜索 |
| `search_knowledge` | 在本地法律知识库检索 |
| `read_section` | 读取指定章节或条款全文 |
| `output_finding` | 把风险发现写入 SessionGraph |
| `check_cross_reference` | 检查条款引用是否准确 |
| `extract_obligations` | 提取甲乙双方权利义务 |
| `validate_calculation` | 验证金额、日期、比例计算 |
| `compare_with_template` | 与标准范本对比 |
| `query_knowledge_graph` | 在 Neo4j 图库中做关系查询 |

### 11.4 RAG 在 Agent 模块中的应用

#### （1）`search_knowledge` —— 法律知识库 RAG

- **检索源**：Qdrant 向量语义检索 → PostgreSQL/SQLite 关键词检索 → Tavily 联网搜索兜底
- **缓存**：外部法条按 `law_name + article_number` 缓存
- **使用方**：RiskReviewAgent、LegalBasisAgent、DebateAgent、LegalVerifyAgent、LegalResearchAgent

#### （2）`search_document` —— 合同内部 RAG

- **检索源**：当前合同自身的 Chunk 向量索引（Qdrant），无 `contract_id` 时回退本地关键词匹配
- **使用方**：RiskReviewAgent、CrossReferenceAgent、ChatAgent

#### （3）`web_search` —— 联网搜索兜底 RAG

- **检索源**：Tavily API
- **使用方**：LegalVerifyAgent、LegalResearchAgent
- **限制**：每个合同最多 3 次泛化 web search

---

## 十二、性能优化要点

1. **LegalResearch 快速路径**：本地+精准检索无结果且风险信号弱时，跳过泛化 web search；
2. **整体性审查跳过**：RiskReviewAgent 若逐条审查无高/中风险且无确定性红线，跳过全文 LLM 调用；
3. **跨条款 LLM 兜底跳过**：当规则未命中组合风险且图中无 high/medium 风险时，跳过 LLM 跨条款检测；
4. **Critic 规则快速路径**：15 条规则过滤常见误报，减少 LLM 调用；
5. **类级缓存**：LegalResearchAgent 的审查要点和 web search 结果做类级缓存；
6. **模型加载优化**：`vector_store._ensure_collection` 仅在需要创建 collection 时加载 BGE-M3；
7. **风险去重优化**：法律指纹 + 2-gram Jaccard 相似度 + clause_ids 交集。

---

## 十三、风险等级规范

所有风险等级必须统一为：

- `high`：硬性违法，必须修改；
- `medium`：法律风险，建议修改；
- `low`：无明显风险或仅起草优化建议。

非标准值（如 `critical`）在 `_triage` 阶段会被映射为 `medium`。
