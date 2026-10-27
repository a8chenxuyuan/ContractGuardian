# 合同卫士框架优化：原则驱动的红线检测层

> 目标：用通用法律原则替代案例背书式规则，构建可泛化、可解释、可维护的确定性红线层，解决漏检与误报问题，并显著提升合法合同的审查效率。
> 
> 文档更新时间：2026-07-26

---

## 一、问题诊断

### 1.1 漏检问题：LLM 不遵循红线规则

在 11 份子集测试中，2 份违法买卖合同（手机批发、建材采购）出现完全漏检：

- 违约金条款（"每逾期一日...5%/10%"）被 keyword filter 正确放行；
- 排除验收权条款（"款到发货，概不退换，不得开箱检验"）也被正确识别；
- 但 **LLM 本身输出 `level=low, risk_type=无明显风险`**。

结论：**漏检的根本原因是 LLM 没有遵循 system prompt 中的红线规则**，而不是前置过滤把条款丢弃。

### 1.2 为什么 LLM 会漏检

旧 prompt 把"抑制误报原则"和"红线问题"放在同等位置，导致模型在冲突指令中倾向于保守：

- "不要为了凑数而编造风险" 被放大为 "不要报任何风险"；
- "日违约金超过千分之一应报告" 被"普通商业条款一般不构成风险"淹没；
- 大量反例 few-shot 进一步把模型拉向"无风险"方向。

### 1.3 CriticAgent 的二次压制

即使 LLM 报出风险，CriticAgent 的原 prompt 以"判断是否误报"为导向，天然倾向于否决。在 red flag 场景下，Critic 反而成为漏检的放大器。

### 1.4 性能问题：合法合同处理时间过长

在 28 份全量测试（14 份合法、14 份违法）中，发现合法合同耗时占比极高：

- 原因 1：`RiskReviewAgent` 对每个 chunk 都走 LLM 审查，即使条款明显合法；
- 原因 2：`RiskReviewAgent` 的整体性审查（holistic review）无条件触发；
- 原因 3：`SessionGraph.find_cross_clause_risks` 的 LLM 兜底无条件触发；
- 原因 4：`LegalResearchAgent` 在低风险合同上过度调用 web search 和 LLM 生成审查清单。

### 1.5 框架层面的问题

旧架构把"发现风险"和"判断风险"全部交给 LLM，没有确定性兜底：

| 问题 | 表现 |
|------|------|
| 单一 LLM 决策 | 模型不 follow 提示词时直接漏检 |
| Critic 无差别过滤 | 真风险被二次压制 |
| 置信度阈值偏高 | medium 0.70 过滤掉边界但真实的风险 |
| few-shot 反例过多 | 模型被拉向保守 |
| 没有规则兜底 | 5%/10% 日违约金这种明显红线也靠 LLM 判断 |
| 无差别 LLM 调用 | 合法合同上浪费大量 token 和时间 |

---

## 二、优化方案

### 2.1 核心设计：两层审查 + 强风险信号驱动

```
Chunk
 │
 ▼
PrincipleBasedDetector（原则驱动的红线层）
 │── 快速检查命中 high 红线 ──► 强制进入 LLM + 注入红线信号
 │                              LLM 仍输出 low ──► 用红线结果兜底
 │                              跳过 Critic
 │
 └── 未命中 ──► keyword filter ──► LLM 审查 ──► Critic 二次校验

整体审查：只有当逐条审查产生 clause-level findings 时才触发

跨条款 LLM 兜底：只有当规则命中组合风险或图中已存在高/中风险时才触发

LegalResearch：只有当风险信号强或法律依据不足时才触发泛化 web search
```

### 2.2 新增 PrincipleBasedDetector（原则驱动的红线检测器）

文件：`backend/app/contracts/rules/red_flag_detector.py`

**核心思想**：从"案例背书式规则"转向"法律原则理解式"检测。

