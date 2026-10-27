"""
文件：app/agentkit/session_graph.py
作用：实现 SessionGraph，即单次审查会话的共享记忆图。

需要实现的类与函数：

1. class SessionGraph
   核心类，表示一次审查会话的图结构。
   内部可使用 networkx.Graph 或自定义字典实现，也可直接对接 Neo4j 做内存图。
"""
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable


class SessionGraph:
    def __init__(self, session_id: int, contract_id: int, contract_type: str = "通用"):
        self.session_id = session_id
        self.contract_id = contract_id
        self.contract_type = contract_type
        self._nodes = {}
        self._edges = {}
        self._node_index = {}
        self._edge_index = {}
        self._bus = None
        self.add_node(
            node_type="Session",
            properties={
                "session_id": session_id,
                "contract_id": contract_id,
                "contract_type": contract_type,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            node_id=f"Session_{session_id}",
        )

    def set_bus(self, bus: Any) -> None:
        """
        设置消息总线。
        Agent 写入风险时，可以通过 bus 发布 finding_added 事件。
        """
        self._bus = bus

    def get_bus(self) -> Any:
        """获取消息总线（未设置时为 None，如离线评测场景）。"""
        return self._bus

    def add_node(self, node_type: str, properties: dict[str, Any], node_id: str | None = None) -> str:
        """
        添加一个节点。
        返回：生成的节点 ID
        """
        if node_id is None:
            node_id = f"{node_type}_{uuid.uuid4().hex[:12]}"

        if node_id in self._nodes:
            self._nodes[node_id]["properties"].update(properties)
            return node_id
        else:
            node = {
                "id": node_id,
                "type": node_type,
                "properties": properties,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._nodes[node_id] = node
            self._node_index.setdefault(node_type, []).append(node_id)
            return node_id

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> str:
        """
        添加一条边。
        返回：生成的边 ID
        """
        if source_id not in self._nodes or target_id not in self._nodes:
            raise ValueError(f"边 {source_id} -> {target_id} 的节点不存在")
        else:
            existing = self._edge_index.get(source_id, {}).get(edge_type, [])
            if target_id in existing:
                for edge_id, edge in self._edges.items():
                    if (
                        edge["source"] == source_id
                        and edge["target"] == target_id
                        and edge["type"] == edge_type
                    ):
                        return edge_id

            edge_id = f"Edge_{uuid.uuid4().hex[:12]}"
            edge = {
                "id": edge_id,
                "type": edge_type,
                "source": source_id,
                "target": target_id,
                "properties": properties or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._edges[edge_id] = edge
            self._edge_index.setdefault(source_id, {}).setdefault(edge_type, []).append(target_id)
            return edge_id

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """
        根据 ID 获取节点。
        """
        return self._nodes.get(node_id)

    def update_node(self, node_id: str, properties: dict[str, Any]) -> bool:
        """
        更新节点属性。
        如果节点存在，把新属性合并进去；不存在则返回 False。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return False
        else:
            node["properties"].update(properties)
            node["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True

    def find_nodes(
        self, node_type: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        按类型和属性过滤查询节点。
        """
        result = []
        filters = filters or {}

        if node_type:
            candidate_ids = self._node_index.get(node_type, [])
        else:
            candidate_ids = list(self._nodes.keys())

        for node_id in candidate_ids:
            node = self._nodes[node_id]
            match = True
            for key, value in filters.items():
                if node["properties"].get(key) != value:
                    match = False
                    break
            if match:
                result.append(node)

        return result

    def get_neighbors(
        self, node_id: str, edge_type: str | None = None, direction: str = "out"
    ) -> list[dict[str, Any]]:
        """
        获取邻居节点。
        direction 可选 out / in / both
        """
        if node_id not in self._nodes:
            return []
        else:
            neighbors = []
            for edge in self._edges.values():
                if (
                    direction in ("out", "both")
                    and edge["source"] == node_id
                    and (edge_type is None or edge["type"] == edge_type)
                ):
                    target = self._nodes.get(edge["target"])
                    if target:
                        neighbors.append({"node": target, "edge": edge})

                if (
                    direction in ("in", "both")
                    and edge["target"] == node_id
                    and (edge_type is None or edge["type"] == edge_type)
                ):
                    source = self._nodes.get(edge["source"])
                    if source:
                        neighbors.append({"node": source, "edge": edge})

            return neighbors

    def find_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        edge_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        按起点、终点或边类型查询边。
        """
        result = []
        for edge in self._edges.values():
            if source_id is not None and edge["source"] != source_id:
                continue

            if target_id is not None and edge["target"] != target_id:
                continue

            if edge_type is not None and edge["type"] != edge_type:
                continue

            result.append(edge)

        return result

    def merge_duplicate_risks(self) -> int:
        """
        合并重复的风险节点。

        判断标准（满足任一即视为重复）：
        1. risk_type 相同且 clause_text 存在包含关系；
        2. risk_type 相同且关联的 clause_ids 有交集（适用于跨条款风险）。

        合并策略：
        - 保留 level 最高的一条（high > medium > low）。
        - 保留 confidence 最高的一条。
        - 合并 law_refs、suggestion、clause_text，避免信息丢失。
        - 把被合并节点的边迁移到保留节点上。

        返回：合并掉的节点数量。
        """
        level_rank = {"high": 3, "medium": 2, "low": 1}
        risk_nodes = self.find_nodes(node_type="Risk")

        grouped = {}
        for risk in risk_nodes:
            fingerprint = self._legal_fingerprint(risk["properties"])
            grouped.setdefault(fingerprint, []).append(risk)

        merged_count = 0
        for fingerprint, risks in grouped.items():
            if len(risks) <= 1:
                continue
            else:
                kept = []
                for risk in risks:
                    is_duplicate = False
                    risk_text = risk["properties"].get("clause_text", "")
                    risk_clause_ids = set(risk["properties"].get("clause_ids", []))

                    for keeper in kept:
                        keeper_text = keeper["properties"].get("clause_text", "")
                        keeper_clause_ids = set(keeper["properties"].get("clause_ids", []))

                        text_overlap = bool(
                            risk_text
                            and keeper_text
                            and (risk_text in keeper_text or keeper_text in risk_text)
                        )
                        text_similar = bool(
                            risk_text and keeper_text and self._clause_text_similar(risk_text, keeper_text)
                        )
                        id_overlap = bool(
                            risk_clause_ids
                            and keeper_clause_ids
                            and risk_clause_ids & keeper_clause_ids
                        )

                        if text_overlap or text_similar or id_overlap:
                            is_duplicate = True

                            merged_law_refs = list(
                                dict.fromkeys(
                                    keeper["properties"].get("law_refs", [])
                                    + risk["properties"].get("law_refs", [])
                                )
                            )

                            keeper_suggestion = keeper["properties"].get("suggestion", {}) or {}
                            risk_suggestion = risk["properties"].get("suggestion", {}) or {}

                            if isinstance(keeper_suggestion, str):
                                merged_suggestion = {"rationale": keeper_suggestion}
                            elif isinstance(keeper_suggestion, dict):
                                merged_suggestion = dict(keeper_suggestion)
                            else:
                                merged_suggestion = {}

                            if isinstance(risk_suggestion, str):
                                risk_suggestion_dict = {"rationale": risk_suggestion}
                            elif isinstance(risk_suggestion, dict):
                                risk_suggestion_dict = risk_suggestion
                            else:
                                risk_suggestion_dict = {}

                            for key in ["original_text", "revised_text", "rationale"]:
                                if not merged_suggestion.get(key) and risk_suggestion_dict.get(key):
                                    merged_suggestion[key] = risk_suggestion_dict[key]

                            merged_text = keeper_text
                            if risk_text and risk_text not in keeper_text:
                                merged_text = f"{keeper_text}\n{risk_text}".strip()

                            merged_clause_ids = list(keeper_clause_ids | risk_clause_ids)

                            keeper_level = keeper["properties"].get("level", "low")
                            risk_level = risk["properties"].get("level", "low")
                            merged_level = keeper_level
                            if level_rank.get(risk_level, 0) > level_rank.get(keeper_level, 0):
                                merged_level = risk_level

                            keeper_conf = float(keeper["properties"].get("confidence", 0))
                            risk_conf = float(risk["properties"].get("confidence", 0))
                            merged_conf = max(keeper_conf, risk_conf)

                            keeper["properties"].update(
                                {
                                    "level": merged_level,
                                    "confidence": merged_conf,
                                    "clause_text": merged_text,
                                    "clause_ids": merged_clause_ids,
                                    "law_refs": merged_law_refs,
                                    "suggestion": merged_suggestion,
                                }
                            )

                            self._migrate_edges(risk["id"], keeper["id"])
                            self._remove_node(risk["id"])
                            merged_count += 1
                            break

                    if not is_duplicate:
                        kept.append(risk)

        return merged_count

    @staticmethod
    def _legal_fingerprint(props: dict[str, Any]) -> str:
        """
        生成法律问题指纹，用于把同一法律问题的不同表述归一化后去重。

        指纹结构：risk_type + 提取的关键法律要素。
        例如：
        - 比例原则 + 日违约金 5% -> "proportionality:penalty:5%"
        - 试用期超长 + 6个月 -> "minimum_guarantee:probation:6"
        - 违法目的 + 赌博 -> "illegal_purpose:gambling"
        """
        risk_type = (props.get("risk_type", "") or "").lower()
        reason = (props.get("reason", "") or "").lower()
        clause_text = (props.get("clause_text", "") or "").lower()
        context = f"{reason} {clause_text}"

        if any(k in risk_type for k in ["违约", "利息", "利率", "赔偿", "比例"]):
            daily_match = re.search(r"(?:每日|日|每天).*?(\d+(?:\.\d+)?)\s*[％%]", context)
            if daily_match:
                return f"proportionality:daily:{daily_match.group(1)}%"
            else:
                year_match = re.search(r"(?:年利率|年息|年化).*?(\d+(?:\.\d+)?)\s*[％%]", context)
                if year_match:
                    return f"proportionality:annual:{year_match.group(1)}%"
                else:
                    total_match = re.search(
                        r"(?:合同总金额|总金额|标的额|总价款).*?(\d+(?:\.\d+)?)\s*[％%]", context
                    )
                    if total_match:
                        return f"proportionality:total:{total_match.group(1)}%"
                    else:
                        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*[％%]", context)
                        if pct_match:
                            return f"proportionality:pct:{pct_match.group(1)}%"
                        else:
                            return "proportionality:general"
        else:
            if "试用期" in risk_type or "试用期" in reason:
                m = re.search(r"试用期[为是]?\s*(\d+)\s*个月", context)
                if m:
                    return f"minimum_guarantee:probation:{m.group(1)}months"
                else:
                    m_cn = re.search(r"试用期[为是]?\s*([一二两三四五六七八九十])\s*个月", context)
                    if m_cn:
                        months = SessionGraph._parse_simple_chinese_number(m_cn.group(1))
                        if months is not None:
                            return f"minimum_guarantee:probation:{months}months"
                    return "minimum_guarantee:probation"
            elif "社保" in risk_type or "社会保险" in reason:
                return "minimum_guarantee:social_insurance"
            elif "租赁期限" in risk_type or "租赁期限" in reason or "租期" in reason:
                m = re.search(r"租赁期限[为是]?\s*(\d+)\s*年", context)
                if m:
                    return f"minimum_guarantee:lease:{m.group(1)}years"
                else:
                    m_cn = re.search(r"租赁期限[为是]?\s*([一二两三四五六七八九十])\s*年", context)
                    if m_cn:
                        years = SessionGraph._parse_simple_chinese_number(m_cn.group(1))
                        if years is not None:
                            return f"minimum_guarantee:lease:{years}years"
                    return "minimum_guarantee:lease"
            elif any(k in risk_type for k in ["排除", "权利保留", "法定权利"]):
                rights = []
                right_keywords = ["检验", "验收", "异议", "退换", "退货", "解除", "索赔", "抗辩"]
                for kw in right_keywords:
                    if kw in context:
                        rights.append(kw)
                if rights:
                    return f"right_preservation:{'+'.join(sorted(rights))}"
                else:
                    return "right_preservation:general"
            elif any(k in risk_type for k in ["违法", "强制性规定"]):
                illegal_keywords = [
                    "赌博", "赌资", "贩毒", "走私", "洗钱",
                    "非法集资", "非法经营", "砍头息", "流质", "流押", "复利",
                ]
                for kw in illegal_keywords:
                    if kw in context:
                        return f"illegal_purpose:{kw}"
                return "illegal_purpose:general"
            elif any(k in risk_type for k in ["免责", "不可免除"]):
                if "故意" in context or "重大过失" in context:
                    return "non_waivable_liability:intent_or_gross_negligence"
                elif "质量" in context or "维修" in context:
                    return "non_waivable_liability:quality_or_repair"
                else:
                    return "non_waivable_liability:general"
            elif any(k in risk_type for k in ["诚信", "公平", "失衡"]):
                if "涨租" in context or "租金" in context:
                    return "good_faith_fairness:rent_adjustment"
                elif "变更" in context:
                    return "good_faith_fairness:unilateral_change"
                elif "解除" in context:
                    return "good_faith_fairness:unilateral_termination"
                else:
                    return "good_faith_fairness:general"
            else:
                return f"other:{risk_type}"

    @staticmethod
    def _parse_simple_chinese_number(s: str) -> int | None:
        """解析简单中文数字（一～十，含两）。"""
        cn_nums = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        return cn_nums.get(s)

    @staticmethod
    def _clause_text_similar(text_a: str, text_b: str, threshold: float = 0.5) -> bool:
        """
        判断两段条款文本是否足够相似，用于风险去重。

        采用基于字符集合的 Jaccard 相似度，简单高效，无需外部依赖：
        - 把文本切成 2-gram 字符集合；
        - 计算交集与并集之比；
        - 超过 threshold 即认为相似。
        """
        if not text_a or not text_b:
            return False
        else:

            def _bigrams(text: str) -> set[str]:
                chars = list(text.strip())
                return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

            a = _bigrams(text_a)
            b = _bigrams(text_b)
            if not a or not b:
                return False
            else:
                intersection = len(a & b)
                union = len(a | b)
                return intersection / union >= threshold

    def _migrate_edges(self, old_node_id: str, new_node_id: str) -> None:
        """
        把 old_node_id 相关的边迁移到 new_node_id，并去重同类型同向边。
        这是合并节点的辅助函数。
        """
        seen = set()
        edges_to_remove = []
        for edge in list(self._edges.values()):
            if edge["source"] == old_node_id:
                edge["source"] = new_node_id
            if edge["target"] == old_node_id:
                edge["target"] = new_node_id

            key = (edge["source"], edge["target"], edge["type"])
            if key in seen:
                edges_to_remove.append(edge["id"])
            else:
                seen.add(key)

        for edge_id in edges_to_remove:
            del self._edges[edge_id]
        self._rebuild_edge_index()

    def _rebuild_edge_index(self) -> None:
        """根据当前边表重建边索引。"""
        self._edge_index = {}
        for edge in self._edges.values():
            self._edge_index.setdefault(edge["source"], {}).setdefault(edge["type"], []).append(
                edge["target"]
            )

    def _remove_node(self, node_id: str) -> None:
        """
        删除节点及其相关边。
        """
        if node_id not in self._nodes:
            return
        else:
            node_type = self._nodes[node_id]["type"]
            del self._nodes[node_id]
            if node_id in self._node_index.get(node_type, []):
                self._node_index[node_type].remove(node_id)

            edges_to_remove = [
                edge_id
                for edge_id, edge in self._edges.items()
                if edge["source"] == node_id or edge["target"] == node_id
            ]
            for edge_id in edges_to_remove:
                del self._edges[edge_id]

    _DEFAULT_RULES_PATH: Path = Path(__file__).parent / "config" / "cross_clause_rules.json"

    @classmethod
    def _load_cross_clause_rules(cls, rules_path: Path | None = None) -> list[dict[str, Any]]:
        """
        从 JSON 配置文件加载跨条款风险规则。
        """
        path = rules_path or cls._DEFAULT_RULES_PATH
        if not path.exists():
            return []
        else:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("rules", [])

    @staticmethod
    def _match_clause_to_condition(clause_text: str, condition: dict[str, list[str]]) -> bool:
        """
        判断单条条款文本是否满足一个匹配条件。

        条件支持：
        - contains_all: 必须全部包含
        - contains_any: 至少包含一个
        - not_contains_any: 不能包含其中任意一个（用于排除否定/保证性表述）
        - not_contains_all: 不能同时包含所有（较少使用）
        """
        text = clause_text

        if "contains_all" in condition:
            for keyword in condition["contains_all"]:
                if keyword not in text:
                    return False

        if "contains_any" in condition:
            keywords = condition["contains_any"]
            if keywords:
                if not any(k in text for k in keywords):
                    return False

        if "not_contains_any" in condition:
            for keyword in condition["not_contains_any"]:
                if keyword in text:
                    return False

        if "not_contains_all" in condition:
            if all(k in text for k in condition["not_contains_all"]):
                return False

        return True

    @classmethod
    def _match_cross_clause_rule(
        cls, rule: dict[str, Any], clauses: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        """
        用一条规则去匹配条款列表。

        规则中的每个 clause_group 都需要至少找到一个匹配的 Clause。
        为了兼容"同一条款中同时包含多个风险信号"的真实合同写法，
        同一个 Clause 可以被多个 group 复用。
        """
        matched_clauses = []
        for group in rule.get("clause_groups", []):
            condition = group.get("match", {})
            found = None

            for clause in clauses:
                text = clause["properties"].get("text", "")
                if cls._match_clause_to_condition(text, condition):
                    found = clause
                    break

            if found is None:
                return None
            else:
                matched_clauses.append(found)

        return matched_clauses

    async def _detect_cross_clause_risks_by_llm(
        self,
        contract_type: str,
        clauses: list[dict[str, Any]],
        llm_detector: Callable[[str, list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]],
    ) -> list[dict[str, Any]]:
        """
        LLM 兜底：当配置规则没有命中时，调用外部传入的检测器继续发现组合风险。
        """
        try:
            risks = await llm_detector(contract_type, clauses)
        except Exception:
            return []

        for risk in risks:
            clause_ids = risk.get("clause_ids", [])
            for i in range(len(clause_ids) - 1):
                source_id = clause_ids[i]
                target_id = clause_ids[i + 1]
                if source_id in self._nodes and target_id in self._nodes:
                    self.add_edge(
                        source_id,
                        target_id,
                        "RELATES_TO",
                        properties={"reason": risk.get("risk_type", "LLM 发现跨条款风险")},
                    )

        return risks

    async def find_cross_clause_risks(
        self,
        contract_type: str | None = None,
        rules_path: Path | None = None,
        llm_detector: Callable[[str, list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        发现跨条款组合风险。

        流程：
        1. 从配置文件加载规则，按 contract_type 过滤。
        2. 对每条规则，在所有 Clause 节点中匹配 clause_groups。
        3. 命中后在相关 Clause 之间建立 RELATES_TO 边，并生成 Risk。
        4. 如果传入了 llm_detector，再调用 LLM 兜底补充规则未覆盖的组合风险。

        参数：
        - contract_type: 合同类型，例如 "劳动合同"。
                         不传时优先从 Session 节点读取，最后默认 "通用"。
        - rules_path: 规则文件路径，默认使用内置 config/cross_clause_rules.json。
        - llm_detector: 可选的 LLM 兜底检测器，签名为 (contract_type, clauses) -> list[risk]。
        """
        cross_risks = []
        t0_start = datetime.now(timezone.utc).timestamp()

        if contract_type is None:
            session_node = self._nodes.get(f"Session_{self.session_id}")
            if session_node is not None:
                contract_type = session_node["properties"].get("contract_type")
            if contract_type is None:
                contract_type = self.contract_type or "通用"

        clauses = self.find_nodes(node_type="Clause")
        rules = self._load_cross_clause_rules(rules_path)

        for rule in rules:
            applies_to = rule.get("applies_to", [])
            if applies_to and contract_type not in applies_to:
                continue

            matched = self._match_cross_clause_rule(rule, clauses)
            if matched is None:
                continue
            else:
                edge_cfg = rule.get("edge", {})
                edge_type = edge_cfg.get("type", "RELATES_TO")
                edge_reason = edge_cfg.get("reason", rule.get("name", ""))
                for i in range(len(matched) - 1):
                    self.add_edge(
                        matched[i]["id"], matched[i + 1]["id"], edge_type, properties={"reason": edge_reason}
                    )

                risk_cfg = rule.get("risk", {})
                cross_risks.append(
                    {
                        "risk_type": risk_cfg.get("risk_type", rule.get("name", "")),
                        "level": risk_cfg.get("level", "medium"),
                        "confidence": risk_cfg.get("confidence", 0.8),
                        "reason": risk_cfg.get("reason", ""),
                        "clause_ids": [c["id"] for c in matched],
                        "rule_name": rule.get("name"),
                        "source": "rule",
                    }
                )

        llm_risks = []
        rule_risks = [r for r in cross_risks if r.get("source") != "llm"]
        existing_risks = self.find_nodes(node_type="Risk", filters={"level": "high"}) + self.find_nodes(
            node_type="Risk", filters={"level": "medium"}
        )

        if llm_detector is not None and (rule_risks or existing_risks):
            t0_llm = datetime.now(timezone.utc).timestamp()
            llm_risks = await self._detect_cross_clause_risks_by_llm(contract_type, clauses, llm_detector)
            datetime.now(timezone.utc).timestamp() - t0_llm
            for risk in llm_risks:
                risk.setdefault("source", "llm")
            cross_risks.extend(llm_risks)

        datetime.now(timezone.utc).timestamp() - t0_start
        rule_risks = [r for r in cross_risks if r.get("source") != "llm"]

        return cross_risks

    def to_dict(self) -> dict[str, Any]:
        """
        把整张图序列化为字典，便于存入数据库。
        """
        return {
            "metadata": {
                "session_id": self.session_id,
                "contract_id": self.contract_id,
                "contract_type": self.contract_type,
            },
            "nodes": list(self._nodes.values()),
            "edges": list(self._edges.values()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionGraph":
        """
        从字典反序列化 SessionGraph。
        """
        metadata = data.get("metadata", {})
        graph = cls(
            session_id=metadata.get("session_id", 0),
            contract_id=metadata.get("contract_id", 0),
            contract_type=metadata.get("contract_type", "通用"),
        )
        graph._nodes = {}
        graph._edges = {}
        graph._node_index = {}
        graph._edge_index = {}

        for node in data.get("nodes", []):
            graph._nodes[node["id"]] = node
            graph._node_index.setdefault(node["type"], []).append(node["id"])

        for edge in data.get("edges", []):
            graph._edges[edge["id"]] = edge
            graph._edge_index.setdefault(edge["source"], {}).setdefault(edge["type"], []).append(
                edge["target"]
            )

        return graph

    def export_for_llm(self, node_id: str, depth: int = 2) -> str:
        """
        导出某个节点周围的子图，格式化为自然语言文本。
        主要用于 ChatAgent 回答用户关于某条风险的追问。
        """
        if node_id not in self._nodes:
            return ""
        else:
            visited = {node_id}
            current_level = {node_id}
            all_nodes = {node_id}

            for _ in range(depth):
                next_level = set()
                for nid in current_level:
                    for neighbor_info in self.get_neighbors(nid, direction="both"):
                        neighbor_id = neighbor_info["node"]["id"]
                        if neighbor_id not in visited:
                            visited.add(neighbor_id)
                            next_level.add(neighbor_id)
                            all_nodes.add(neighbor_id)
                current_level = next_level

            lines = []
            for nid in all_nodes:
                node = self._nodes[nid]
                node_type = node["type"]
                props = node["properties"]

                if node_type == "Clause":
                    lines.append(f"条款：{props.get('text', '')}")
                elif node_type == "Risk":
                    lines.append(f"风险：{props.get('risk_type', '')}（等级 {props.get('level', '')}）")
                    lines.append(f"原因：{props.get('reason', '')}")
                elif node_type == "Law":
                    lines.append(f"法律依据：{props.get('law_name', '')} 第 {props.get('article_number', '')} 条")
                    lines.append(f"内容：{props.get('article_text', '')}")
                elif node_type == "Suggestion":
                    lines.append(f"修改建议：{props.get('revised_text', '')}")

            return "\n".join(lines)
