import json
from pathlib import Path
from typing import Any

from app.agentkit.base import BaseAgent
from app.contracts.rules.red_flag_detector import RedFlagDetector
from app.review.agents.critic import CriticAgent
from app.review.prompts.risk_review import (
    HOLISTIC_REVIEW_PROMPT_TEMPLATE,
    RISK_REVIEW_SYSTEM_PROMPT,
)


class RiskReviewAgent(BaseAgent):
    """
    通用合同风险审查 Agent。

    设计要点：
    1. 先经 RedFlagDetector 做确定性红线扫描，保证一望即知的违法/高风险条款不被 LLM 漏掉；
    2. system prompt 只保留通用法律原则，不再堆砌测试集补丁；
    3. 边界案例通过 few-shot 案例库动态注入，新增误报/漏报时优先改案例库；
    4. 非确定性候选风险经 CriticAgent 二次校验，降低误报；
    5. 最终按置信度阈值映射风险等级，避免勉强输出。
    """

    # 置信度阈值（最终输出）
    HIGH_CONFIDENCE_THRESHOLD = 0.85
    MEDIUM_CONFIDENCE_THRESHOLD = 0.60

    # 确定性红线命中的置信度下限（用于强制保留）
    DETERMINISTIC_CONFIDENCE_FLOOR = 0.85

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="RiskReviewAgent",
            system_prompt=RISK_REVIEW_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )
        # 风险审查优先使用环境配置中的模型，确保与 .env 保持一致
        from app.core.config import get_settings
        from app.llm import LLMClient
        self.set_llm_client(LLMClient(model=get_settings().LLM_MODEL))

        # 确定性红线检测器：保证通用法律红线不被漏检
        self.red_flag_detector = RedFlagDetector()

        # 二次校验 Agent：用于过滤非确定性风险的误报
        self.critic = CriticAgent(tools=tools)

        # 加载 few-shot 案例库
        self.few_shot_cases = self._load_few_shot_cases()

        # 历史误判/漏检模式（回测与 Critic 回流），每次 run 开头刷新后注入 prompt
        self.mistake_patterns: list[dict[str, Any]] = []
        self.missed_patterns: list[dict[str, Any]] = []

    def _refresh_mistake_patterns(self) -> None:
        """从反例库刷新误报/漏检模式（文件读取一次，run 级别刷新）。"""
        try:
            from app.review.learning import get_counter_example_store

            store = get_counter_example_store()
            self.mistake_patterns = store.get_top_patterns(
                n=5, days=90, evidence_type="backtest_fp"
            )
            self.missed_patterns = store.get_top_patterns(
                n=3, days=90, evidence_type="backtest_fn"
            )
        except Exception as e:  # 学习库不可用不能阻断审查
            print(f"[RiskReview] 加载误判模式失败: {e}")
            self.mistake_patterns = []
            self.missed_patterns = []

    def _format_mistake_patterns(self) -> str:
        """把历史误判/漏检模式格式化为 prompt 段落，为空时返回空串。"""
        if not self.mistake_patterns and not self.missed_patterns:
            return ""
        lines = ["历史回测记录（务必避免重犯）："]
        for p in self.mistake_patterns:
            line = f"- 曾误报：[{p['risk_type']}] {p['pattern']}（{p['count']}次）"
            if p.get("sample_correction"):
                line += f"，正确判断：{p['sample_correction']}"
            lines.append(line)
        for p in self.missed_patterns:
            lines.append(f"- 曾漏检：{p['pattern']}（{p['count']}次），请重点核查该情形")
        return "\n".join(lines)

    def _load_few_shot_cases(self) -> list[dict[str, Any]]:
        """加载 few-shot 案例库。文件不存在或解析失败时返回空列表。"""
        case_file = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "review_few_shot_cases.json"
        )
        try:
            with open(case_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("cases", [])
        except Exception as e:
            print(f"[RiskReview] 加载 few-shot 案例库失败: {e}")
            return []

    def _find_relevant_cases(
        self,
        clause_text: str,
        contract_type: str,
        top_k: int = 3,
        prefer_risk_cases: bool = False,
    ) -> list[dict[str, Any]]:
        """
        根据条款文本和合同类型，从案例库中检索最相关的 few-shot 案例。

        匹配逻辑：
        1. 合同类型匹配：case.contract_types 包含 contract_type 或 "通用"；
        2. 关键词匹配：case.keywords 与 clause_text 的交集越多越相关；
        3. 当 prefer_risk_cases=True（如已命中红线），正例得分额外加权，避免模型被反例拉偏；
        4. 返回 top_k 个最相关案例。
        """
        text = clause_text.lower()
        scored = []
        for case in self.few_shot_cases:
            types = case.get("contract_types", [])
            if contract_type not in types and "通用" not in types:
                continue

            keywords = case.get("keywords", [])
            if not keywords:
                continue

            match_count = sum(1 for kw in keywords if kw.lower() in text)
            if match_count == 0:
                continue

            # 类型完全匹配加分
            type_bonus = 1.0 if contract_type in types else 0.0
            # 红线命中时，正例额外加分
            risk_bonus = 1.5 if prefer_risk_cases and case.get("is_risk") else 0.0
            score = match_count + type_bonus + risk_bonus
            scored.append((score, case))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [case for _, case in scored[:top_k]]

    def _format_few_shot_context(self, cases: list[dict[str, Any]]) -> str:
        """把 few-shot 案例格式化为 prompt 文本。"""
        if not cases:
            return "（本次未匹配到相似案例）"

        lines = ["以下是与当前条款相似的边界案例，供你参考判断："]
        for i, case in enumerate(cases, 1):
            label = "【正例：应报告风险】" if case.get("is_risk") else "【反例：不应报告风险】"
            lines.append(f"\n案例{i} {label}")
            lines.append(f"条款：{case.get('clause_text', '')}")
            lines.append(f"说明：{case.get('explanation', '')}")
            expected = case.get("expected_output", {})
            lines.append(
                f"预期输出：level={expected.get('level', 'low')}, "
                f"risk_type={expected.get('risk_type', '无明显风险')}, "
                f"confidence={expected.get('confidence', 0.5)}"
            )
        return "\n".join(lines)

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """
        分三步审查合同：
        1. 逐条审查 Chunk，发现候选条款级风险；
        2. 对候选风险进行 Critic 二次校验；
        3. 对合同全文做整体性审查。
        """
        import time as _time

        chunks = context.get("chunks", [])
        contract_type = context.get("contract_type", "通用")
        discovered_laws = context.get("discovered_laws", [])
        review_checklist = context.get("review_checklist", [])
        risk_signals = context.get("risk_signals", [])
        findings = []

        law_context = self._format_law_context(discovered_laws)
        checklist_context = self._format_checklist(review_checklist)
        signals_context = self._format_signals_context(risk_signals)

        # 刷新历史误判/漏检模式，供后续两个审查步骤注入
        self._refresh_mistake_patterns()

        print(f"[RiskReview] chunks={len(chunks)}, contract_type={contract_type}, laws={len(discovered_laws)}, checklist={len(review_checklist)}, signals={len(risk_signals)}")

        # ---------- 第一步：逐条审查 ----------
        clause_findings = 0
        chunk_review_count = 0
        chunk_skip_count = 0
        red_flag_count = 0
        deterministic_red_flag_count = 0
        surviving_deterministic_count = 0
        critic_llm_count = 0
        critic_rule_count = 0
        total_clause_llm_time = 0.0
        total_critic_time = 0.0
        for idx, chunk in enumerate(chunks):
            clause_text = chunk.get("text", "")
            chunk.get("id")
            if not clause_text or len(clause_text.strip()) < 15:
                print(f"[RiskReview chunk {idx}] skipped (too short)")
                continue

            # 1. 先跑原则驱动的红线检测
            red_flags = await self.red_flag_detector.detect(clause_text, contract_type)
            high_conf_flags = [
                f for f in red_flags if f.get("level") == "high" and f.get("confidence", 0) >= 0.9
            ]
            has_deterministic_red_flag = bool(high_conf_flags)
            if red_flags:
                red_flag_count += 1
            if has_deterministic_red_flag:
                deterministic_red_flag_count += 1

            # 2. 只有没有确定性红线时，才允许 keyword filter 跳过
            if not has_deterministic_red_flag and not self._is_suspicious_clause(clause_text):
                print(f"[RiskReview chunk {idx}] skipped by keyword filter")
                chunk_skip_count += 1
                continue

            chunk_review_count += 1
            # 3. 构造 prompt，注入红线信号
            task_prompt = self._build_clause_prompt(
                clause_text,
                contract_type,
                law_context,
                checklist_context,
                signals_context,
                red_flags=red_flags,
            )
            t0 = _time.time()
            output = await self._direct_review_clause(task_prompt)
            elapsed = _time.time() - t0
            total_clause_llm_time += elapsed

            level = output.get("level", "low")
            risk_type = output.get("risk_type", "")

            # 4. 如果红线检测命中 high，但 LLM 输出 low，强制用红线结果兜底
            if has_deterministic_red_flag and level not in ("high", "medium"):
                primary_flag = high_conf_flags[0]
                output = self._merge_red_flag_with_llm(primary_flag, output)
                level = output.get("level", "high")
                risk_type = output.get("risk_type", "")
                print(f"[RiskReview chunk {idx}] DETECTOR_OVERRIDES_LLM: {primary_flag.get('pattern_id')}")

            if level in ("high", "medium"):
                # 5. 按证据类型决定是否经过 Critic
                # numeric/statutory 类 detector 结果可信度高，直接放行
                # keyword/semantic 类仍需 Critic 守门，避免 detector 误判
                evidence_type = output.get("evidence_type", "keyword_match")
                high_trust_evidence = {"numeric_violation", "statutory_violation", "statutory_exclusion"}
                critic_t0 = _time.time()
                if has_deterministic_red_flag and evidence_type in high_trust_evidence:
                    final_output = output
                    final_level = level
                    critic_rule_count += 1
                else:
                    verified = await self._critic_review(
                        output, clause_text, contract_type, law_context
                    )
                    final_output = self._apply_critic_result(output, verified)
                    final_level = final_output.get("level", "low")
                    if verified.get("source") == "rule":
                        critic_rule_count += 1
                    else:
                        critic_llm_count += 1
                total_critic_time += _time.time() - critic_t0

                if final_level in ("high", "medium"):
                    clause_findings += 1
                    if has_deterministic_red_flag:
                        surviving_deterministic_count += 1
                    self._add_risk_node(session_graph, chunk, final_output)
                    findings.append(final_output)
                    print(f"[RiskReview chunk {idx}] {elapsed:.2f}s FOUND [{final_level}] {risk_type}: {final_output.get('reason','')[:60]}")
                else:
                    print(f"[RiskReview chunk {idx}] {elapsed:.2f}s CRITIC_FILTERED [{level}->{final_level}] {risk_type}")
            else:
                print(f"[RiskReview chunk {idx}] {elapsed:.2f}s no risk (level={level}, type={risk_type})")

        print(f"[RiskReview] clause review done, findings={clause_findings}")

        # ---------- 第二步：整体性审查 ----------
        # 优化：如果逐条审查没有产生任何高/中风险，且没有 surviving 的确定性红线，
        # 说明当前合同条款层面风险信号极弱，跳过整体性审查，避免在明显合法的合同上
        # 触发一次全文 LLM 调用并产生误报。
        if clause_findings == 0 and surviving_deterministic_count == 0:
            print("[RiskReview] holistic review skipped (no clause-level findings)")
        else:
            print("[RiskReview] starting holistic review...")
            holistic_t0 = _time.time()
            holistic_findings = await self._holistic_review(
                session_graph, chunks, contract_type, law_context, checklist_context, signals_context
            )
            _time.time() - holistic_t0
            print(f"[RiskReview] holistic review done, findings={len(holistic_findings)}")
            findings.extend(holistic_findings)

        return {"output": {}, "findings": findings, "logs": self.logs}

    async def _critic_review(
        self,
        candidate: dict[str, Any],
        clause_text: str,
        contract_type: str,
        law_context: str,
    ) -> dict[str, Any]:
        """调用 CriticAgent 对候选风险做二次校验。"""
        return await self.critic.review_finding(
            candidate=candidate,
            clause_text=clause_text,
            contract_type=contract_type,
            law_context=law_context,
        )

    def _apply_critic_result(
        self,
        candidate: dict[str, Any],
        critic_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        根据 Critic 结果调整候选风险。

        规则：
        - false_positive：直接降为 low（过滤掉）；
        - uncertain：降低置信度，如果低于阈值则降为 low；
        - valid：应用 confidence_adjustment，再按阈值映射等级。
        """
        output = dict(candidate)
        verdict = critic_result.get("verdict", "uncertain")
        adjustment = float(critic_result.get("confidence_adjustment", 0.0))
        reason = critic_result.get("reason", "")

        # 记录 Critic 意见到日志
        self.logs.append({
            "action": "critic_review",
            "verdict": verdict,
            "adjustment": adjustment,
            "reason": reason,
            "risk_type": output.get("risk_type"),
        })

        if verdict == "false_positive":
            output["level"] = "low"
            output["risk_type"] = "无明显风险"
            output["confidence"] = 0.1
            return output

        # 调整置信度并限制范围
        new_confidence = min(max(output.get("confidence", 0.5) + adjustment, 0.0), 1.0)
        output["confidence"] = new_confidence

        # 按阈值映射最终等级
        if new_confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            output["level"] = "high"
        elif new_confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            output["level"] = "medium"
        else:
            output["level"] = "low"
            output["risk_type"] = "无明显风险"

        return output

    def _add_risk_node(
        self,
        session_graph: Any,
        chunk: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        """把校验后的风险写入 SessionGraph。"""
        clause_text = chunk.get("text", "")
        chunk_id = chunk.get("id")
        risk_id = session_graph.add_node(
            node_type="Risk",
            properties={
                "risk_type": output.get("risk_type", "未分类"),
                "level": output.get("level", "low"),
                "confidence": output.get("confidence", 0.5),
                "reason": output.get("reason", ""),
                "suggestion": output.get("suggestion", {}),
                "clause_text": clause_text,
                "source_chunk_id": chunk_id,
                "page": chunk.get("page", 1),
                "bbox": chunk.get("bbox"),
            },
        )

        if chunk_id and session_graph.get_node(chunk_id):
            session_graph.add_edge(
                source_id=chunk_id,
                target_id=risk_id,
                edge_type="HAS_RISK",
            )

    def _format_law_context(self, discovered_laws: list[dict[str, Any]]) -> str:
        """将动态发现的法律依据格式化为上下文文本。"""
        if not discovered_laws:
            return "（本次尚未检索到具体法律依据，请基于一般法律原则进行审查）"

        lines = []
        for law in discovered_laws[:8]:
            name = law.get("law_name", "")
            number = law.get("article_number", "")
            title = law.get("article_title", "")
            text = law.get("article_text", "")[:400]
            review_points = law.get("review_points", [])

            header = f"{name} {number}"
            if title:
                header += f" {title}"
            lines.append(f"【{header}】")
            if text:
                lines.append(f"原文：{text}")
            if review_points:
                lines.append("审查要点：" + "；".join(review_points))
            lines.append("")

        return "\n".join(lines)

    def _format_checklist(self, review_checklist: list[str]) -> str:
        """将动态审查清单格式化为上下文文本。"""
        if not review_checklist:
            return "（本次未生成专项审查清单）"
        return "\n".join(f"- {item}" for item in review_checklist[:8])

    def _format_signals_context(self, risk_signals: list[dict[str, Any]]) -> str:
        """将 LegalResearchAgent 推断的风险信号格式化为上下文文本。"""
        if not risk_signals:
            return "（本次未识别到特定风险信号）"
        lines = []
        for s in risk_signals[:8]:
            signal = s.get("signal", "")
            law_area = s.get("law_area", "")
            if law_area:
                lines.append(f"- {signal}（涉及：{law_area}）")
            else:
                lines.append(f"- {signal}")
        return "\n".join(lines)

    def _format_red_flags(self, red_flags: list[dict[str, Any]]) -> str:
        """将 RedFlagDetector 命中结果格式化为上下文文本。"""
        if not red_flags:
            return "（本次未命中确定性红线规则）"
        lines = ["以下规则已在本条款中命中，请你重点核实并给出法律理由："]
        for flag in red_flags[:5]:
            lines.append(
                f'- [{flag.get("level", "medium").upper()}] {flag.get("risk_type", "")}：'
                f'{flag.get("reason", "")}'
            )
        return "\n".join(lines)

    def _merge_red_flag_with_llm(
        self,
        red_flag: dict[str, Any],
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        当 LLM 对确定性红线输出 low 时，用红线结果兜底。
        必须同步使用 detector 的 reason/suggestion，避免结论与论证断裂。
        若 LLM 给出不同法律意见，作为附注保留，供后续审计。
        """
        merged = dict(llm_output)
        merged["level"] = red_flag.get("level", "high")
        merged["risk_type"] = red_flag.get("risk_type", "法律风险")
        merged["confidence"] = max(
            float(red_flag.get("confidence", 0.95)),
            self.DETERMINISTIC_CONFIDENCE_FLOOR,
        )
        # 核心修复：override 时统一使用 detector 的法律理由，确保结论自洽
        detector_reason = red_flag.get("reason", "")
        detector_suggestion = red_flag.get("suggestion", "")
        llm_reason = llm_output.get("reason", "")

        merged["reason"] = detector_reason
        merged["suggestion"] = detector_suggestion

        # 若 LLM 明确表达了相反意见，保留在审计字段中
        if llm_reason and detector_reason and llm_reason != detector_reason:
            merged["llm_dissent"] = llm_reason

        # 标记来源与证据类型，便于后续评估和学习
        merged["deterministic_red_flag"] = red_flag.get("pattern_id")
        merged["evidence_type"] = red_flag.get("evidence_type", "keyword_match")
        return merged

    def _build_clause_prompt(
        self,
        clause_text: str,
        contract_type: str,
        law_context: str,
        checklist_context: str,
        signals_context: str,
        red_flags: list[dict[str, Any]] | None = None,
    ) -> str:
        """构造针对单条条款的审查任务提示词。"""
        has_high_flag = any(f.get("level") == "high" for f in (red_flags or []))
        relevant_cases = self._find_relevant_cases(
            clause_text, contract_type, prefer_risk_cases=has_high_flag
        )
        few_shot_context = self._format_few_shot_context(relevant_cases)

        red_flag_context = self._format_red_flags(red_flags or [])

        mistake_context = self._format_mistake_patterns()
        mistake_block = f"{mistake_context}\n\n" if mistake_context else ""

        return (
            "请审查以下合同条款。\n\n"
            "本次审查可参考的法律依据：\n"
            f"{law_context}\n\n"
            "本次审查重点关注：\n"
            f"{checklist_context}\n\n"
            "合同文本中已识别的潜在风险信号（请特别关注这些信号是否在本条款中出现）：\n"
            f"{signals_context}\n\n"
            f"{mistake_block}"
            f"{red_flag_context}\n\n"
            f"{few_shot_context}\n\n"
            "待审查条款：\n"
            f"{clause_text}\n\n"
            "请从主体资格、权利义务对等、违约责任合理性、期限与解除、强制性法律规定、"
            "格式条款公平性、争议解决可执行性等通用维度进行评估。\n\n"
            "判断标准（风险三级定义）：\n"
            "- high（硬性违法）：条款明确违反法律强制性规定，必须报告。例如：违约金超过法定红线、排除法定权利、试用期超过法定上限、约定违法用途、免除故意/重大过失责任。\n"
            "- medium（法律风险）：条款可能导致不利后果或权利明显失衡，但未必直接无效。例如：权利义务明显失衡、关键义务约定模糊到难以履行、单方任意变更权。\n"
            "- low（无明显风险）：正常商业安排、一般性表述、合同未约定某事项、付款节奏/项目进度安排、起草可优化但不构成法律问题。\n\n"
            "具体规则：\n"
            "1. 只报告条款本身存在的明显不公平或违法问题；\n"
            "2. 合同未约定某事项、或约定较简略，不等于存在法律风险；\n"
            "3. 质量标准、知识产权归属、押金退还条件等'缺失'本身不构成风险，除非条款明确排除对方权利或导致履行不能；\n"
            "4. 违约金、赔偿金要明显过高才报告：日违约金超过千分之一（0.1%/日），或一次性违约金明显超过合同标的30%且无合理解释；\n"
            "5. 正常的预付款、分期付款、验收合格后付款、交付后付款是 common 商业安排，不要报为'付款与权利转移错位'或权利义务失衡；\n"
            "6. '违约金 + 赔偿损失'在中国法下可并用，只有约定无限制双重赔付才构成重复主张；\n"
            "7. 条款明确禁止某种违法用途（如'不得用于赌博、非法集资'）属于合法限制，不是违法目的；\n"
            "8. 适用对象、计算期间或触发条件不同的违约责任/费用，不得简单相加后作为整体判断是否超过法定上限；\n"
            "9. 合同前言中的概括表述与具体条款不一致时，通常以具体条款为准，不构成合同目的冲突；\n"
            "10. 如果条款没有明显问题，请直接输出 level='low'，risk_type='无明显风险'，不要勉强找问题。\n\n"
            "请直接输出且仅输出一个 JSON 对象，不要加 markdown 代码块，不要解释：\n"
            '{"risk_type":"风险名称","level":"high/medium/low","confidence":0.9,"reason":"结合条款说明","suggestion":"修改建议"}'
        )

    async def _holistic_review(
        self,
        session_graph: Any,
        chunks: list[dict[str, Any]],
        contract_type: str,
        law_context: str,
        checklist_context: str,
        signals_context: str,
    ) -> list[dict[str, Any]]:
        """对合同全文做整体性审查，重点关注跨条款组合风险。"""
        if not chunks:
            return []

        contract_text = "\n".join(c.get("text", "") for c in chunks)
        if len(contract_text) > 4000:
            contract_text = contract_text[:4000] + "\n...（后续内容省略）"

        # 整体性审查也注入与合同类型相关的 few-shot 案例
        relevant_cases = self._find_relevant_cases(contract_text, contract_type, top_k=3)
        few_shot_context = self._format_few_shot_context(relevant_cases)

        # 追加历史误判/漏检模式（模板占位符复用 few_shot_context，不改模板结构）
        mistake_context = self._format_mistake_patterns()
        if mistake_context:
            few_shot_context = f"{mistake_context}\n\n{few_shot_context}"

        prompt = HOLISTIC_REVIEW_PROMPT_TEMPLATE.format(
            law_context=law_context,
            checklist_context=checklist_context,
            few_shot_context=few_shot_context,
            signals_context=signals_context,
            contract_text=contract_text,
        )

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as e:
            self.logs.append({"action": "holistic_review", "error": str(e)})
            return []

        parsed = self._parse_json_output(response)
        if not isinstance(parsed, list):
            return []

        findings = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            level = item.get("level", "low")
            if level not in ("high", "medium"):
                continue

            # 对整体性风险也做 Critic 校验；但如果涉及文本命中确定性红线，则跳过 Critic
            clause_text = item.get("clause_text", "")
            holistic_red_flags = await self.red_flag_detector.detect(clause_text, contract_type)
            holistic_high_flags = [
                f for f in holistic_red_flags if f.get("level") == "high" and f.get("confidence", 0) >= 0.9
            ]
            if holistic_high_flags:
                final_item = item
                final_item["deterministic_red_flag"] = holistic_high_flags[0].get("pattern_id")
            else:
                verified = await self._critic_review(
                    item, clause_text, contract_type, law_context
                )
                final_item = self._apply_critic_result(item, verified)
            if final_item.get("level", "low") not in ("high", "medium"):
                continue

            risk_props = {
                "risk_type": final_item.get("risk_type", "未分类"),
                "level": final_item.get("level", "low"),
                "confidence": float(final_item.get("confidence", 0.7)),
                "reason": final_item.get("reason", ""),
                "suggestion": final_item.get("suggestion", {}),
                "clause_text": clause_text,
                "is_holistic": True,
                "page": 1,
                "bbox": None,
            }
            risk_id = session_graph.add_node(node_type="Risk", properties=risk_props)
            findings.append(final_item)

            # 尝试与包含相关文本的 Clause 建立边
            for chunk in chunks:
                chunk_text = chunk.get("text", "")
                chunk_id = chunk.get("id")
                if chunk_id and chunk_text and (
                    chunk_text in clause_text or clause_text in chunk_text or
                    any(term in chunk_text and len(term) > 3 for term in clause_text.split("，"))
                ):
                    try:
                        session_graph.add_edge(
                            source_id=chunk_id,
                            target_id=risk_id,
                            edge_type="HAS_RISK",
                        )
                    except Exception as exc:
                        # 单条边添加失败（如重复边）不影响整体审查，留痕即可
                        print(f"[warn] add_edge 失败 {chunk_id}->{risk_id}: {exc}", flush=True)

        return findings

    # 常见风险关键词：命中这些词才进入 LLM 深度审查
    _RISK_KEYWORDS: tuple[str, ...] = (
        "违约金", "逾期", "滞纳金", "罚款", "赔偿责任",
        "不得", "禁止", "无权", "概不", "永不", "永久", "无限期",
        "不提供", "不负责", "不承担", "免除", "放弃", "排除",
        "超过", "高于", "低于", "千分之一", "百分之", "年化",
        "单方", "任意", "随时", "擅自",
        "砍头息", "预先扣除", "借款用途",
        "质押", "抵押", "已质押",
        "公司承担", "个人债务",
        "试用期", "社保", "加班费", "经济补偿", "竞业限制",
        "二十年", "涨租", "解约",
        "瑕疵", "缺陷", "质量问题", "质保", "售后",
    )

    def _is_suspicious_clause(self, clause_text: str) -> bool:
        """根据关键词快速判断条款是否值得送入 LLM 深度审查。"""
        text = clause_text.lower()
        return any(kw in text for kw in self._RISK_KEYWORDS)

    async def _direct_review_clause(self, task_prompt: str) -> dict[str, Any]:
        """直接调用 LLM 审查单条条款，返回标准风险结论字典。"""
        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": task_prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
        except Exception as e:
            self.logs.append({"action": "direct_review_clause", "error": str(e)})
            return {"level": "low", "risk_type": "无明显风险"}

        parsed = self._parse_json_output(response)
        if isinstance(parsed, dict) and "level" in parsed:
            return {
                "risk_type": parsed.get("risk_type", "未分类"),
                "level": parsed.get("level", "low"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "reason": parsed.get("reason", ""),
                "suggestion": parsed.get("suggestion", ""),
            }

        # 兼容 LLM 返回 final_answer 包装的情况
        if isinstance(parsed, dict):
            final = parsed.get("final_answer", parsed)
            if isinstance(final, dict) and "level" in final:
                return {
                    "risk_type": final.get("risk_type", "未分类"),
                    "level": final.get("level", "low"),
                    "confidence": float(final.get("confidence", 0.5)),
                    "reason": final.get("reason", ""),
                    "suggestion": final.get("suggestion", ""),
                }

        self.logs.append({
            "action": "direct_review_clause",
            "warning": "无法解析 LLM 输出为风险结论",
            "raw": (response or "")[:300],
        })
        return {"level": "low", "risk_type": "无明显风险"}

    def _extract_risk_output(self, output: Any) -> dict[str, Any]:
        """从 ReAct 输出中提取风险结论，兼容多种格式。"""
        if not isinstance(output, dict):
            return {"level": "low", "risk_type": "无明显风险"}

        if "level" in output:
            return output

        final = output.get("final_answer", {})
        if isinstance(final, dict) and "level" in final:
            return final

        return {"level": "low", "risk_type": "无明显风险"}

    def _parse_json_output(self, text: str) -> Any:
        """解析 LLM 的 JSON 输出，兼容 markdown 代码块。"""
        import json as _json
        import re as _re

        text = (text or "").strip()
        try:
            return _json.loads(text)
        except _json.JSONDecodeError:
            pass

        match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return _json.loads(match.group(1).strip())
            except _json.JSONDecodeError:
                pass

        match = _re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if match:
            try:
                return _json.loads(match.group(1).strip())
            except _json.JSONDecodeError:
                pass

        return text