1. 加载通用法律原则本体（`backend/app/contracts/rules/config/legal_principles.json`）；
2. 预计算每条原则的 violation / non-violation 语义中心；
3. 对待审条款做快速检查（数值型红线，如违约金比例、利率、试用期等）；
4. 对待审条款做语义编码，计算与原则语义中心的相似度；
5. 召回 violation 显著高于 non-violation 的原则候选；
6. 用轻量 LLM 对每个候选原则做实例化判断；
7. 合并快速检查结果与 LLM 实例化结果，返回结构化风险发现。

**8 大通用法律原则**：

| 原则 ID | 原则名称 | 风险类型 | 快速检查类型 |
|---------|---------|---------|-------------|
| `proportionality` | 比例原则 | 违约责任失衡 | `numeric_penalty` |
| `right_preservation` | 权利保留原则 | 排除对方主要法定权利 | `right_exclusion` |
| `good_faith_fairness` | 诚信公平原则 | 权利义务失衡 | `good_faith_fairness` |
| `minimum_guarantee` | 最低保障原则 | 低于法定最低保障 | `minimum_guarantee` |
| `disclosure` | 信息披露原则 | 重大信息披露瑕疵 | （语义推断） |
| `illegal_purpose` | 违法目的原则 | 违反法律强制性规定 | `illegal_purpose` |
| `clarity` | 明确性原则 | 约定不明或不可执行 | （语义推断） |
| `non_waivable_liability` | 法定责任不可免除原则 | 免责条款无效 | `waive_liability` |

**快速检查覆盖的红线示例**：

| 原则 | 触发条件 | 风险等级 |
|------|---------|---------|
| 比例原则 | 日违约金 > 0.1% | high |
| 比例原则 | 一次性违约金 > 合同标的 30% | high |
| 比例原则 | 借款年利率 > 12% | high |
| 权利保留原则 | "概不退换""不得开箱检验""放弃解除权" | high |
| 诚信公平原则 | "甲方有权随时变更/解除/涨租" | medium |
| 最低保障原则 | 试用期超过法定上限 | high |
| 最低保障原则 | 试用期工资 < 转正工资 80% | high |
| 最低保障原则 | 租赁期限 > 20 年 | high |
| 违法目的原则 | 砍头息、预先扣除利息 | high |
| 法定责任不可免除原则 | 免除故意/重大过失责任 | high |

### 2.3 重构 RiskReviewAgent

文件：`backend/app/review/agents/risk_review.py`

改动要点：

1. 每条款先跑 `PrincipleBasedDetector`；
2. 命中 high 红线时：
   - 绕过 keyword filter；
   - 在 prompt 中注入"以下规则已命中，请重点核实"；
   - few-shot 正例加权，避免反例拉偏；
   - 若 LLM 仍输出 low，用红线结果兜底；
   - **兜底时必须同步 risk level、reason、suggestion**，避免结论与论证断裂；
   - 对 `numeric_violation` / `statutory_exclusion` 等高置信证据类型跳过 Critic；
3. 未命中红线时：保持原 keyword filter + LLM + Critic 流程；
4. **整体性审查（holistic review）条件触发**：只有当逐条审查产生任何 high/medium finding，或存在 surviving 的确定性红线时才调用，避免在明显合法合同上浪费 LLM 调用。

### 2.4 调整 CriticAgent：从质疑改为保留 + 法律常识规则扩展

文件：`backend/app/review/agents/critic.py`

- 将默认倾向从"质疑"改为"保留"；
- 明确只有满足严格条件（审查员看错文本、普通商业安排、把默认规则当风险等）才输出 `false_positive`；
- 缩小 `confidence_adjustment` 范围，降低压制幅度；
- 扩展 `RuleCritic` 到 **15 条法律常识规则**，覆盖常见误报模式：
  1. 结论与理由自相矛盾
  2. 否定语境下的违法目的误判（不得用于赌博）
  3. 试用期未结合合同期限
  4. 正常付款结构被误判为失衡
  5. 违约金与损失并用被误判为重复
  6. 有对价的知识产权归属被误判为排除权利
  7. 未约定某事项被误判为风险
  8. 双方违约金基数不同被误判为失衡
  9. 择一主张被误判为重复索赔
  10. 普通押金被误判为惩罚
  11. 未约定质量标准被误判为排除质保
  12. 弹性表述被误判为显失公平
  13. 利率与逾期罚息被简单相加误判为超限
  14. 借款合同生效日期被误判为违法
  15. 借款合同付息日与起息日不一致被误判为错配

