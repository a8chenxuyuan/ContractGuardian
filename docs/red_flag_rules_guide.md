# RedFlagDetector 规则贡献指南

> 目标：让新红线的添加变得系统化、可测试、不依赖改 prompt，同时保持通用法律原则导向，避免写成测试集补丁。
> 
> 文档更新时间：2026-07-26

---

## 一、什么样的规则应该进 RedFlagDetector

RedFlagDetector（现基于 `PrincipleBasedDetector`）只收录**一望即知的通用法律红线**，标准是：

1. **有明确法律依据**（民法典、公司法、劳动合同法、民间借贷司法解释等）；
2. **表达形式相对固定**（可用数值比较、正则、关键词捕获）；
3. **跨合同类型普遍适用**，或至少在某类合同中普遍适用；
4. **不是测试集补丁**——不能只为某一份合同里的一句话而写规则。

### 适合加入的例子

- 日违约金超过 0.1%（民法典第 585 条 + 司法实践）
- 排除对方检验权、退货权（民法典第 620-622 条）
- 借款年利率超过 LPR 四倍近似值（民间借贷司法解释第 25 条）
- 竞业限制未约定补偿（劳动合同法第 23 条）
- 租赁期限超过 20 年（民法典第 705 条）
- 试用期超过法定上限（劳动合同法第 19 条）

### 不适合加入的例子

- 某份特定合同里的"甲方有权要求乙方每周汇报三次"——这是业务管理条款，不是通用红线；
- 需要大量上下文推理才能判断的"显失公平"——留给 LLM；
- 只在极个别行业出现的特殊监管要求——可进行业规则库，不进通用 RedFlagDetector。

---

## 二、架构说明

当前 RedFlagDetector 已升级为 **PrincipleBasedDetector**，红线不再以硬编码的 `RedFlagRule` 形式存在，而是以**通用法律原则**为核心组织：

```
backend/app/contracts/rules/config/legal_principles.json
        │
        ▼
   PrincipleBasedDetector
        │
        ├── 快速检查（quick_checks）
        │      └── 数值型/关键词型硬规则，保证 recall
        │
        └── 语义推断（semantic inference）
               └── 语义中心 + 轻量 LLM，处理原则层面的泛化理解
```

因此，贡献新红线有两种路径：

1. **新增/扩展原则**：适合通用法律原则层面的红线，写入 `legal_principles.json`；
2. **扩展快速检查**：对已有原则增加新的 `quick_check` 类型或正则模式，写入 `red_flag_detector.py`。

---

## 三、添加一条新原则的步骤

### 步骤 1：在 `legal_principles.json` 中登记原则

打开 `backend/app/contracts/rules/config/legal_principles.json`，在 `principles` 数组中添加：

```json
{
  "id": "your_principle_id",
  "name": "原则中文名称",
  "description": "原则说明，描述什么情况下构成违反。",
  "legal_basis": "《中华人民共和国民法典》第XXX条",
  "applicable_contract_types": ["通用"],
  "risk_type": "风险类型",
  "default_level": "high",
  "decision_prompt": "你正在审查一条合同条款，判断是否违反【原则名称】...\n\n输出 JSON：{\"violated\": true/false, \"level\": \"high/medium/low\", \"confidence\": 0.0-1.0, \"reason\": \"...\", \"suggestion\": \"...\"}",
  "violation_examples": [
    "违反原则的条款示例 1",
    "违反原则的条款示例 2"
  ],
  "non_violation_examples": [
    "不违反原则的条款示例 1",
    "不违反原则的条款示例 2"
  ],
  "quick_checks": {
    "enabled": true,
    "type": "numeric_penalty"
  }
}
```

注意：

- `id` 一旦确定不要轻易改，会写入风险结果的 `deterministic_red_flag` 字段；
- `violation_examples` / `non_violation_examples` 用于预计算语义中心，**必须真实、典型**；
- `default_level` 建议：明确违法用 `high`，明显失衡用 `medium`；
- `quick_checks.type` 必须是已有实现或你新增的类型。

### 步骤 2：实现对应的快速检查（如需要）

如果新原则有明确数值/关键词特征，在 `red_flag_detector.py` 的 `PrincipleBasedDetector` 中新增或扩展快速检查。

已有快速检查类型：

- `numeric_penalty`：比例原则数值检查
- `right_exclusion`：权利保留原则检查
- `good_faith_fairness`：诚信公平原则检查
- `minimum_guarantee`：最低保障原则检查
- `illegal_purpose`：违法目的原则检查
- `waive_liability`：法定责任不可免除原则检查

如果现有类型可以覆盖，直接在 `legal_principles.json` 中引用即可。如果需要新类型：

1. 在 `_run_quick_checks` 中增加分支：

```python
elif check_type == "your_new_check":
    if result := self._check_your_new_check(text, principle):
        findings.append(result)
```

