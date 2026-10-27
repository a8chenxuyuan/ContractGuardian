"""
文件：app/review/agents/critic.py
作用：CriticAgent 对 RiskReviewAgent 提出的候选风险做二次校验。

设计目标：
1. 把常见、明确的误报模式交给规则快速处理，减少 LLM 调用；
2. 把边界、模糊案例留给 LLM Critic；
3. 所有规则必须基于通用法律原则，不能是测试集补丁；
4. 输出结构化的校验结论，供上游调整风险等级或置信度。

分层流程：
输入候选风险
  ↓
RuleCritic（规则快速路径）
  ├── 明确误报 → false_positive，直接过滤
  ├── 明确成立 → valid，保留并可能提升置信度
  └── 不确定/边界 → uncertain，进入 LLM Critic
  ↓
LLM Critic（轻量模型）
  └── 输出最终 verdict / adjustment / reason
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agentkit.base import BaseAgent
from app.review.learning import get_counter_example_store
from app.review.prompts.critic import CRITIC_SYSTEM_PROMPT


@dataclass(frozen=True)
class RuleCriticResult:
    """规则 Critic 输出。"""

    verdict: str  # "valid" | "false_positive" | "uncertain"
    confidence_adjustment: float
    reason: str


class RuleCritic:
    """
    基于法律原则的轻量规则 Critic。

    规则设计原则：
    - 不针对某份合同的具体写法，而是针对一类法律上通常不成立的风险推断；
    - 每条规则都能说出对应的法律原则（比例原则、权利保留原则、明确性原则等）；
    - 规则只能处理 high-confidence 的 obvious 情况，不确定时退回 uncertain。
    """

    def __init__(self, store_counter_examples: bool = True):
        self.store_counter_examples = store_counter_examples
        self._counter_store = get_counter_example_store() if store_counter_examples else None

    def review(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """按顺序执行规则，返回第一个非 uncertain 的确定性结论，或 uncertain。"""
        rules = [
            self._rule_detector_conclusion_reason_conflict,
            self._rule_negation_context_illegal_purpose,
            self._rule_probation_ratio_legal,
            self._rule_normal_payment_structure,
            self._rule_liquidated_damages_plus_loss_legal,
            self._rule_ip_assignment_with_consideration,
            self._rule_missing_term_is_not_risk,
            self._rule_symmetric_penalty_different_basis,
            self._rule_alternative_remedy_clause,
            self._rule_reasonable_deposit_not_penalty,
            self._rule_quality_default_not_exclusion,
            self._rule_vague_but_not_unfair,
            self._rule_interest_rate_and_penalty_not_additive,
            self._rule_loan_effective_date_not_risk,
            self._rule_loan_payment_date_mismatch_not_risk,
        ]

        for rule in rules:
            result = rule(candidate, clause_text, contract_type)
            if result.verdict != "uncertain":
                # 记录反例，用于持续学习
                if result.verdict == "false_positive" and self._counter_store:
                    self._counter_store.add(
                        pattern=self._pattern_name(rule),
                        risk_type=candidate.get("risk_type", ""),
                        rule=rule.__name__,
                        evidence_type=candidate.get("evidence_type", "semantic_inference"),
                        contract_type=contract_type,
                        reason=candidate.get("reason", ""),
                        corrected_reason=result.reason,
                        metadata={"clause_snippet": clause_text[:200]},
                    )
                return result

        return RuleCriticResult(
            verdict="uncertain",
            confidence_adjustment=0.0,
            reason="未命中任何规则 Critic 模式，转 LLM Critic 处理。",
        )

    @staticmethod
    def _pattern_name(rule) -> str:
        """从规则函数名生成可读的误判模式名称。"""
        name = rule.__name__
        mapping = {
            "_rule_detector_conclusion_reason_conflict": "结论与理由自相矛盾",
            "_rule_negation_context_illegal_purpose": "否定语境下的违法目的误判",
            "_rule_probation_ratio_legal": "试用期未结合合同期限",
            "_rule_normal_payment_structure": "正常付款结构被误判为失衡",
            "_rule_liquidated_damages_plus_loss_legal": "违约金与损失并用被误判为重复",
            "_rule_ip_assignment_with_consideration": "有对价的知识产权归属被误判为排除权利",
            "_rule_missing_term_is_not_risk": "未约定某事项被误判为风险",
            "_rule_symmetric_penalty_different_basis": "双方违约金基数不同被误判为失衡",
            "_rule_alternative_remedy_clause": "择一主张被误判为重复索赔",
            "_rule_reasonable_deposit_not_penalty": "普通押金被误判为惩罚",
            "_rule_quality_default_not_exclusion": "未约定质量标准被误判为排除质保",
            "_rule_vague_but_not_unfair": "弹性表述被误判为显失公平",
            "_rule_interest_rate_and_penalty_not_additive": "利率与逾期罚息被简单相加误判为超限",
            "_rule_loan_effective_date_not_risk": "借款合同生效日期被误判为违法",
            "_rule_loan_payment_date_mismatch_not_risk": "借款合同付息日与起息日不一致被误判为错配",
        }
        return mapping.get(name, name)

    # ---------- 规则实现 ----------

    def _rule_detector_conclusion_reason_conflict(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：风险结论与理由必须自洽。
        如果理由明确说条款合法、无风险，但等级却是 high/medium，属于系统错误，应过滤。
        """
        level = candidate.get("level", "low")
        reason = (candidate.get("reason", "") or "").lower()
        if level not in ("high", "medium"):
            return RuleCriticResult("uncertain", 0.0, "")

        legal_indicators = [
            "符合法律规定", "未发现", "不违法", "不违反", "不构成",
            "不属于", "合法", "无风险",
        ]
        # 如果理由中强烈表达合法，但等级为高/中，则判定为误报
        if any(k in reason for k in legal_indicators) and "不" in reason:
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.3,
                reason="风险结论与理由自相矛盾：理由已说明条款合法/无风险，不应评定为高/中风险。",
            )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_negation_context_illegal_purpose(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：约定“不得用于违法行为”是合法的限制性条款，不是违法目的。
        只有积极约定用于违法活动才构成违法目的原则违反。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        if "违法" not in risk_type and "强制性规定" not in risk_type:
            return RuleCriticResult("uncertain", 0.0, "")

        illegal_acts = ["赌博", "赌资", "贩毒", "走私", "洗钱", "非法集资", "非法经营"]
        for act in illegal_acts:
            if act not in clause_text:
                continue
            for match in re.finditer(re.escape(act), clause_text):
                start = max(0, match.start() - 20)
                context = clause_text[start:match.start()]
                if re.search(r"(?:不得|禁止|严禁|拒绝|不得将|不得用于).{0,5}$", context):
                    return RuleCriticResult(
                        verdict="false_positive",
                        confidence_adjustment=-0.25,
                        reason=f"条款明确禁止将{act}作为用途，属于合法约束，不构成违法目的。",
                    )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_probation_ratio_legal(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：试用期长短应结合劳动合同期限判断，不能仅看绝对月数。
        《劳动合同法》第 19 条：3 个月~1 年≤1 个月；1~3 年≤2 个月；3 年以上≤6 个月。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()
        if "试用期" not in risk_type and "试用期" not in reason:
            return RuleCriticResult("uncertain", 0.0, "")

        # 提取试用期月数（阿拉伯数字 + 中文数字）
        m_prob = re.search(r"试用期[为是]?\s*(\d+)\s*个月", clause_text)
        if m_prob:
            probation_months = int(m_prob.group(1))
        else:
            m_prob_cn = re.search(r"试用期[为是]?\s*([一二两三四五六七八九十])\s*个月", clause_text)
            cn_nums = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            probation_months = cn_nums.get(m_prob_cn.group(1)) if m_prob_cn else None

        # 提取合同期限月数（阿拉伯数字 + 中文数字）
        m_year = re.search(r"(?:合同期限|劳动合同期限|期限为)\s*(?:为|是)?\s*(\d+)\s*年", clause_text)
        m_month = re.search(r"(?:合同期限|劳动合同期限|期限为)\s*(?:为|是)?\s*(\d+)\s*个月", clause_text)
        if m_year:
            contract_months = int(m_year.group(1)) * 12
        elif m_month:
            contract_months = int(m_month.group(1))
        else:
            m_year_cn = re.search(r"(?:合同期限|劳动合同期限|期限为)\s*(?:为|是)?\s*([一二两三四五六七八九十])\s*年", clause_text)
            if m_year_cn:
                years = cn_nums.get(m_year_cn.group(1))
                contract_months = years * 12 if years else None
            else:
                contract_months = None

        if probation_months is None or contract_months is None:
            return RuleCriticResult("uncertain", 0.0, "")

        # 法定上限
        if contract_months < 3:
            max_probation = 0
        elif contract_months < 12:
            max_probation = 1
        elif contract_months < 36:
            max_probation = 2
        else:
            max_probation = 6

        if probation_months <= max_probation:
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.25,
                reason=f"合同期限 {contract_months} 个月，试用期 {probation_months} 个月，未超过法定上限（{max_probation} 个月）。",
            )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_normal_payment_structure(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：正常的商业付款结构（预付款+验收后付款、分期付款、交付后付款）
        不等于"付款与权利转移错位"或权利义务失衡。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()
        imbalance_indicators = ["权利义务失衡", "不对等", "付款", "权利转移", "错位", "显失公平"]
        if not any(k in risk_type or k in reason for k in imbalance_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        normal_payment_patterns = [
            r"预付款.*验收.*(?:付款|支付)",
            r"验收合格后.*(?:付款|支付)",
            r"交付后.*(?:付款|支付)",
            r"分期(?:付款|支付)",
            r"按月(?:支付|付款)",
            r"按阶段(?:支付|付款)",
            r"合同签订后.*(?:支付|付款).*余款",
        ]
        if any(re.search(p, clause_text) for p in normal_payment_patterns):
            # 若同时没有"款到发货不交付""付款后不履行"等异常信号，则属正常商业安排
            abnormal_signals = ["付款后.*不.*交付", "付款后.*不.*履行", "款到.*不予", "收款后.*无义务"]
            if not any(re.search(p, clause_text) for p in abnormal_signals):
                return RuleCriticResult(
                    verdict="false_positive",
                    confidence_adjustment=-0.2,
                    reason="条款属于常见的预付款/分期付款/验收后付款等商业安排，不构成付款与权利转移错位。",
                )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_liquidated_damages_plus_loss_legal(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：在中国法下，违约金与赔偿损失可以并用，只要违约金用于填补损失、不足部分再补差额。
        只有约定"固定违约金 + 全部实际损失"且无限制，才可能构成过度惩罚。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()
        if "重复" not in risk_type and "重复" not in reason and "双重" not in reason:
            return RuleCriticResult("uncertain", 0.0, "")

        # 如果合同已明确择一、就高、或差额补足，则合法
        alternative_indicators = ["择一", "就高", "选择其一", "不足部分", "差额部分", "超过部分"]
        if any(k in clause_text for k in alternative_indicators):
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.2,
                reason="条款已约定违约金与损失赔偿的适用关系（择一/差额补足），符合法律规定，不构成重复主张。",
            )

        # 如果只是简单并列"违约金和损失"，但未明确双倍赔付，通常是合法表述
        if re.search(r"违约金.*损失|损失.*违约金", clause_text):
            if not re.search(r"同时.*全部|既.*又.*全部|一并.*全部", clause_text):
                return RuleCriticResult(
                    verdict="false_positive",
                    confidence_adjustment=-0.15,
                    reason="违约金与损失赔偿并列约定在中国法下可并用，未约定无限制双重赔付，不构成重复主张。",
                )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_ip_assignment_with_consideration(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：委托/合作开发中约定知识产权归委托方/甲方，只要对方获得合同对价，
        不等于排除对方主要权利或显失公平。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()
        if "排除" not in risk_type and "权利" not in reason and "失衡" not in reason:
            return RuleCriticResult("uncertain", 0.0, "")

        ip_indicators = ["知识产权", "著作权", "专利", "技术成果", "成果"]
        if not any(k in clause_text for k in ip_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 若条款只是约定成果归某方，且合同存在对价/报酬表述，则属于正常商业安排
        if re.search(r"(?:归|属于).{0,10}(?:甲方|乙方|委托方|受托方)", clause_text):
            consideration_indicators = ["报酬", "费用", "价款", "对价", "支付", "合同金额", "合同总价"]
            # 在当前 chunk 或候选理由中提到对价，则认为有对价支撑
            context = clause_text + reason
            if any(k in context for k in consideration_indicators):
                return RuleCriticResult(
                    verdict="false_positive",
                    confidence_adjustment=-0.2,
                    reason="条款约定知识产权归属属于有偿交易安排，相对方已获得合同对价，不构成排除主要权利。",
                )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_missing_term_is_not_risk(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：合同未约定某事项 ≠ 法律风险。
        民法典等法律已提供默认规则，"缺失"本身只有在导致履行不能或显失公平时才构成风险。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        missing_indicators = [
            "未约定", "缺少", "缺失", "没有约定", "未明确", "未规定",
            "未载明", "无约定", "无明确",
        ]
        if not any(k in risk_type or k in reason for k in missing_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 如果条款本身只是陈述未约定，而没有任何一方被排除权利或加重义务，则属于误报
        exclusion_indicators = ["不得", "无权", "概不", "放弃", "排除", "免除"]
        if not any(k in clause_text for k in exclusion_indicators):
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.25,
                reason="风险理由为'未约定/缺少某事项'，但合同未约定某事项不等于法律风险，法律已提供默认规则。",
            )

        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_symmetric_penalty_different_basis(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：双方违约责任可以约定不同计算基数，只要比例本身不明显失衡，不当然构成权利义务失衡。
        比例原则关注的是违约金数额是否显著过高，而非双方计算基数是否完全一致。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        imbalance_indicators = ["权利义务失衡", "不对等", "不公平", "偏向", "显失公平"]
        if not any(k in risk_type or k in reason for k in imbalance_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 寻找双方违约金比例：通常表现为 "甲方...X%...乙方...Y%"
        # 如果比例相同或接近，仅基数不同（如逾期金额 vs 合同总金额），通常不构成失衡
        rates = re.findall(r"(\d+(?:\.\d+)?)\s*[％%]", clause_text)
        if len(rates) >= 2:
            try:
                nums = [float(r) for r in rates]
                # 所有违约金比例相同或相近（差异 < 1 个百分点）
                if max(nums) - min(nums) < 1.0:
                    return RuleCriticResult(
                        verdict="false_positive",
                        confidence_adjustment=-0.2,
                        reason="双方违约金比例相同或接近，仅计算基数不同，不构成权利义务失衡。",
                    )
            except ValueError:
                pass

        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_alternative_remedy_clause(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：违约金与赔偿损失并列约定时，若合同已明确"择一主张"或"就高不就低"，
        则不属于重复主张或双重惩罚。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        double_recovery_indicators = [
            "重复主张", "双重", "既...又", "同时主张", "违约金和.*损失",
            "违约金与.*损失",
        ]
        if not any(k in risk_type or k in reason for k in double_recovery_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        alternative_indicators = [
            "择一", "就高", "选择其一", "只能主张其一", "不可同时主张",
            "违约金或", "或赔偿损失",
        ]
        if any(k in clause_text for k in alternative_indicators):
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.2,
                reason="条款已约定违约金与损失赔偿择一主张，不构成重复索赔。",
            )

        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_reasonable_deposit_not_penalty(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：押金/定金作为履约担保是正常商业安排，只有"一概不退""无条件没收"等
        明显剥夺对方权利的表述才构成风险。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        deposit_indicators = ["押金", "定金", "保证金"]
        if not any(k in risk_type or k in reason or k in clause_text for k in deposit_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 如果存在任意没收/概不退还表述，属于真风险，不确定让 LLM 判断
        if re.search(r"一概不.*退还|概不退还|全部没收|无条件没收|一律不.*退还|押金.*不.*退还", clause_text):
            return RuleCriticResult("uncertain", 0.0, "")

        # 普通押金条款，无绝对化没收表述
        return RuleCriticResult(
            verdict="false_positive",
            confidence_adjustment=-0.2,
            reason="条款仅约定押金/保证金作为履约担保，未约定一概不退或无条件没收，不构成显失公平。",
        )

    def _rule_quality_default_not_exclusion(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：未约定质量标准时，民法典已规定标的物应符合通常用途/国家标准；
        只有明确排除质量担保义务才是风险。
        """
        reason = (candidate.get("reason", "") or "").lower()
        risk_type = (candidate.get("risk_type", "") or "").lower()

        quality_indicators = ["质量标准", "验收", "检验", "质保", "质量保证"]
        if not any(k in risk_type or k in reason for k in quality_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 如果条款明确说"不提供质保""概不负责"等，是真风险
        exclusion_indicators = ["概不负责", "概不提供", "不提供.*质保", "免除.*质保", "排除"]
        if any(k in clause_text for k in exclusion_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 如果只是"未约定"质量标准，属于误报
        missing_indicators = ["未约定", "缺少", "缺失", "没有", "未明确"]
        if any(k in reason for k in missing_indicators):
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.2,
                reason="未约定质量标准不等于排除法定质量担保义务，民法典已提供默认规则。",
            )

        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_vague_but_not_unfair(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：约定不够详细、使用"合理""适当"等弹性措辞，不等于显失公平；
        必须结合是否导致一方权利被实质性剥夺来判断。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        vague_indicators = ["约定不明", "不够详细", "过于模糊", "不够明确", "不明确"]
        if not any(k in risk_type or k in reason for k in vague_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 如果同时出现排除权利、任意单方、显著过高金额等信号，则不是误报
        unfair_signals = ["不得", "无权", "概不", "放弃", "随时", "任意", "显著高于", "明显超过"]
        if any(k in clause_text for k in unfair_signals):
            return RuleCriticResult("uncertain", 0.0, "")

        return RuleCriticResult(
            verdict="false_positive",
            confidence_adjustment=-0.15,
            reason="条款仅约定较为原则或弹性，但未排除任何法定权利或造成显失公平，不构成法律风险。",
        )

    def _rule_interest_rate_and_penalty_not_additive(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：借款合同的正常年利率与逾期罚息不得简单相加作为整体利率判断是否超过法定上限。
        逾期罚息仅针对逾期本金，正常利息针对全部本金；二者适用对象和期间不同，直接相加会虚增融资成本。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        if "利率" not in risk_type and "利率" not in reason:
            return RuleCriticResult("uncertain", 0.0, "")

        # 必须同时存在正常利率与逾期/罚息表述，且理由中使用了相加/合计逻辑
        has_normal_rate = re.search(r"年利率|借款利率|利息", clause_text) is not None
        has_penalty = re.search(r"逾期|罚息|违约金|日万分之", clause_text) is not None
        additive_reason = any(k in reason for k in ["合计", "相加", "总和", "总计", "两者", "同时存在"])

        if has_normal_rate and has_penalty and additive_reason:
            return RuleCriticResult(
                verdict="false_positive",
                confidence_adjustment=-0.25,
                reason="正常年利率与逾期罚息适用对象和期间不同，不得简单相加作为整体利率判断；该条款未明显超过法定上限。",
            )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_loan_effective_date_not_risk(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：自然人借款合同约定'自双方签字之日起生效'是常见表述。
        《民法典》第679条规范的是合同成立时间（实际提供借款时成立），当事人仍可约定合同生效条件；
        只有条款明确否定'实际放款'作为成立要件，或约定签字后未放款即需付息，才可能构成风险。
        """
        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()

        if contract_type != "借款合同":
            return RuleCriticResult("uncertain", 0.0, "")
        if "生效" not in risk_type and "生效" not in reason:
            return RuleCriticResult("uncertain", 0.0, "")

        # 仅因'签字之日起生效'而 flagged，且无明确否定实际放款或提前计息表述
        if "签字" in clause_text and "之日起生效" in clause_text:
            exclusion_indicators = ["无论是否放款", "未放款也生效", "签字即应支付利息", "自签字日起计息"]
            if not any(k in clause_text for k in exclusion_indicators):
                return RuleCriticResult(
                    verdict="false_positive",
                    confidence_adjustment=-0.2,
                    reason="自然人借款合同约定'自签字之日起生效'属常见表述，未明确否定实际放款要件或提前计息，不构成违法。",
                )
        return RuleCriticResult("uncertain", 0.0, "")

    def _rule_loan_payment_date_mismatch_not_risk(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
    ) -> RuleCriticResult:
        """
        原则：借款合同每月固定付息日与借款起始日不一致（如25日起借、每月24日付息）
        属于正常日历安排，不等于期限与义务错配。
        只有付息周期明显混乱或导致多期/首期利息缺失，才可能构成风险。
        """
        if contract_type != "借款合同":
            return RuleCriticResult("uncertain", 0.0, "")

        risk_type = (candidate.get("risk_type", "") or "").lower()
        reason = (candidate.get("reason", "") or "").lower()
        mismatch_indicators = ["错配", "不一致", "错位", "期限", "支付日", "起算日", "起息日"]
        if not any(k in risk_type or k in reason for k in mismatch_indicators):
            return RuleCriticResult("uncertain", 0.0, "")

        # 必须同时存在借款起始/放款日表述与固定付息日表述
        has_start_date = re.search(
            r"(?:自|起)\s*(?:20\d{2}|\d{4})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
            r"实际放款日|实际划款|起息日|借款期限自",
            clause_text,
        ) is not None
        has_payment_date = re.search(r"每月\s*\d{1,2}\s*(?:日|号)\s*前|按月\s*(?:结算|支付|付息)", clause_text) is not None

        if has_start_date and has_payment_date:
            # 若存在真正的周期混乱信号，则不排除风险
            abnormal_signals = [
                "多期", "缺失", "不计息", "不支付利息", "首期不付", "末期不付",
                "首个付息日", "末个付息日", "利息免除", "免息",
            ]
            if not any(k in clause_text for k in abnormal_signals):
                return RuleCriticResult(
                    verdict="false_positive",
                    confidence_adjustment=-0.25,
                    reason="借款合同约定每月固定付息日与借款起始日不一致属常见日历安排，不等于期限与义务错配。",
                )
        return RuleCriticResult("uncertain", 0.0, "")


class CriticAgent(BaseAgent):
    """
    CriticAgent：对 RiskReviewAgent 提出的候选风险做二次校验。

    设计目标：
    - 先用 RuleCritic 处理 obvious 误报/成立情形，减少 LLM 调用；
    - LLM Critic 只处理边界案例；
    - 不替代 RiskReviewAgent 的审查，只作为守门员（gatekeeper）。
    """

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="CriticAgent",
            system_prompt=CRITIC_SYSTEM_PROMPT,
            tools=tools,
            max_turns=1,
        )
        # Critic 统一读取环境配置中的模型
        from app.core.config import get_settings
        from app.llm import LLMClient
        self.set_llm_client(LLMClient(model=get_settings().LLM_MODEL))

        # 规则快速路径
        self.rule_critic = RuleCritic()

    async def run(
        self,
        session_graph: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        满足 BaseAgent 抽象方法要求。
        CriticAgent 实际通过 review_finding 被调用，run 方法不直接参与 Coordinator 管线。
        """
        return {"output": {}, "findings": [], "logs": self.logs}

    async def review_finding(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
        law_context: str,
    ) -> dict[str, Any]:
        """
        对单个候选风险进行复核。

        流程：
        1. RuleCritic 快速路径；
        2. 规则无法确定时，调用 LLM Critic。
        """
        # 1. 规则快速路径
        rule_result = self.rule_critic.review(candidate, clause_text, contract_type)
        if rule_result.verdict in ("valid", "false_positive"):
            self.logs.append({
                "action": "critic_review",
                "verdict": rule_result.verdict,
                "adjustment": rule_result.confidence_adjustment,
                "reason": rule_result.reason,
                "risk_type": candidate.get("risk_type"),
                "source": "rule",
            })
            return {
                "verdict": rule_result.verdict,
                "confidence_adjustment": rule_result.confidence_adjustment,
                "reason": rule_result.reason,
                "source": "rule",
            }

        # 2. LLM 模糊路径
        return await self._llm_review(candidate, clause_text, contract_type, law_context)

    async def _llm_review(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
        law_context: str,
    ) -> dict[str, Any]:
        """调用 LLM 对边界案例进行复核。"""
        prompt = (
            f"合同类型：{contract_type}\n\n"
            f"本次审查可参考的法律依据：\n{law_context}\n\n"
            f"待复核条款原文：\n{clause_text}\n\n"
            f"审查员提出的风险结论：\n"
            f"- 风险类型：{candidate.get('risk_type', '未分类')}\n"
            f"- 风险等级：{candidate.get('level', 'low')}\n"
            f"- 置信度：{candidate.get('confidence', 0.5)}\n"
            f"- 风险理由：{candidate.get('reason', '')}\n"
            f"- 修改建议：{candidate.get('suggestion', '')}\n\n"
            "请复核上述风险结论。请只输出 JSON 对象："
            '{"verdict": "valid/false_positive/uncertain", "confidence_adjustment": -0.15, "reason": "..."}'
        )

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=512,
            )
        except Exception as e:
            self.logs.append({"action": "review_finding", "error": str(e)})
            # 出问题时保守处理：不确定，不调整置信度
            return {
                "verdict": "uncertain",
                "confidence_adjustment": 0.0,
                "reason": f"Critic 调用失败: {e}",
                "source": "llm",
            }

        parsed = self._parse_json_output(response)
        if isinstance(parsed, dict) and "verdict" in parsed:
            return {
                "verdict": parsed.get("verdict", "uncertain"),
                "confidence_adjustment": float(parsed.get("confidence_adjustment", 0.0)),
                "reason": parsed.get("reason", ""),
                "source": "llm",
            }

        self.logs.append({
            "action": "review_finding",
            "warning": "无法解析 Critic 输出",
            "raw": (response or "")[:300],
        })
        return {
            "verdict": "uncertain",
            "confidence_adjustment": 0.0,
            "reason": "Critic 输出无法解析",
            "source": "llm",
        }
