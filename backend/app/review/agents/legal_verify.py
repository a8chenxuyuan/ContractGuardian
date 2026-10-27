from typing import Any

from app.agentkit.base import BaseAgent
from app.contracts.rules.law_whitelist import law_whitelist


class LegalVerifyAgent(BaseAgent):
    def __init__(
        self,
        tools: dict[str, Any] | None = None,
        use_function_calling: bool = False,
    ):
        super().__init__(
            name="LegalVerifyAgent",
            system_prompt="验证风险引用的法律依据是否准确。你可以调用 search_knowledge 查询法律法规，必要时调用 web_search 查找最新司法解释。",
            tools=tools,
            max_turns=5,
            use_function_calling=use_function_calling,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """校验 Risk 节点 law_refs 的真实性，阻断幻觉法条进入报告。

        两级校验：
        1. 白名单精确匹配（法律名 + 条号都必须在知识库中存在）；
        2. 白名单无法判断时，退回 search_knowledge 语义检索兜底。

        判定结果写入节点属性：
        - law_refs: 仅保留验证通过的引用（幻觉法条被剔除）
        - law_invalid_refs: 被剔除的引用（留档可追溯）
        - verified: True/False，供 HumanReviewAgent 分流人工复核
        """
        search_knowledge = self.tools.get("search_knowledge")
        await law_whitelist.ensure_loaded()

        risk_nodes = session_graph.find_nodes(node_type="Risk")

        verified_count = 0
        invalid_count = 0
        unverified = []

        for risk in risk_nodes:
            props = risk.get("properties", {})
            law_refs = props.get("law_refs", []) or []
            if not law_refs:
                continue

            valid_refs: list[str] = []
            invalid_refs: list[dict] = []
            unknown_refs: list[dict] = []

            for ref in law_refs:
                result = law_whitelist.verify(ref)
                status = result.get("status")

                if status == "valid":
                    valid_refs.append(ref)
                    verified_count += 1
                    continue

                if status == "invalid":
                    # 幻觉法条：法律名或条号确定不存在，直接剔除
                    invalid_refs.append({"ref": ref, "reason": result.get("detail", "")})
                    invalid_count += 1
                    continue

                # status == unknown：白名单无法判断，退回语义检索兜底
                found = False
                if search_knowledge:
                    try:
                        article_number = ref.split("第")[-1].replace("条", "").strip()
                        kb_result = await search_knowledge(
                            {"query": article_number, "limit": 1},
                            context,
                        )
                        found = bool(kb_result.get("results"))
                    except Exception:
                        found = False

                if found:
                    valid_refs.append(ref)
                    verified_count += 1
                else:
                    unknown_refs.append({
                        "ref": ref,
                        "reason": result.get("detail", "") + "；语义检索未命中",
                    })

            total = len(law_refs)
            passed = len(valid_refs)
            update: dict[str, Any] = {
                # 剔除幻觉法条（原实现会原样保留全部引用，是幻觉进入报告的漏洞）
                "law_refs": valid_refs,
                "verified": passed == total,
            }
            removed = invalid_refs + unknown_refs
            if removed:
                update["law_invalid_refs"] = [r["ref"] for r in removed]
                unverified.extend(removed)

            session_graph.update_node(risk["id"], update)

        return {
            "output": {
                "verified_count": verified_count,
                "invalid_count": invalid_count,
                "unverified": unverified,
                "whitelist_laws": law_whitelist.law_count,
                "whitelist_articles": len(law_whitelist),
            },
            "findings": [],
            "logs": self.logs,
        }