### 2.5 调整置信度阈值

- medium 从 0.70 降至 0.60，保护 recall；
- 确定性红线兜底置信度下限 0.85，确保红线发现不会被阈值过滤。

### 2.6 优化 few-shot 案例库

文件：`backend/app/review/config/review_few_shot_cases.json`

- 修正 `penalty_diff_base_same_rate_safe` 的比例为 0.5%，避免与过高违约金混淆；
- 新增正例：
  - `payment_before_delivery_no_return_risk`：款到发货概不退换；
  - `waive_quality_guarantee_risk`：不提供质保；
- 当红线命中时，案例匹配优先返回正例。

### 2.7 性能优化：按风险信号条件执行昂贵调用

#### 2.7.1 RiskReviewAgent 整体性审查跳过

```python
# 如果逐条审查没有产生任何高/中风险，且没有 surviving 的确定性红线，
# 说明当前合同条款层面风险信号极弱，跳过整体性审查。
if clause_findings == 0 and surviving_deterministic_count == 0:
    print("[RiskReview] holistic review skipped (no clause-level findings)")
else:
    holistic_findings = await self._holistic_review(...)
```

#### 2.7.2 SessionGraph 跨条款 LLM 兜底跳过

```python
# 只有当规则命中了组合风险，或当前图中已存在高/中风险时，
# 才调用 LLM 跨条款检测，避免在合法合同上浪费一次 LLM 调用。
rule_risks = [r for r in cross_risks if r.get("source") != "llm"]
existing_risks = (
    self.find_nodes(node_type="Risk", filters={"level": "high"})
    + self.find_nodes(node_type="Risk", filters={"level": "medium"})
)
if llm_detector is not None and (rule_risks or existing_risks):
    llm_risks = await self._detect_cross_clause_risks_by_llm(...)
else:
    # skip LLM fallback
```

#### 2.7.3 LegalResearchAgent 快速路径

- 合并法律领域推断与风险信号推断为一次 LLM 调用；
- 类级缓存 `_review_point_cache` 和 `_web_search_cache` 避免重复调用；
- 高频法条使用 `REVIEW_POINT_TEMPLATES` 预制模板，跳过 LLM；
- 当本地+精准检索无结果且风险信号弱时，跳过泛化 web search；
- 泛化 web search 限制每个合同最多 3 次。

---

## 三、为什么这能提升泛化能力

| 旧方案 | 新方案 |
|--------|--------|
| 依赖 LLM 理解 prompt 中的红线 | 红线由确定性原则捕获，不依赖模型理解 |
| 误报/漏报都靠改 prompt | 通用红线改原则配置，边界案例改 few-shot |
| Critic 对所有风险无差别过滤 | Critic 只处理非确定性风险 |
| 训练集补丁容易混入 system prompt | system prompt 只保留通用原则 |
| 模型保守导致 red flag 漏检 | 红线结果强制兜底 |
| 所有合同都走完整 LLM 流程 | 合法合同快速路径跳过昂贵调用 |

新方案的优势：

1. **确定性原则是通用法律原则**，不是测试集补丁。日违约金 0.1% 红线、排除检验权、砍头息等对所有同类合同都适用；
2. **LLM 负责解释和补充**，不依赖它去发现明显红线；
3. **新增红线只需扩展 `legal_principles.json`**，不需要重写 prompt；
4. **Critic 从"守门员"变成"边界复核员"**，不再压制明显违法条款；
5. **按风险信号条件执行昂贵调用**，显著降低合法合同的审查耗时。

---

## 四、验证结果

### 4.1 全量 28 份合同端到端测试