2. 实现 `_check_your_new_check` 方法：

```python
def _check_your_new_check(
    self, text: str, principle: LegalPrinciple
) -> dict[str, Any] | None:
    """你的快速检查说明。"""
    if "必要关键词" not in text:
        return None

    if re.search(r"你的正则表达式", text):
        return self._make_result(
            principle,
            "命中时的理由说明，尽量结合具体数值或文本。",
            level="high",
            matched_text=text,
            evidence_type="keyword_match",
        )
    return None
```

---

## 四、为已有原则扩展快速检查模式的步骤

如果某类红线已经有对应原则（如"比例原则"），只需要扩展其快速检查正则或阈值，不需要新增原则。

### 示例：扩展比例原则的数值检查

在 `_check_numeric_penalty` 中增加新的数值模式：

```python
# 新增：逾期付款滞纳金复利
if re.search(r"滞纳金.*复利|复利.*滞纳金|滞纳金.*滚入", text):
    findings.append(
        self._make_result(
            principle,
            "条款约定滞纳金按复利计算，可能违反利率管制规定。",
            level="high",
            matched_text=text,
            evidence_type="numeric_violation",
        )
    )
```

然后补充测试：

```python
def test_compound_late_fee(detector):
    text = "逾期付款的，按日加收千分之五滞纳金，并按复利计息。"
    result = detector.detect_highest_sync(text)
    assert result is not None
    assert result["pattern_id"] == "proportionality"
```

---

## 五、规则编写最佳实践

### 5.1 尽量用"否定例外"减少误报

如果规则容易在正常条款上误报，先检查是否有例外表述：

```python
def _check_automatic_renewal(self, text: str, principle: LegalPrinciple) -> dict[str, Any] | None:
    if not re.search(r"自动续期|自动续签|自动延长|到期自动", text):
        return None
    # 如果有提前通知或拒绝权利，则不构成风险
    if re.search(r"提前.*通知|书面通知|拒绝续期|不再续约|期满前.*通知", text):
        return None
    return self._make_result(...)
```

### 5.2 数值型规则要给出具体数值

```python
if value > 0.1:
    return self._make_result(
        principle,
        f"条款约定每日违约金/罚息为 {value}%，超过主债权千分之一（0.1%/日）的红线。",
        level="high",
        matched_text=text,
        evidence_type="numeric_violation",
    )
```

### 5.3 中文数字要处理

劳动合同、租赁合同中常见"六个月"、"三年"等中文数字，应做转换。参考 `_parse_chinese_number` 方法。

```python
match = re.search(r"试用期[为是]?\s*(\d+|[一二两三四五六七八九十]+)\s*个月", text)
```

### 5.4 不要假设金额单位一致

涉及金额比较时，注意"万元"和"元"的统一：

```python
val = float(m.group(1))
unit = m.group(2)
if unit == "万元":
    val *= 10000
```

### 5.5 规则之间允许重叠

同一条款可能同时命中多条原则（例如"款到发货，概不退换，不得开箱检验"既违反权利保留原则也违反诚信公平原则）。这是正常的，`detect()` 会返回所有命中结果，上游 Agent 负责合并。

### 5.6 优先快速检查，不确定时退回语义推断

快速检查只处理高置信度的 obvious 情况。如果一条规则需要大量上下文推理，不要硬写成正则，而是依赖原则的语义中心 + LLM 实例化。

---

## 六、原则分级策略

| 等级 | 适用场景 | 置信度 | 是否跳过 Critic |
|------|---------|--------|----------------|
| high | 明确违法、强制性规定 | >=0.85 | 是（对 numeric/statutory 证据） |
| medium | 明显失衡、需结合上下文 | 0.75-0.85 | 视情况而定 |
| low | 轻微嫌疑、主要提示 LLM | <0.75 | 否 |

当前 `RiskReviewAgent` 把 `level=high` 且 `confidence>=0.9` 的快速检查结果视为**确定性红线**，直接跳过 Critic。因此关键原则建议 default_level 设为 `high`，且快速检查输出 confidence >= 0.9。

---

## 七、持续演进方向

1. **原则库扩展**：把更多通用法律红线原则化，如流质/流押、格式条款提示义务、消费者保护等；
2. **按合同类型分组**：未来可把 `legal_principles.json` 拆分为通用原则 + 买卖合同/借款合同/劳动合同/租赁合同/股权转让/保密协议等子原则集；
3. **从司法判例中抽取原则**：定期分析线上漏检案例，把反复出现的通用模式抽象为原则；
4. **原则置信度动态调整**：根据线上反馈，用统计方法调整各原则的触发阈值；
5. **快速检查配置化**：把快速检查的正则/阈值逐步迁移到 JSON/YAML，支持运营人员在不改代码的情况下启用/禁用规则。
