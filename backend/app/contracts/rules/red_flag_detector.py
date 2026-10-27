"""
文件：app/contracts/rules/red_flag_detector.py
作用：原则驱动的红线检测层。

设计目标：
1. 从"案例背书式规则"转向"法律原则理解式"检测；
2. 用一组跨合同类型的通用法律原则作为检测本体；
3. 用语义向量召回可能触犯的原则候选；
4. 用轻量 LLM 将抽象原则实例化到具体条款；
5. 对存在明确数值/关键词红线的原则保留快速检查路径，确保 recall；
6. Detector 只负责"发现嫌疑"和"给出理由"，最终是否写入风险仍由上游 Agent 决定。

判定结果：
{
    "matched": True,
    "pattern_id": "原则ID",
    "risk_type": "风险类型",
    "level": "high/medium/low",
    "confidence": 0.95,
    "reason": "命中理由",
    "suggestion": "修改建议",
    "matched_text": "命中的原文片段",
    "principle": "原则名称",
    "legal_basis": "法律依据"
}
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class LegalPrinciple:
    """单条通用法律原则。"""

    id: str
    name: str
    description: str
    legal_basis: str
    applicable_contract_types: list[str]
    risk_type: str
    default_level: str
    decision_prompt: str
    violation_examples: list[str]
    non_violation_examples: list[str]
    violation_centroid: list[float] | None = None
    non_violation_centroid: list[float] | None = None
    quick_checks: dict[str, Any] = field(default_factory=dict)


class PrincipleBasedDetector:
    """
    基于法律原则的红线检测器。

    核心流程：
    1. 加载通用法律原则本体（legal_principles.json）；
    2. 预计算每条原则的 violation/non-violation 语义中心；
    3. 对待审条款做快速检查（数值型红线，如违约金比例、利率、试用期等）；
    4. 对待审条款做语义编码，计算与原则语义中心的相似度；
    5. 召回 violation 显著高于 non-violation 的原则候选；
    6. 用轻量 LLM 对每个候选原则做实例化判断；
    7. 合并快速检查结果与 LLM 实例化结果，返回结构化风险发现。
    """

    CONFIG_PATH: Path = (
        Path(__file__).resolve().parent / "config" / "legal_principles.json"
    )

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else self.CONFIG_PATH
        self.principles: list[LegalPrinciple] = []
        self.settings: dict[str, Any] = {}
        self._llm_client: Any | None = None
        self._embedding_client: Any | None = None

        self._load_config()
        self._precompute_centroids()
        self._init_quick_check_patterns()

    # ---------- 配置加载 ----------
    def _load_config(self) -> None:
        """从 JSON 文件加载原则本体。"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"法律原则配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.settings = data.get("settings", {})
        for item in data.get("principles", []):
            self.principles.append(
                LegalPrinciple(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    legal_basis=item.get("legal_basis", ""),
                    applicable_contract_types=item.get(
                        "applicable_contract_types", ["通用"]
                    ),
                    risk_type=item["risk_type"],
                    default_level=item.get("default_level", "medium"),
                    decision_prompt=item["decision_prompt"],
                    violation_examples=item.get("violation_examples", []),
                    non_violation_examples=item.get("non_violation_examples", []),
                    quick_checks=item.get("quick_checks", {}),
                )
            )

    # ---------- 语义中心预计算 ----------
    def _precompute_centroids(self) -> None:
        """预计算每条原则的 violation / non-violation 语义中心。"""
        from app.llm.embeddings import get_embedding_client

        self._embedding_client = get_embedding_client()

        for principle in self.principles:
            if principle.violation_examples:
                vectors = self._embedding_client.encode_batch(
                    principle.violation_examples
                )
                principle.violation_centroid = self._compute_centroid(vectors)

            if principle.non_violation_examples:
                vectors = self._embedding_client.encode_batch(
                    principle.non_violation_examples
                )
                principle.non_violation_centroid = self._compute_centroid(vectors)

    @staticmethod
    def _compute_centroid(vectors: list[list[float]]) -> list[float]:
        """计算一组向量的均值中心。"""
        if not vectors:
            return []
        arr = np.array(vectors, dtype=np.float32)
        centroid = arr.mean(axis=0)
        # 归一化，便于余弦相似度计算
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid.astype(np.float32).tolist()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        if not a or not b:
            return 0.0
        return float(np.dot(a, b))

    # ---------- 快速检查模式初始化 ----------
    def _init_quick_check_patterns(self) -> None:
        """初始化数值型和关键词型快速检查所需的正则与阈值。"""
        self._percent_re = re.compile(r"(\d+(?:\.\d+)?)\s*[％%]")
        self._permille_re = re.compile(r"千分之(\d+(?:\.\d+)?)")
        self._daily_rate_re = re.compile(
            r"每逾期一日|每日|按日|日息|日利率|日违约金|日罚息|滞纳金.*日|每延迟一天|每逾期一天"
        )
        self._year_rate_re = re.compile(r"年利率|年化|年息|借款利率")
        self._money_cut_re = re.compile(r"预先扣除|砍头息|先扣利息|实际到手|实付")

    # ---------- 公共入口 ----------
    async def detect(
        self, clause_text: str, contract_type: str = "通用"
    ) -> list[dict[str, Any]]:
        """
        对单条条款进行原则驱动的红线检测，返回命中的风险列表。
        """
        if not clause_text or len(clause_text.strip()) < 5:
            return []

        findings: list[dict[str, Any]] = []
        text = clause_text

        # 1. 快速检查：明确数值/关键词红线，保证 recall
        quick_findings = self._run_quick_checks(text, contract_type)
        findings.extend(quick_findings)

        # 2. 语义召回 + LLM 实例化：处理原则层面的泛化理解
        semantic_findings = await self._run_semantic_checks(text, contract_type)

        # 3. 合并去重：同一原则只保留置信度最高的结果
        for finding in semantic_findings:
            if not any(
                f.get("pattern_id") == finding.get("pattern_id") for f in findings
            ):
                findings.append(finding)

        return findings

    async def detect_highest(
        self, clause_text: str, contract_type: str = "通用"
    ) -> dict[str, Any] | None:
        """返回单条条款中等级最高、置信度最高的命中结果。

        排序规则：
        1. 风险等级（high > medium > low）；
        2. 来源优先级（quick_check > semantic，明确规则优先于 LLM 推断）；
        3. 置信度。
        """
        findings = await self.detect(clause_text, contract_type)
        if not findings:
            return None
        level_order = {"high": 3, "medium": 2, "low": 1}
        source_order = {"quick_check": 2, "semantic": 1}
        findings.sort(
            key=lambda x: (
                level_order.get(x.get("level", "low"), 0),
                source_order.get(x.get("source", "semantic"), 0),
                x.get("confidence", 0),
            ),
            reverse=True,
        )
        return findings[0]

    def detect_sync(
        self, clause_text: str, contract_type: str = "通用"
    ) -> list[dict[str, Any]]:
        """同步入口，便于非异步上下文调用。"""
        try:
            return asyncio.run(self.detect(clause_text, contract_type))
        except RuntimeError:
            # 已处于事件循环中（如 pytest-asyncio）
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.detect(clause_text, contract_type))

    def detect_highest_sync(
        self, clause_text: str, contract_type: str = "通用"
    ) -> dict[str, Any] | None:
        """同步入口，返回最高等级命中结果。"""
        try:
            return asyncio.run(self.detect_highest(clause_text, contract_type))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.detect_highest(clause_text, contract_type))

    # ---------- 快速检查 ----------
    def _run_quick_checks(
        self, text: str, contract_type: str
    ) -> list[dict[str, Any]]:
        """运行所有启用了快速检查的原则。"""
        findings: list[dict[str, Any]] = []

        for principle in self.principles:
            if not principle.quick_checks.get("enabled"):
                continue
            if not self._is_applicable(principle, contract_type):
                continue

            check_type = principle.quick_checks.get("type")
            if check_type == "numeric_penalty":
                if result := self._check_numeric_penalty(text, principle):
                    findings.append(result)
            elif check_type == "right_exclusion":
                if result := self._check_right_exclusion(text, principle):
                    findings.append(result)
            elif check_type == "good_faith_fairness":
                if result := self._check_good_faith_fairness(text, principle):
                    findings.append(result)
            elif check_type == "minimum_guarantee":
                if result := self._check_minimum_guarantee(text, principle):
                    findings.append(result)
            elif check_type == "illegal_purpose":
                if result := self._check_illegal_purpose(text, principle):
                    findings.append(result)
            elif check_type == "waive_liability":
                if result := self._check_waive_liability(text, principle):
                    findings.append(result)

        return findings

    def _is_applicable(self, principle: LegalPrinciple, contract_type: str) -> bool:
        """判断原则是否适用于当前合同类型。"""
        types = principle.applicable_contract_types
        return "通用" in types or contract_type in types

    def _make_result(
        self,
        principle: LegalPrinciple,
        reason: str,
        level: str | None = None,
        confidence: float | None = None,
        matched_text: str = "",
        source: str = "quick_check",
        evidence_type: str = "keyword_match",
    ) -> dict[str, Any]:
        """构造标准化输出。"""
        return {
            "matched": True,
            "pattern_id": principle.id,
            "risk_type": principle.risk_type,
            "level": level or principle.default_level,
            "confidence": confidence
            or self.settings.get("quick_check_confidence", 0.95),
            "reason": reason,
            "suggestion": self._suggestion_for_principle(principle),
            "matched_text": matched_text[:300],
            "principle": principle.name,
            "legal_basis": principle.legal_basis,
            "source": source,
            "evidence_type": evidence_type,
        }

    def _suggestion_for_principle(self, principle: LegalPrinciple) -> str:
        """根据原则生成通用修改建议。"""
        suggestions = {
            "proportionality": "违约金、赔偿金、滞纳金等应与可能损失相当，日违约金建议不超过千分之一，一次性违约金建议不超过合同标的30%。",
            "right_preservation": "不得通过格式条款排除对方的法定检验、验收、质量异议、退货换货、解除、索赔等权利。",
            "good_faith_fairness": "合同重大变更、解除、价格调整应经双方协商一致，避免一方任意行使单方权利。",
            "minimum_guarantee": "试用期、工资、社保、租赁期限等约定应符合法律规定的最低保障标准。",
            "disclosure": "转让方/卖方应如实披露标的物瑕疵、权利受限、质押、抵押、债务负担等影响对方决策的重大信息。",
            "illegal_purpose": "合同标的、用途、交易方式应符合法律强制性规定，不得约定砍头息、复利、流质流押或违法用途。",
            "clarity": "关键义务、质量标准、计算方式、履行期限应明确具体，避免因约定不明导致履行争议。",
            "non_waivable_liability": "不得通过格式条款免除故意或重大过失责任，以及法定的质量担保、安全保障、信息披露义务。",
        }
        return suggestions.get(principle.id, "请根据相关法律规定调整该条款，使其公平合理。")

    # ---------- 具体快速检查实现 ----------
    def _extract_penalty_values(self, text: str) -> list[tuple[float, int, int]]:
        """从文本中提取所有百分/千分比例数值，返回 [(百分比值, start, end), ...]。

        例如：
        - "5%" -> (5.0, ...)
        - "千分之五" -> (0.5, ...)
        - "千分之10" -> (1.0, ...)
        """
        values: list[tuple[float, int, int]] = []
        # 阿拉伯数字 + %
        for match in self._percent_re.finditer(text):
            try:
                values.append((float(match.group(1)), match.start(), match.end()))
            except ValueError:
                continue
        # 阿拉伯数字 + 千分之
        for match in self._permille_re.finditer(text):
            try:
                values.append((float(match.group(1)) / 10.0, match.start(), match.end()))
            except ValueError:
                continue
        # 中文数字 + 千分之（如千分之五、千分之十五）
        cn_permille_re = re.compile(r"千分之([一二两三四五六七八九十百千万]+)")
        for match in cn_permille_re.finditer(text):
            num = self._parse_chinese_number(match.group(1))
            if num is not None:
                values.append((num / 10.0, match.start(), match.end()))
        return values

    def _check_numeric_penalty(
        self, text: str, principle: LegalPrinciple
    ) -> dict[str, Any] | None:
        """比例原则的数值快速检查：日违约金 > 0.1%、一次性违约金 > 30%、年利率 > 12%。"""
        findings: list[dict[str, Any]] = []
        penalty_values = self._extract_penalty_values(text)

        # 日违约金 / 逾期利率
        if self._daily_rate_re.search(text):
            for value, _, _ in penalty_values:
                if value > 0.1:
                    findings.append(
                        self._make_result(
                            principle,
                            f"条款约定每日违约金/罚息为 {value}%，超过主债权千分之一（0.1%/日）的红线。",
                            level="high",
                            matched_text=text,
                            evidence_type="numeric_violation",
                        )
                    )
                    break

        # 一次性违约金
        if "违约金" in text:
            for value, start, _ in penalty_values:
                before = text[max(0, start - 25) : start]
                if any(
                    k in before
                    for k in ("合同总金额", "总金额", "标的额", "合同价款", "总价款")
                ):
                    if value > 30:
                        findings.append(
                            self._make_result(
                                principle,
                                f"条款约定一次性违约金为合同总金额的 {value}%，显著高于通常合理范围。",
                                level="high",
                                matched_text=text,
                                evidence_type="numeric_violation",
                            )
                        )
                        break

        # 借款年利率
        if self._year_rate_re.search(text) or "利息" in text:
            for value, _, _ in penalty_values:
                if value > 12:
                    findings.append(
                        self._make_result(
                            principle,
                            f"条款约定借款年利率为 {value}%，超过一年期 LPR 四倍的司法保护上限近似值。",
                            level="high",
                            matched_text=text,
                            evidence_type="numeric_violation",
                        )
                    )
                    break

        # 返回最高级别结果
        if not findings:
            return None
        return max(findings, key=lambda x: (x["level"] == "high", x["confidence"]))

    def _check_right_exclusion(
        self, text: str, principle: LegalPrinciple
    ) -> dict[str, Any] | None:
        """权利保留原则的快速检查：排除检验、验收、异议、退换货、安宁使用权等权利。"""
        patterns = [
            (r"不得开箱检验|不得检验|不得验收|不得提出.*异议|放弃.*检验|放弃.*验收|无权.*检验|无权.*验收", "条款明确排除对方对标的物进行检验、验收或提出质量异议的法定权利。"),
            (r"概不退换|概不退货|概不换货|一经售出.*不退", "条款通过'概不退换'等表述绝对化排除买受人的法定救济权利。"),
            (r"无权.*解除|放弃.*解除|不得.*解除", "条款排除对方依法享有的合同解除权。"),
        ]
        for pattern, reason in patterns:
            if re.search(pattern, text):
                return self._make_result(
                    principle,
                    reason,
                    level="high",
                    matched_text=text,
                    evidence_type="statutory_exclusion",
                )

        # 出租方任意进入租赁房屋，侵害承租人安宁使用权
        if re.search(
            r"(?:甲方|出租方|房东).{0,15}(?:有权|可以).{0,10}随时.{0,10}进入.{0,20}(?:房屋|租赁物|房间).{0,30}(?:无需|不须|不必).{0,10}(?:事先|提前).{0,10}通知",
            text,
        ):
            return self._make_result(
                principle,
                "条款赋予出租方随时进入租赁房屋且无需事先通知的权利，侵害承租人的安宁居住/使用权。",
                level="high",
                confidence=0.9,
                matched_text=text,
                evidence_type="statutory_exclusion",
            )

        return None

    def _check_good_faith_fairness(
        self, text: str, principle: LegalPrinciple
    ) -> dict[str, Any] | None:
        """诚信公平原则的快速检查：任意单方变更/解除/调整、自动续期未通知、合作成果单方独占。"""
        # 任意单方变更/调整
        patterns = [
            (r"甲方有权随时.*变更|乙?方有权随时.*变更|任意.*变更|单方.*变更|甲?方有权随时.*调整|任意.*调整", "条款赋予一方任意单方变更或调整合同的权利，权利义务失衡。"),
            (r"甲方有权随时.*解除|乙?方有权随时.*解除|任意.*解除|单方.*解除|甲?方有权随时.*涨租|任意.*涨租", "条款赋予一方任意单方解除或重大变更合同的权利，权利义务失衡。"),
        ]
        for pattern, reason in patterns:
            if re.search(pattern, text):
                return self._make_result(
                    principle,
                    reason,
                    level="medium",
                    confidence=0.8,
                    matched_text=text,
                )

        # 自动续期未通知
        if re.search(r"自动续期|自动续签|自动延长|到期自动", text):
            if not re.search(r"提前.*通知|书面通知|拒绝续期|不再续约|期满前.*通知", text):
                return self._make_result(
                    principle,
                    "条款约定自动续期但未约定提前通知义务和拒绝续期权利，可能构成霸王条款。",
                    level="medium",
                    confidence=0.75,
                    matched_text=text,
                )

        # 合作/共同开发的成果单方独占
        if re.search(
            r"(?:合作|共同|联合).{0,15}(?:开发|研制|创作|研发).{0,20}(?:知识产权|成果|著作权|专利|技术成果).{0,15}(?:全部|均|统通|一律).{0,10}归.{0,10}(?:甲方|乙方|一方|丙方)",
            text,
        ):
            return self._make_result(
                principle,
                "条款将合作/共同开发的知识产权单方归某一方所有，违反公平原则和共有权利约定。",
                level="medium",
                confidence=0.8,
                matched_text=text,
            )

        return None

    def _extract_contract_duration_months(self, text: str) -> int | None:
        """从合同文本中提取合同期限（月），支持常见表述。"""
        # 阿拉伯数字：X 年 / X 个月
        m_year = re.search(r"(?:合同期限|劳动合同期限|合同期为|期限为)\s*(?:为|是)?\s*(\d+)\s*年", text)
        if m_year:
            return int(m_year.group(1)) * 12
        m_month = re.search(r"(?:合同期限|劳动合同期限|合同期为|期限为)\s*(?:为|是)?\s*(\d+)\s*个月", text)
        if m_month:
            return int(m_month.group(1))
        # 中文数字：三年 / 六个月 等
        m_cn_year = re.search(r"(?:合同期限|劳动合同期限|合同期为|期限为)\s*(?:为|是)?\s*([一二两三四五六七八九十百千万]+)\s*年", text)
        if m_cn_year:
            years = self._parse_chinese_number(m_cn_year.group(1))
            if years:
                return years * 12
        m_cn_month = re.search(r"(?:合同期限|劳动合同期限|合同期为|期限为)\s*(?:为|是)?\s*([一二两三四五六七八九十百千万]+)\s*个月", text)
        if m_cn_month:
            months = self._parse_chinese_number(m_cn_month.group(1))
            if months:
                return months
        return None

    def _check_probation_legal(self, probation_months: int, contract_months: int | None) -> tuple[bool, str]:
        """
        根据《劳动合同法》第 19 条判断试用期是否合法。
        返回 (是否违法, 理由)。
        """
        # 绝对上限：任何劳动合同试用期不得超过 6 个月
        if probation_months > 6:
            return True, f"试用期 {probation_months} 个月，超过劳动合同法规定的六个月绝对上限。"

        if contract_months is None:
            # 无法判断合同期限时，保守处理：大于 6 个月才报，否则不判断
            return False, ""

        # 劳动合同期限 3 个月以下：不得约定试用期
        if contract_months < 3 and probation_months > 0:
            return True, "合同期限不足三个月，不得约定试用期。"

        # 3 个月 ~ 1 年：试用期不得超过 1 个月
        if contract_months < 12:
            if probation_months > 1:
                return True, f"合同期限 {contract_months} 个月，试用期不得超过一个月。"
            return False, ""

        # 1 年 ~ 3 年：试用期不得超过 2 个月
        if contract_months < 36:
            if probation_months > 2:
                return True, f"合同期限 {contract_months} 个月，试用期不得超过二个月。"
            return False, ""

        # 3 年以上或无固定期限：试用期不得超过 6 个月（已在前面的绝对上限中处理）
        return False, ""

    def _check_minimum_guarantee(
        self, text: str, principle: LegalPrinciple
    ) -> dict[str, Any] | None:
        """最低保障原则的快速检查：试用期、社保、租赁期限。"""
        # 试用期：必须结合合同期限判断
        if "试用期" in text:
            contract_months = self._extract_contract_duration_months(text)
            match = re.search(r"试用期[为是]?\s*(\d+|[一二两三四五六七八九十]+)\s*个月", text)
            if match:
                num_str = match.group(1)
                if num_str.isdigit():
                    probation_months = int(num_str)
                else:
                    probation_months = self._parse_chinese_number(num_str)

                if probation_months is not None:
                    is_illegal, reason = self._check_probation_legal(probation_months, contract_months)
                    if is_illegal:
                        return self._make_result(
                            principle,
                            reason,
                            level="high",
                            matched_text=text,
                            evidence_type="statutory_violation",
                        )

            # 试用期工资
            match = re.search(r"试用期工资.*?(\d+(?:\.\d+)?)\s*[％%]", text)
            if match:
                try:
                    value = float(match.group(1))
                except ValueError:
                    value = None
                if value is not None and value < 80:
                    return self._make_result(
                        principle,
                        f"条款约定试用期工资为转正工资的 {value}%，低于劳动合同法规定的80%下限。",
                        level="high",
                        matched_text=text,
                        evidence_type="statutory_violation",
                    )

        # 社保
        if re.search(r"不.*缴纳.*社保|不.*缴纳.*社会保险|放弃.*社保|不承担.*社保|社保.*乙方.*承担|不为.*缴纳.*社会保险", text):
            return self._make_result(
                principle,
                "条款约定用人单位不缴纳社会保险费，违反劳动法强制性规定。",
                level="high",
                matched_text=text,
                evidence_type="statutory_violation",
            )

        # 租赁期限（支持阿拉伯数字和中文数字，允许中间有"为/是"等连接词）
        if re.search(r"租赁期限|租期|租赁期", text):
            match = re.search(r"租赁期限\s*(?:为|是)?\s*(\d+)\s*年", text)
            if match:
                years = int(match.group(1))
                if years > 20:
                    return self._make_result(
                        principle,
                        f"条款约定租赁期限为 {years} 年，超过民法典规定的二十年上限，超过部分无效。",
                        level="high",
                        matched_text=text,
                        evidence_type="statutory_violation",
                    )

            # 中文数字，如二十五年
            match = re.search(r"租赁期限\s*(?:为|是)?\s*([一二两三四五六七八九十百千万]+)\s*年", text)
            if match:
                years = self._parse_chinese_number(match.group(1))
                if years and years > 20:
                    return self._make_result(
                        principle,
                        f"条款约定租赁期限为 {match.group(1)} 年，超过民法典规定的二十年上限，超过部分无效。",
                        level="high",
                        matched_text=text,
                        evidence_type="statutory_violation",
                    )

        return None

    def _has_positive_illegal_purpose(self, text: str, keyword: str) -> bool:
        """
        判断关键词是否表示“积极约定用于违法行为”。
        如果关键词前面出现“不得、禁止、拒绝、不得将、不得用于”等否定/禁止表述，
        则是合法的限制性约定，不构成违法目的。
        """
        # 先找到关键词位置
        for match in re.finditer(re.escape(keyword), text):
            start = max(0, match.start() - 20)
            context = text[start:match.start()]
            # 否定/禁止表述
            negation_patterns = [
                r"不得\s*用于?\s*$",
                r"不得\s*将\s*$",
                r"禁止\s*用于?\s*$",
                r"禁止\s*将\s*$",
                r"拒绝\s*用于?\s*$",
                r"严禁\s*用于?\s*$",
                r"严禁\s*将\s*$",
                r"不得.*(?:使用|用作|作为)\s*$",
            ]
            if any(re.search(p, context) for p in negation_patterns):
                return False
        return True

    def _check_illegal_purpose(
        self, text: str, principle: LegalPrinciple
    ) -> dict[str, Any] | None:
        """违法目的原则的快速检查：砍头息、违法用途。"""
        if self._money_cut_re.search(text):
            return self._make_result(
                principle,
                "条款约定预先从本金中扣除利息或费用，构成砍头息。",
                level="high",
                matched_text=text,
                evidence_type="illegal_purpose",
            )

        illegal_keywords = ["赌博", "赌资", "贩毒", "走私", "洗钱", "非法集资", "非法经营"]
        if "借款用途" in text or "借款用于" in text or "用于" in text:
            for kw in illegal_keywords:
                if kw in text and self._has_positive_illegal_purpose(text, kw):
                    return self._make_result(
                        principle,
                        f"条款约定借款用于{kw}，违反法律强制性规定。",
                        level="high",
                        matched_text=text,
                        evidence_type="illegal_purpose",
                    )

        # 流质流押
        if re.search(r"抵押物.*归.*所有|质押物.*归.*所有|到期.*所有权.*归|流质|流押", text):
            return self._make_result(
                principle,
                "条款约定债务到期未清偿时担保物所有权直接归债权人所有，构成流质/流押，违反法律强制性规定。",
                level="high",
                matched_text=text,
                evidence_type="illegal_purpose",
            )

        # 复利
        if re.search(r"利滚利|复利|利息计入本金.*计息|滞纳金.*计收.*利息|逾期利息.*计收复利", text):
            return self._make_result(
                principle,
                "条款约定滞纳金、逾期利息计收复利或利息计入本金，违反民间借贷司法解释。",
                level="high",
                matched_text=text,
                evidence_type="illegal_purpose",
            )

        return None

    @staticmethod
    def _parse_chinese_number(s: str) -> int | None:
        """简单中文数字解析。"""
        if not s:
            return None
        cn_nums = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        if len(s) == 1:
            return cn_nums.get(s)
        if s.startswith("十"):
            return 10 + cn_nums.get(s[1:], 0)
        if s.endswith("十"):
            return cn_nums.get(s[:-1], 0) * 10
        if "十" in s:
            parts = s.split("十")
            if len(parts) == 2:
                return cn_nums.get(parts[0], 0) * 10 + cn_nums.get(parts[1], 0)
        return None

    def _check_waive_liability(
        self, text: str, principle: LegalPrinciple
    ) -> dict[str, Any] | None:
        """法定责任不可免除原则的快速检查：免除故意/重大过失责任、质量保证义务、出租人维修义务等。"""
        # 租赁合同中将出租人法定维修义务完全转嫁给承租人（该表述不含"免责"关键词，优先判断）
        if re.search(
            r"(?:租赁|房屋).{0,30}(?:全部|所有).{0,10}维修.{0,15}(?:由乙方|归乙方|乙方承担|承租方承担)|维修义务.{0,10}(?:由乙方|归乙方|乙方承担|承租方承担)",
            text,
        ):
            return self._make_result(
                principle,
                "条款将房屋及附属设施的全部维修义务转嫁给承租方，违反出租人法定维修义务。",
                level="medium",
                confidence=0.8,
                matched_text=text,
                evidence_type="statutory_exclusion",
            )

        if not re.search(r"免责|不承担|不提供|不负责|概不负责|免除", text):
            return None

        # 免除故意或重大过失责任
        patterns = [
            r"故意.*不承担",
            r"重大过失.*不承担",
            r"故意.*不负责",
            r"重大过失.*不负责",
            r"任何情况下.*概不负责",
            r"任何情形.*概不负责",
        ]
        for p in patterns:
            if re.search(p, text):
                return self._make_result(
                    principle,
                    "条款通过格式条款免除因故意或重大过失造成对方损失的责任，违反法律强制性规定。",
                    level="high",
                    matched_text=text,
                    evidence_type="statutory_exclusion",
                )

        # 免除质量保证/售后服务义务
        if re.search(r"质保|质量保证|售后服务|保修", text):
            if re.search(r"不提供.*质保|不提供.*售后|不承担.*质保|不承担.*售后|无质保|无售后", text):
                return self._make_result(
                    principle,
                    "条款单方免除出卖人依法应承担的质量保证或售后服务义务。",
                    level="high",
                    matched_text=text,
                    evidence_type="statutory_exclusion",
                )

        return None

    # ---------- 语义检查 ----------
    async def _run_semantic_checks(
        self, text: str, contract_type: str
    ) -> list[dict[str, Any]]:
        """基于语义相似度召回原则候选，并用 LLM 实例化判断。"""
        if not self._embedding_client:
            return []

        # 编码待审条款
        clause_vector = await self._async_encode(text)
        if not clause_vector:
            return []

        # 召回候选原则
        candidates = self._retrieve_candidate_principles(
            clause_vector, contract_type
        )
        if not candidates:
            return []

        # 对每个候选原则调用 LLM 做实例化判断
        findings: list[dict[str, Any]] = []
        for principle in candidates:
            finding = await self._instantiate_principle(principle, text)
            if finding and finding.get("matched"):
                findings.append(finding)

        return findings

    async def _async_encode(self, text: str) -> list[float]:
        """异步编码文本。"""
        from app.llm.embeddings import get_embedding

        return await get_embedding(text)

    def _retrieve_candidate_principles(
        self, clause_vector: list[float], contract_type: str
    ) -> list[LegalPrinciple]:
        """根据语义相似度召回可能触犯的原则候选。"""
        top_k = self.settings.get("similarity_top_k", 3)
        margin = self.settings.get("similarity_margin", 0.05)
        min_sim = self.settings.get("min_violation_similarity", 0.55)

        scored: list[tuple[float, LegalPrinciple]] = []
        for principle in self.principles:
            if not self._is_applicable(principle, contract_type):
                continue
            if not principle.violation_centroid:
                continue

            violation_sim = self._cosine_similarity(
                clause_vector, principle.violation_centroid
            )
            non_violation_sim = 0.0
            if principle.non_violation_centroid:
                non_violation_sim = self._cosine_similarity(
                    clause_vector, principle.non_violation_centroid
                )

            # 只保留 violation 显著高于 non-violation 且超过最低阈值的原则
            if violation_sim < min_sim:
                continue
            if violation_sim - non_violation_sim < margin:
                continue

            scored.append((violation_sim, principle))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]

    async def _instantiate_principle(
        self, principle: LegalPrinciple, clause_text: str
    ) -> dict[str, Any] | None:
        """调用轻量 LLM 判断具体条款是否违反某原则。"""
        if self._llm_client is None:
            from app.core.config import get_settings
            from app.llm import LLMClient

            self._llm_client = LLMClient(model=get_settings().LLM_MODEL)

        prompt = (
            f"{principle.decision_prompt}\n\n"
            f"待审查条款：\n{clause_text}\n\n"
            "请只输出 JSON 对象，不要加 markdown 代码块，不要解释。"
        )

        try:
            response = await self._llm_client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一名严谨的合同法律审查专家，只根据给定的法律原则判断条款是否违反该原则。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=self.settings.get("llm_temperature", 0.1),
                max_tokens=self.settings.get("llm_max_tokens", 512),
            )
        except Exception:
            # LLM 调用失败时保守处理：不返回风险
            return None

        parsed = self._parse_json_output(response)
        if not isinstance(parsed, dict):
            return None

        violated = parsed.get("violated")
        if not isinstance(violated, bool):
            # 兼容 LLM 输出字符串
            violated = str(violated).lower() in ("true", "yes", "是", "违反")

        if not violated:
            return None

        level = parsed.get("level", principle.default_level)
        if level not in ("high", "medium", "low"):
            level = principle.default_level

        confidence = float(parsed.get("confidence", 0.75))
        confidence = min(max(confidence, 0.0), 1.0)

        return {
            "matched": True,
            "pattern_id": principle.id,
            "risk_type": principle.risk_type,
            "level": level,
            "confidence": confidence,
            "reason": parsed.get("reason", f"条款可能违反{principle.name}"),
            "suggestion": parsed.get("suggestion", self._suggestion_for_principle(principle)),
            "matched_text": clause_text[:300],
            "principle": principle.name,
            "legal_basis": principle.legal_basis,
            "source": "semantic",
            "evidence_type": "semantic_inference",
        }

    # ---------- 输出解析 ----------
    def _parse_json_output(self, text: str) -> Any:
        """解析 LLM 的 JSON 输出，兼容 markdown 代码块。"""
        import json as _json

        text = (text or "").strip()
        try:
            return _json.loads(text)
        except _json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return _json.loads(match.group(1).strip())
            except _json.JSONDecodeError:
                pass

        match = re.search(r"(\{[\s\S]*\})" , text)
        if match:
            try:
                return _json.loads(match.group(1).strip())
            except _json.JSONDecodeError:
                pass

        return text


# 保持向后兼容：RiskReviewAgent 仍可通过 RedFlagDetector 名称导入
RedFlagDetector = PrincipleBasedDetector