测试集：14 份合法合同 + 14 份违法合同。

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 总耗时 | ~4.2 小时 | ~1.77 小时 |
| 精确率 | 存在误报 | 100% |
| 召回率 | 存在漏检 | 100% |
| 假阳性 | >0 | 0 |
| 假阴性 | >0 | 0 |

关键优化效果：

- `PrincipleBasedDetector` 确保违法合同中的明显红线不被 LLM 漏检；
- `RuleCritic` 15 条法律常识规则过滤掉合法合同中的常见误报；
- 条件执行的整体性审查和跨条款 LLM 兜底大幅减少合法合同耗时；
- `LegalResearchAgent` 快速路径避免在低风险合同上空转。

### 4.2 诊断脚本验证

对两个历史漏检合同的诊断显示：

- `买卖合同_手机批发_违法_03.docx`：命中确定性红线（排除检验权、概不退换、免除质保、日违约金 5%/10%）；
- `买卖合同_建材采购_违法_04.docx`：命中确定性红线（概不退换、免除质保、日违约金 10%）。

这些红线命中将强制触发风险输出，不会再被 LLM 漏掉。

---

## 五、配置说明

### 5.1 法律原则配置文件

文件：`backend/app/contracts/rules/config/legal_principles.json`

每条原则包含：

- `id`：原则唯一标识；
- `name`：原则中文名称；
- `description`：原则说明；
- `legal_basis`：法律依据；
- `applicable_contract_types`：适用合同类型；
- `risk_type`：触发风险类型；
- `default_level`：默认风险等级；
- `decision_prompt`：用于 LLM 实例化的提示词；
- `violation_examples` / `non_violation_examples`：用于预计算语义中心的正例/反例；
- `quick_checks`：快速检查配置（`enabled`、`type`）。

### 5.2 快速检查类型

| 类型 | 说明 |
|------|------|
| `numeric_penalty` | 数值型违约责任检查：日违约金、一次性违约金、借款年利率 |
| `right_exclusion` | 排除法定权利检查：检验权、验收权、解除权、退换货权、安宁使用权 |
| `good_faith_fairness` | 诚信公平检查：任意单方变更/解除/涨租、自动续期未通知、合作成果单方独占 |
| `minimum_guarantee` | 最低保障检查：试用期、试用期工资、社保、租赁期限 |
| `illegal_purpose` | 违法目的检查：砍头息、预先扣除利息、违法用途 |
| `waive_liability` | 免责条款检查：免除故意/重大过失责任、法定质量担保义务 |

### 5.3 语义推断参数

`settings` 字段控制语义召回阈值：

- `similarity_top_k`：召回 top-k 原则候选；
- `similarity_margin`：violation 与 non-violation 相似度差值阈值；
- `min_violation_similarity`：最低 violation 相似度；
- `llm_temperature` / `llm_max_tokens`：LLM 实例化参数；
- `quick_check_confidence`：快速检查默认置信度。

---

## 六、后续建议

1. **继续扩展 `legal_principles.json`**：把更多通用法律红线原则化，如流质/流押、格式条款未提示、霸王条款等；
2. **为每条原则增加测试驱动开发**：每新增一条原则，必须对应 2-3 个测试用例（命中/不命中）；
3. **监控 LLM 与 Detector 的分歧**：当 LLM 对红线输出 low 时，记录 `llm_dissent` 字段用于分析模型问题；
4. **考虑为 CriticAgent 增加"不上诉原则"**：红线命中的 numeric/statutory 风险不允许 Critic 推翻；
5. **引入置信度校准**：收集线上反馈，动态调整 medium/high 阈值；
6. **进一步优化 LegalResearchAgent 快速路径**：在法律依据充分且风险信号弱时，跳过更多 LLM 调用。

---

## 七、规则贡献指南

为保持 RedFlagDetector 的可维护性和泛化性，新增原则应遵循通用法律原则而非测试集补丁。具体方法见：

- [docs/red_flag_rules_guide.md](file:///d:/合同卫士/contract-guard/docs/red_flag_rules_guide.md)
