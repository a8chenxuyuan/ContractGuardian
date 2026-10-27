"""
Agent：LegalResearchAgent
作用：动态法律研究与审查要点生成。

核心职责：
1. 读取合同全文，推断可能适用的法律领域、具体法律名称与条款号；
2. 调用 search_knowledge（含 Tavily 联网缓存兜底）检索相关法律原文；
3. 将检索到的法条转化为「审查要点」，写入 SessionGraph 的 Law 节点；
4. 把发现的法律依据与动态审查清单返回给 Coordinator，供后续 Agent 使用。

设计原则：
- 不依赖预设合同类型，强调泛化推断；
- 尽可能推断到「法律名称 + 条款号」，用精准检索替代泛泛搜索；
- 检索失败不阻断主流程，至少返回通用审查维度。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.legal_research import (
    CHECKLIST_PROMPT_TEMPLATE,
    CHECKLIST_RETRY_PROMPT_TEMPLATE,
    COMBINED_INFERENCE_PROMPT_TEMPLATE,
    COMBINED_RETRY_PROMPT_TEMPLATE,
    LEGAL_RESEARCH_SYSTEM_PROMPT,
    REVIEW_POINTS_PROMPT_TEMPLATE,
    REVIEW_POINTS_RETRY_PROMPT_TEMPLATE,
)


class LegalResearchAgent(BaseAgent):
    """
    Agent：LegalResearchAgent
    作用：动态法律研究与审查要点生成。

    优化点：
    1. 合并法律领域推断与风险信号推断为一次 LLM 调用；
    2. 对（法律名称 + 条款号）的审查要点做类级缓存，避免重复调用；
    3. 高频法条使用预制审查要点模板，进一步减少 LLM 调用；
    4. 生成动态审查清单时优先使用已发现的法律依据，降低对 LLM 的依赖。
    """

    # 类级缓存：key = law_name|article_number|hash(article_text[:200])
    _review_point_cache: dict[str, list[str]] = {}
    # 类级缓存：key = search_query，value = list[article_dict]
    _web_search_cache: dict[str, list[dict[str, Any]]] = {}

    # 常见法条审查要点模板：命中时直接返回，不再调用 LLM
    REVIEW_POINT_TEMPLATES: dict[str, list[str]] = {
        "中华人民共和国民法典|第六条": [
            "检查合同整体权利义务安排是否显失公平",
            "检查是否存在明显免除一方责任、加重对方责任的条款",
        ],
        "中华人民共和国民法典|第五百零九条": [
            "检查当事人是否按照约定全面履行自己的义务",
            "检查是否遵循诚信原则履行通知、协助、保密等附随义务",
        ],
        "中华人民共和国民法典|第五百八十四条": [
            "检查损失赔偿额是否相当于因违约所造成的损失",
            "检查赔偿额是否超过违约一方订立合同时预见到或应当预见到的因违约可能造成的损失",
        ],
        "中华人民共和国民法典|第四百九十七条": [
            "检查是否存在不合理地免除或减轻己方责任、加重对方责任、限制对方主要权利的格式条款",
            "检查是否以显著方式提示并说明与对方有重大利害关系的格式条款",
        ],
        "中华人民共和国民法典|第五百八十五条": [
            "检查违约金是否过分高于实际损失",
            "检查违约金条款是否约定合理的调整机制",
            "重点关注日违约金是否超过主债权千分之一或一次性违约金是否超过合同标的30%",
        ],
        "中华人民共和国民法典|第六百零三条": [
            "检查标的物交付地点是否明确约定",
            "检查标的物毁损、灭失风险转移时点是否清晰",
        ],
        "中华人民共和国民法典|第六百一十条": [
            "检查标的物不符合质量要求时买受人是否仍享有拒收、解除等法定救济权利",
            "检查合同是否通过单方标准排除买受人的法定质量救济权",
        ],
        "中华人民共和国民法典|第六百一十五条": [
            "检查质量标准是否明确、可执行",
            "检查是否约定符合国家标准、行业标准或通常标准",
        ],
        "中华人民共和国民法典|第六百一十七条": [
            "检查出卖人是否对标的物质量承担瑕疵担保责任",
            "检查免责条款是否不合理地排除法定质量担保义务",
        ],
        "中华人民共和国民法典|第六百二十条": [
            "检查买受人收到标的物后是否在约定期限内检验",
            "检查未约定检验期限时是否及时在合理期限内提出异议",
        ],
        "中华人民共和国民法典|第六百二十二条": [
            "检查约定的检验期限是否过短，是否剥夺买受人对隐蔽瑕疵的检验权",
            "检查异议期限是否符合标的物的性质和交易习惯",
        ],
        "中华人民共和国民法典|第六百七十条": [
            "检查借款利息是否预先在本金中扣除（砍头息）",
            "检查实际出借金额是否与约定本金一致",
        ],
        "中华人民共和国民法典|第七百零五条": [
            "检查租赁期限是否超过二十年",
            "检查超过二十年的租赁期限是否被依法处理",
        ],
        "中华人民共和国劳动合同法|第十九条": [
            "检查试用期期限是否超过法定上限",
            "检查试用期约定是否与劳动合同期限相匹配",
        ],
        "中华人民共和国劳动合同法|第二十条": [
            "检查试用期工资是否不低于转正工资的80%",
            "检查试用期工资是否不低于用人单位所在地最低工资标准",
        ],
        "中华人民共和国公司法|第八十六条": [
            "检查股权转让是否依法办理变更登记",
            "检查股东名册是否及时更新记载受让方信息",
        ],
        "中华人民共和国公司法|第八十八条": [
            "检查转让方是否如实披露股权出资情况",
            "检查受让方是否知晓股权存在瑕疵出资",
        ],
        "中华人民共和国反不正当竞争法|第九条": [
            "检查保密信息的范围是否明确",
            "检查保密义务是否覆盖不正当获取、披露、使用商业秘密的行为",
        ],
        "最高人民法院关于审理民间借贷案件适用法律若干问题的规定|第二十五条": [
            "检查借款利率是否超过合同成立时一年期 LPR 的四倍",
            "检查利率约定是否明确、可计算",
        ],
        "最高人民法院关于审理民间借贷案件适用法律若干问题的规定|第二十八条": [
            "检查逾期利率是否超过法定上限",
            "检查逾期利息、违约金与其他费用之和是否超过 LPR 四倍",
        ],
    }

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="LegalResearchAgent",
            system_prompt=LEGAL_RESEARCH_SYSTEM_PROMPT,
            tools=tools,
            max_turns=3,
        )
        # 法律研究统一读取环境配置中的模型
        from app.core.config import get_settings
        from app.llm import LLMClient
        self.set_llm_client(LLMClient(model=get_settings().LLM_MODEL))

    async def run(
        self,
        session_graph: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        执行动态法律研究。

        返回：
        {
            "output": {"discovered_count": int},
            "discovered_laws": [{law_name, article_number, article_text, review_points, source}, ...],
            "review_checklist": [str, ...],
            "logs": [...]
        }
        """
        chunks = context.get("chunks", [])
        contract_type = context.get("contract_type", "通用")

        # 1. 拼接合同文本（控制长度，避免 token 爆炸）
        t0 = time.time()
        contract_text = self._build_contract_text(chunks)
        print(f"[LR {time.time()-t0:.2f}s] build_contract_text done")

        # 2. 合并调用：一次 LLM 同时推断法律领域和风险信号
        t0 = time.time()
        inference_result = await self._infer_areas_and_signals(
            contract_text, contract_type
        )
        legal_areas = inference_result.get("legal_areas", [])
        risk_signals = inference_result.get("risk_signals", [])
        infer_cost = time.time() - t0
        print(f"[LR {infer_cost:.2f}s] infer done, areas={len(legal_areas)}, signals={len(risk_signals)}")

        # 3. 检索每个法律领域对应的法条
        t0_total = time.time()
        discovered_laws: list[dict[str, Any]] = []
        search_knowledge = self.tools.get("search_knowledge")

        # 延迟导入，避免启动时的循环导入
        from app.rag.knowledge_cache import (
            cache_articles_from_web_search,
            fetch_and_cache_article,
        )

        # 限制泛化联网检索总次数，避免 Tavily 调用过多拖慢整体审查
        max_general_web_searches = 3
        general_web_search_count = 0

        # 判断整体风险信号强弱，用于 LegalResearch 快速路径
        self._has_strong_risk_signals(risk_signals)

        for idx, area in enumerate(legal_areas[:6]):  # 最多处理 6 个领域
            t0_area = time.time()
            query = area.get("keywords") or area.get("area") or ""
            if not query:
                continue

            # ---------- 3.1 本地知识库检索（带 CRAG 纠错） ----------
            t0 = time.time()
            local_articles: list[dict[str, Any]] = []
            if search_knowledge:
                try:
                    from app.rag.crag import corrective_search

                    async def _local_search(q: str) -> list[dict[str, Any]]:
                        r = await search_knowledge(
                            {"query": q, "limit": 5, "enable_web_search": False},
                            context,
                        )
                        return r.get("results", [])

                    # CRAG：最高分低于阈值时 LLM 改写问法重检索，仍不足则 degraded=True
                    local_articles, crag_degraded = await corrective_search(
                        _local_search, query, self.llm_client
                    )
                    if crag_degraded:
                        self.logs.append({
                            "action": "crag_degraded",
                            "query": query,
                            "note": "改写重检索后分数仍低于阈值，本地依据不足",
                        })
                    print(f"[LR area {idx} {time.time()-t0:.2f}s] local search done, query={query[:20]}, results={len(local_articles)}")
                except Exception as e:
                    self.logs.append({
                        "action": "search_knowledge",
                        "query": query,
                        "error": str(e),
                    })

            # ---------- 3.2 精准联网检索：如果推断出具体法律+条款 ----------
            targeted_articles: list[dict[str, Any]] = []
            law_name = area.get("law_name", "")
            article_number = area.get("article_number", "")
            if law_name and article_number:
                try:
                    cached = await fetch_and_cache_article(
                        law_name=law_name,
                        article_number=article_number,
                        keywords=query,
                    )
                    print(f"[LR area {idx} {time.time()-t0:.2f}s] targeted fetch done, law={law_name[:15]} {article_number}, cached={cached and cached.get('cached')}")
                    if cached and cached.get("cached"):
                        targeted_articles.append({
                            "law_name": cached.get("law_name", ""),
                            "article_number": cached.get("article_number", ""),
                            "article_title": cached.get("article_title", ""),
                            "article_text": cached.get("article_text", ""),
                            "source": "web_cache",
                        })
                except Exception as e:
                    self.logs.append({
                        "action": "fetch_and_cache_article",
                        "law_name": law_name,
                        "article_number": article_number,
                        "error": str(e),
                    })

            # ---------- 3.3 泛化联网检索兜底 ----------
            # 优化：限制每个合同的泛化联网检索次数，并对相同 query 做缓存，
            # 既保留发现风险的能力，又避免 Tavily 调用过多拖慢整体审查。
            #
            # 快速路径：当本地检索 + 精准检索均未获得法条，且当前领域无强风险信号时，
            # 直接跳过泛化 web search。这能显著降低合法合同上的 Tavily 空转耗时。
            web_articles: list[dict[str, Any]] = []
            search_query = query + " 原文"
            has_local_or_targeted = bool(local_articles or targeted_articles)
            area_has_strong_signal = self._area_matches_risk_signal(area, risk_signals)
            skip_web_reason: str | None = None
            if not has_local_or_targeted and not area_has_strong_signal:
                skip_web_reason = "local+targeted 无结果且风险信号弱"
            elif general_web_search_count >= max_general_web_searches:
                skip_web_reason = "泛化联网检索次数已达上限"

            if skip_web_reason:
                self.logs.append({
                    "action": "cache_articles_from_web_search",
                    "query": search_query,
                    "skipped": True,
                    "reason": skip_web_reason,
                })
                print(f"[LR area {idx} {time.time()-t0:.2f}s] web search skipped, reason={skip_web_reason}")
            else:
                # 类级缓存命中：相同 query 直接复用
                cached_web = LegalResearchAgent._web_search_cache.get(search_query)
                if cached_web is not None:
                    web_articles = cached_web
                    self.logs.append({
                        "action": "cache_articles_from_web_search",
                        "query": search_query,
                        "cache_hit": True,
                        "result_count": len(web_articles),
                    })
                else:
                    try:
                        cached_list = await cache_articles_from_web_search(
                            query=search_query,
                            category=None,
                            limit=2,
                        )
                        print(f"[LR area {idx} {time.time()-t0:.2f}s] web search done, query={search_query[:25]}, results={len(cached_list)}")
                        general_web_search_count += 1
                        for item in cached_list:
                            if item.get("cached"):
                                web_articles.append({
                                    "law_name": item.get("law_name", ""),
                                    "article_number": item.get("article_number", ""),
                                    "article_title": item.get("article_title", ""),
                                    "article_text": item.get("article_text", ""),
                                    "source": "web_cache",
                                })
                        # 写入类级缓存，供后续合同复用
                        LegalResearchAgent._web_search_cache[search_query] = web_articles
                    except Exception as e:
                        self.logs.append({
                            "action": "cache_articles_from_web_search",
                            "query": search_query,
                            "error": str(e),
                        })

            # ---------- 3.4 合并、去重、相关性过滤 ----------
            combined = local_articles + targeted_articles + web_articles
            combined = [a for a in combined if self._is_relevant_to_area(a, area)]
            unique: list[dict[str, Any]] = []
            for article in combined:
                if not self._law_already_in(article, unique) and not self._law_already_in(article, discovered_laws):
                    unique.append(article)

            # ---------- 3.5 生成审查要点并写入图（每个领域最多取最相关 1 条） ----------
            for article in unique[:1]:
                article_text = article.get("article_text", "")
                if len(article_text) < 20:
                    continue
                t0 = time.time()
                review_points = await self._generate_review_points(article)
                print(f"[LR area {idx} {time.time()-t0:.2f}s] review points done, law={article.get('law_name', '')[:15]} {article.get('article_number', '')}, points={len(review_points)}")
                law_node = {
                    "law_name": article.get("law_name", ""),
                    "article_number": article.get("article_number", ""),
                    "article_title": article.get("article_title", ""),
                    "article_text": article_text,
                    "locator": article.get("locator", ""),
                    "review_points": review_points,
                    "source": article.get("source", "local"),
                }
                discovered_laws.append(law_node)
                session_graph.add_node(
                    node_type="Law",
                    properties=law_node,
                )
            print(f"[LR area {idx} total {time.time()-t0_area:.2f}s] area done, unique={len(unique)}, discovered_now={len(discovered_laws)}")

        areas_cost = time.time() - t0_total
        print(f"[LR {areas_cost:.2f}s] all areas done, total discovered={len(discovered_laws)}")

        # 4. 如果没有发现任何法条，至少补充通用法律原则节点
        if not discovered_laws:
            general_law = {
                "law_name": "通用法律原则",
                "article_number": "诚实信用与公平原则",
                "article_title": "",
                "article_text": "民事主体从事民事活动，应当遵循公平原则，合理确定各方的权利和义务。",
                "review_points": [
                    "权利义务是否明显失衡",
                    "是否存在免除己方责任、加重对方责任的条款",
                    "违约责任是否显著高于实际损失",
                ],
                "source": "fallback",
            }
            discovered_laws.append(general_law)
            session_graph.add_node(node_type="Law", properties=general_law)

        # 5. 生成动态审查清单：根据合同类型、推断领域和已发现法条，生成本次审查重点
        t0 = time.time()
        review_checklist = await self._generate_review_checklist(
            contract_text, contract_type, legal_areas, discovered_laws, risk_signals
        )
        checklist_cost = time.time() - t0
        print(f"[LR {checklist_cost:.2f}s] checklist done, items={len(review_checklist)}")

        return {
            "output": {"discovered_count": len(discovered_laws)},
            "discovered_laws": discovered_laws,
            "review_checklist": review_checklist,
            "risk_signals": risk_signals,
            "logs": self.logs,
        }

    def _build_contract_text(self, chunks: list[dict[str, Any]], max_chars: int = 3500) -> str:
        """把 chunks 拼接成一段可控长度的合同文本。"""
        texts = []
        current_len = 0
        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            if current_len + len(text) > max_chars:
                remain = max_chars - current_len
                if remain > 50:
                    texts.append(text[:remain])
                break
            texts.append(text)
            current_len += len(text)
        return "\n".join(texts)

    async def _infer_areas_and_signals(
        self,
        contract_text: str,
        contract_type: str,
    ) -> dict[str, Any]:
        """
        合并推断：一次 LLM 调用同时返回法律领域和风险信号。

        相比分别调用 _infer_legal_areas 和 _infer_risk_signals，
        可减少约 1 次 LLM 调用，同时保持输出质量。
        """
        prompt = self._build_combined_inference_prompt(contract_text, contract_type)

        for attempt in range(2):
            try:
                response = await self.llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1500,
                )
            except Exception as e:
                self.logs.append({"action": "infer_areas_and_signals", "attempt": attempt, "error": str(e)})
                continue

            areas, signals = self._parse_combined_output(response)
            areas = self._filter_inferred_areas(areas, contract_type)
            if areas or signals:
                return {"legal_areas": areas, "risk_signals": signals}

            self.logs.append({
                "action": "infer_areas_and_signals",
                "attempt": attempt,
                "error": "无法从 LLM 输出中解析法律领域和风险信号",
                "raw": (response or "")[:500],
            })
            prompt = self._build_combined_retry_prompt(contract_text, contract_type)

        # 两次都失败，使用基于合同类型的兜底领域和空风险信号
        return {
            "legal_areas": self._fallback_legal_areas(contract_type),
            "risk_signals": [],
        }

    def _parse_combined_output(
        self,
        text: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """解析合并输出，按标记分为法律领域部分和风险信号部分。"""
        if not text:
            return [], []

        area_part = text
        signal_part = ""

        markers = ["===风险信号===", "===风险===", "发现的风险信号", "风险信号："]
        for marker in markers:
            if marker in text:
                parts = text.split(marker, 1)
                area_part = parts[0]
                signal_part = parts[1]
                break

        areas = self._parse_area_text_output(area_part)
        signals = self._parse_signal_text_output(signal_part)
        return areas, signals

    def _build_combined_inference_prompt(self, contract_text: str, contract_type: str) -> str:
        """构造合并推断提示词（法律领域 + 风险信号）。"""
        return COMBINED_INFERENCE_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            contract_text=contract_text,
        )

    def _build_combined_retry_prompt(self, contract_text: str, contract_type: str) -> str:
        """构造合并推断重试提示词。"""
        return COMBINED_RETRY_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            contract_text=contract_text,
        )

    def _filter_inferred_areas(
        self,
        areas: list[dict[str, Any]],
        contract_type: str,
    ) -> list[dict[str, Any]]:
        """
        对 LLM 推断的法律领域做后处理：去重、过滤明显不相关的领域。
        规则基于中国法律的适用范围，但保留 LLM 明确关联的领域，以支持新类型合同的泛化推断。
        """
        if not areas:
            return areas

        # 去重：按 area + law_name + article_number
        seen: set[str] = set()
        unique_areas: list[dict[str, Any]] = []
        for area in areas:
            key = "|".join([
                area.get("area", ""),
                area.get("law_name", ""),
                area.get("article_number", ""),
            ])
            if key not in seen:
                seen.add(key)
                unique_areas.append(area)

        # 法律名称 -> 兼容的合同类型（精确匹配或子串匹配）
        # 仅在 LLM 推断明显不相关时才过滤， keywords 中出现核心特征则保留
        law_scope_map: dict[str, set[str]] = {
            "中华人民共和国劳动合同法": {"劳动合同"},
            "中华人民共和国劳动法": {"劳动合同"},
            "中华人民共和国公司法": {"股权转让协议"},
            "最高人民法院关于审理民间借贷案件适用法律若干问题的规定": {"借款合同"},
            "中华人民共和国消费者权益保护法": {"买卖合同"},
        }

        # 法律核心特征词：只要关键词包含这些词，就保留该法律
        law_feature_keywords: dict[str, set[str]] = {
            "中华人民共和国劳动合同法": {"劳动合同", "试用期", "劳动报酬", "工作时间", "加班费", "竞业限制", "服务期", "社保", "经济补偿", "解除合同"},
            "中华人民共和国劳动法": {"劳动", "工时", "加班", "工资", "休假", "社保"},
            "中华人民共和国公司法": {"股权", "股东", "公司", "出资", "股权转让", "变更登记", "股东名册"},
            "最高人民法院关于审理民间借贷案件适用法律若干问题的规定": {"借款", "借贷", "利率", "利息", "逾期", "砍头息", "LPR"},
            "中华人民共和国消费者权益保护法": {"消费者", "买卖", "三包", "退货", "欺诈"},
        }

        filtered: list[dict[str, Any]] = []
        for area in unique_areas:
            law_name = (area.get("law_name", "") or "").strip()
            if not law_name:
                filtered.append(area)
                continue

            # 检查该法律是否明显超出当前合同类型的适用范围
            incompatible = False
            keywords = (area.get("keywords", "") or "").lower()
            for scope_law, scope_types in law_scope_map.items():
                if scope_law in law_name or law_name in scope_law:
                    if contract_type not in scope_types:
                        # 放宽：如果关键词里明确包含该法律的核心特征，仍保留
                        feature_words = law_feature_keywords.get(scope_law, set())
                        if not any(k in keywords for k in feature_words):
                            incompatible = True
                    break

            if incompatible:
                self.logs.append({
                    "action": "filter_inferred_areas",
                    "removed": area,
                    "reason": f"{contract_type} 通常不适用该法律",
                })
                continue
            filtered.append(area)

        # 过滤关键词为空或领域名过短的
        return [a for a in filtered if a.get("keywords") and len(a.get("area", "")) >= 2]

    def _parse_signal_text_output(self, text: str) -> list[dict[str, Any]]:
        """解析风险信号文本输出。"""
        signals: list[dict[str, Any]] = []
        if not text:
            return signals

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = re.sub(r"^\s*(?:\d+[.．]\s*|-\s*|•\s*)", "", line)

            if "无明显风险信号" in line or line in ("无", "无。", "none", "None"):
                continue

            if "|" not in line:
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                signal = parts[0]
                law_area = parts[1]
                keywords = re.sub(r"[、，,;；]+", " ", " ".join(parts[2:]))
                if signal and keywords and len(signal) >= 4:
                    signals.append({
                        "signal": signal,
                        "law_area": law_area,
                        "keywords": keywords,
                        "indicators": [k for k in keywords.split() if len(k) >= 2][:5],
                    })
            elif len(parts) == 2:
                signal = parts[0]
                keywords = re.sub(r"[、，,;；]+", " ", parts[1])
                if signal and keywords and len(signal) >= 4:
                    signals.append({
                        "signal": signal,
                        "law_area": "",
                        "keywords": keywords,
                        "indicators": [k for k in keywords.split() if len(k) >= 2][:5],
                    })

        return signals

    def _format_signals_context(self, risk_signals: list[dict[str, Any]]) -> str:
        """把风险信号格式化为上下文文本。"""
        if not risk_signals:
            return "（本次未识别到特定风险信号）"
        return "\n".join(
            f"- {s.get('signal', '')}（涉及：{s.get('law_area', '')}；关键词：{s.get('keywords', '')}）"
            for s in risk_signals[:8]
        )

    def _has_strong_risk_signals(self, risk_signals: list[dict[str, Any]]) -> bool:
        """
        判断风险信号列表中是否存在足够强的风险信号。

        强风险信号标准：信号描述中包含明确的负面法律评价词（如违法、无效、过高、显失公平等）。
        仅提及领域关键词（如“利率”“违约金”）而无负面评价的信号视为弱信号。
        """
        if not risk_signals:
            return False
        strong_indicators = {
            "违法", "无效", "过高", "超限", "超过", "显失公平", "排除", "免除",
            "加重", "欺诈", "侵权", "违反", "不当", "不合理", "不公", "冲突",
            "规避", "剥夺", "限制", "隐瞒", "恶意", "显失", "畸高", "暴利",
        }
        for signal in risk_signals:
            signal_text = (signal.get("signal", "") or "").lower()
            if any(indicator in signal_text for indicator in strong_indicators):
                return True
        return False

    def _area_matches_risk_signal(
        self,
        area: dict[str, Any],
        risk_signals: list[dict[str, Any]],
    ) -> bool:
        """
        判断当前法律领域是否与某个强风险信号相关联。

        匹配条件：
        1. 风险信号的关键词/涉及领域与当前 area 的关键词或领域名有重叠；
        2. 该信号本身已被 _has_strong_risk_signals 判定为强信号（含负面法律评价词）。
        """
        if not risk_signals:
            return False
        area_keywords = set((area.get("keywords", "") or "").lower().split())
        area_name = (area.get("area", "") or "").lower()
        area_law = (area.get("law_name", "") or "").lower()

        strong_indicators = {
            "违法", "无效", "过高", "超限", "超过", "显失公平", "排除", "免除",
            "加重", "欺诈", "侵权", "违反", "不当", "不合理", "不公", "冲突",
            "规避", "剥夺", "限制", "隐瞒", "恶意", "显失", "畸高", "暴利",
        }

        for signal in risk_signals:
            signal_text = (signal.get("signal", "") or "").lower()
            if not any(indicator in signal_text for indicator in strong_indicators):
                continue

            signal_keywords = set((signal.get("keywords", "") or "").lower().split())
            signal_area = (signal.get("law_area", "") or "").lower()

            # 关键词交集 或 领域名/法律名出现在信号中
            if area_keywords & signal_keywords:
                return True
            if area_name and area_name in signal_text:
                return True
            if area_name and area_name in signal_area:
                return True
            if area_law and area_law in signal_area:
                return True

        return False

    def _parse_area_text_output(self, text: str) -> list[dict[str, Any]]:
        """
        从文本输出中解析法律领域、法律名称、条款号和关键词。
        每行格式：领域 | 法律名称 | 条款号 | 关键词
        也兼容旧格式：领域 | 关键词
        """
        areas: list[dict[str, Any]] = []
        if not text:
            return areas

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 去掉可能的序号前缀
            line = re.sub(r"^\s*(?:\d+[.．]\s*|-\s*|•\s*)", "", line)
            if "|" not in line:
                continue

            parts = [p.strip() for p in line.split("|")]
            # 兼容 2 段或 4 段格式
            if len(parts) == 2:
                area = parts[0]
                keywords = re.sub(r"[、，,;；]+", " ", parts[1])
                if area and keywords:
                    areas.append({
                        "area": area,
                        "law_name": "",
                        "article_number": "",
                        "keywords": keywords,
                    })
            elif len(parts) >= 4:
                area = parts[0]
                law_name = parts[1]
                article_number = parts[2]
                keywords = re.sub(r"[、，,;；]+", " ", " ".join(parts[3:]))
                if area and keywords:
                    areas.append({
                        "area": area,
                        "law_name": law_name,
                        "article_number": article_number,
                        "keywords": keywords,
                    })

        return areas

    def _fallback_legal_areas(self, contract_type: str) -> list[dict[str, Any]]:
        """当 LLM 推断失败时，根据合同类型返回兜底法律领域。"""
        fallback_map: dict[str, list[dict[str, Any]]] = {
            "劳动合同": [
                {"area": "试用期", "law_name": "中华人民共和国劳动合同法", "article_number": "第十九条", "keywords": "劳动合同法 试用期 上限"},
                {"area": "试用期工资", "law_name": "中华人民共和国劳动合同法", "article_number": "第二十条", "keywords": "试用期 工资 百分之八十"},
                {"area": "工作时间", "law_name": "中华人民共和国劳动法", "article_number": "第三十六条", "keywords": "劳动法 工作时间 八小时"},
                {"area": "加班费", "law_name": "中华人民共和国劳动法", "article_number": "第四十四条", "keywords": "加班 加班费 工资报酬"},
                {"area": "社会保险", "law_name": "中华人民共和国社会保险法", "article_number": "第十条", "keywords": "社会保险 养老保险 缴纳"},
                {"area": "竞业限制", "law_name": "中华人民共和国劳动合同法", "article_number": "第二十三条", "keywords": "竞业限制 经济补偿"},
            ],
            "租赁合同": [
                {"area": "租赁期限", "law_name": "中华人民共和国民法典", "article_number": "第七百零五条", "keywords": "民法典 租赁期限 二十年"},
                {"area": "转租", "law_name": "中华人民共和国民法典", "article_number": "第七百一十六条", "keywords": "民法典 转租 出租人同意"},
                {"area": "维修义务", "law_name": "中华人民共和国民法典", "article_number": "第七百一十二条", "keywords": "民法典 出租人 维修义务"},
                {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            ],
            "借款合同": [
                {"area": "利率上限", "law_name": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定", "article_number": "第二十五条", "keywords": "民间借贷 利率 合同成立时 LPR"},
                {"area": "逾期利率", "law_name": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定", "article_number": "第二十八条", "keywords": "民间借贷 逾期利率 约定"},
                {"area": "砍头息", "law_name": "中华人民共和国民法典", "article_number": "第六百七十条", "keywords": "借款 利息 预先扣除"},
                {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            ],
            "买卖合同": [
                {"area": "质量标准", "law_name": "中华人民共和国民法典", "article_number": "第六百一十五条", "keywords": "民法典 标的物 质量"},
                {"area": "验收", "law_name": "中华人民共和国民法典", "article_number": "第六百二十条", "keywords": "民法典 买受人 检验期限"},
                {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            ],
            "保密协议": [
                {"area": "商业秘密", "law_name": "中华人民共和国反不正当竞争法", "article_number": "第九条", "keywords": "商业秘密 经营者 不正当手段"},
                {"area": "保密义务", "law_name": "中华人民共和国民法典", "article_number": "第五百零一条", "keywords": "合同订立 商业秘密 保密义务"},
                {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            ],
            "股权转让协议": [
                {"area": "股权转让", "law_name": "中华人民共和国公司法", "article_number": "第八十六条", "keywords": "公司法 股权转让 变更登记"},
                {"area": "股东名册", "law_name": "中华人民共和国公司法", "article_number": "第八十七条", "keywords": "公司法 股东名册 记载"},
                {"area": "瑕疵出资", "law_name": "中华人民共和国公司法", "article_number": "第八十八条", "keywords": "公司法 出资 股权转让"},
                {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            ],
            "技术服务合同": [
                {"area": "技术服务合同", "law_name": "中华人民共和国民法典", "article_number": "第八百八十五条", "keywords": "技术服务合同 工作成果 验收"},
                {"area": "知识产权归属", "law_name": "中华人民共和国民法典", "article_number": "第八百八十五条", "keywords": "技术服务合同 知识产权 归属"},
                {"area": "委托开发", "law_name": "中华人民共和国著作权法", "article_number": "第十九条", "keywords": "著作权 委托创作 归属"},
                {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            ],
        }
        return fallback_map.get(contract_type, [
            {"area": "合同权利义务", "law_name": "中华人民共和国民法典", "article_number": "第五百零九条", "keywords": "民法典 合同 权利义务"},
            {"area": "违约责任", "law_name": "中华人民共和国民法典", "article_number": "第五百八十五条", "keywords": "民法典 违约金 过高"},
            {"area": "公平原则", "law_name": "中华人民共和国民法典", "article_number": "第六条", "keywords": "公平原则 诚实信用"},
        ])

    def _review_point_cache_key(self, article: dict[str, Any]) -> str:
        """生成审查要点缓存 key：优先用法律名称+条款号，辅以文本摘要。"""
        law_name = (article.get("law_name", "") or "").strip("《》")
        article_number = article.get("article_number", "")
        article_text = article.get("article_text", "")
        text_hash = ""
        if article_text:
            text_hash = hashlib.md5(article_text[:200].encode("utf-8")).hexdigest()[:8]
        return f"{law_name}|{article_number}|{text_hash}"

    async def _generate_review_points(self, article: dict[str, Any]) -> list[str]:
        """
        根据法条原文生成审查要点。

        优化：
        1. 先查类级缓存，命中直接返回；
        2. 再查高频法条模板，命中直接返回；
        3. 最后才调用 LLM，并将结果写入缓存。
        """
        law_name = article.get("law_name", "")
        article_number = article.get("article_number", "")
        article_text = article.get("article_text", "")

        if not article_text or len(article_text) < 10:
            return []

        cache_key = self._review_point_cache_key(article)

        # 1. 类级缓存命中
        cached = LegalResearchAgent._review_point_cache.get(cache_key)
        if cached:
            self.logs.append({
                "action": "generate_review_points",
                "cache_hit": True,
                "law_name": law_name,
                "article_number": article_number,
            })
            return cached[:3]

        # 2. 高频法条模板命中（用 law_name + article_number 做 key，去掉书名号）
        normalized_law_name = (law_name or "").strip("《》")
        template_key = f"{normalized_law_name}|{article_number}"
        template_points = LegalResearchAgent.REVIEW_POINT_TEMPLATES.get(template_key)
        if template_points:
            LegalResearchAgent._review_point_cache[cache_key] = template_points
            self.logs.append({
                "action": "generate_review_points",
                "template_hit": True,
                "law_name": law_name,
                "article_number": article_number,
            })
            return template_points[:3]

        # 3. LLM 生成
        prompt = REVIEW_POINTS_PROMPT_TEMPLATE.format(
            law_name=law_name,
            article_number=article_number,
            article_text=article_text[:1000],
        )

        for attempt in range(2):
            try:
                response = await self.llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": "你是专业的合同审查助手，只输出编号列表。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1024,
                )
            except Exception as e:
                self.logs.append({"action": "generate_review_points", "error": str(e)})
                continue

            points = self._parse_numbered_list(response)
            points = [p for p in points if self._is_valid_review_point(p)]
            if points:
                LegalResearchAgent._review_point_cache[cache_key] = points
                return points[:3]

            # 第二次尝试使用更简单的提示
            prompt = REVIEW_POINTS_RETRY_PROMPT_TEMPLATE.format(
                law_name=law_name,
                article_number=article_number,
                article_text=article_text[:600],
            )

        # 4. LLM 失败兜底：从法条原文中提取前 1-2 个完整句子作为审查要点
        fallback_points = self._fallback_review_points(article_text)
        if fallback_points:
            LegalResearchAgent._review_point_cache[cache_key] = fallback_points
        return fallback_points

    def _fallback_review_points(self, article_text: str, max_points: int = 2) -> list[str]:
        """LLM 不可用时，从法条文本中提取完整句子作为兜底审查要点。"""
        if not article_text:
            return []
        # 清理 markdown 链接、多余空格和英文标点
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", article_text)
        text = re.sub(r"\*+", "", text)
        text = re.sub(r"\s+", " ", text)

        # 按常见中文句末标点拆分
        sentences = re.split(r"(?<=[。；!！?？])\s+", text)
        results = []
        for s in sentences:
            s = s.strip()
            # 只保留长度适中、包含足够中文字符、且不是纯英文的句子
            if len(s) >= 15 and len(re.findall(r"[\u4e00-\u9fa5]", s)) >= 8:
                latin_chars = len(re.findall(r"[a-zA-Z]", s))
                if latin_chars / max(len(s), 1) > 0.3:
                    continue
                results.append(s)
            if len(results) >= max_points:
                break
        return results

    def _is_valid_review_point(self, point: str) -> bool:
        """校验 LLM 生成的审查要点是否可读、可用。"""
        if not point:
            return False
        # 过滤掉包含明显乱码/重复英文单词的内容
        garbage_patterns = [
            r"party\s+party",
            r"contractions",
            r"seconduity",
            r"contraints",
            r"secondry",
            r"performanc",
        ]
        for pattern in garbage_patterns:
            if re.search(pattern, point, re.IGNORECASE):
                return False
        # 过滤掉 markdown 链接
        if re.search(r"\[([^\]]+)\]\([^)]+\)", point):
            return False
        # 拉丁字母占比过高时视为不合格
        latin_chars = len(re.findall(r"[a-zA-Z]", point))
        if latin_chars / max(len(point), 1) > 0.3:
            return False
        return True

    def _parse_numbered_list(self, text: str) -> list[str]:
        """从编号列表文本中提取条目。"""
        if not text:
            return []
        # 匹配 1. / 1、/ (1) / 1） 等编号
        pattern = r"(?:^|\n)\s*(?:\d+[.．、)）]|\([\d一二三四五]\)|（[\d一二三四五]）)\s*([^\n]+)"
        matches = re.findall(pattern, text)
        results = []
        for m in matches:
            item = m.strip()
            # 过滤掉常见无效内容
            if not item or item in ("无", "无。", "none", "None"):
                continue
            if len(item) < 5:
                continue
            # 过滤掉包含过多非中文字符的条目
            chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", item))
            if chinese_chars < 3:
                continue
            results.append(item)
        return results

    async def _generate_review_checklist(
        self,
        contract_text: str,
        contract_type: str,
        legal_areas: list[dict[str, Any]],
        discovered_laws: list[dict[str, Any]],
        risk_signals: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """
        根据合同内容和发现的法律，生成本次审查的动态重点清单。

        优化：当已检索到充分法律依据时，直接使用基于法条 review_points 的兜底清单，
        避免不必要的 LLM 调用；否则调用 LLM 生成更贴合合同内容的清单。

        新增快速路径：当法律依据不足且整体风险信号较弱时，也跳过 LLM，直接返回兜底清单。
        这能在合法合同上避免一次昂贵的 LLM 调用。
        """
        risk_signals = risk_signals or []

        # 若法律依据充分，直接基于法条 review_points 生成清单，减少 LLM 调用
        if len(discovered_laws) >= 3 and len(legal_areas) >= 3:
            self.logs.append({
                "action": "generate_review_checklist",
                "fallback_reason": "法律依据充分，跳过 LLM",
                "discovered_laws_count": len(discovered_laws),
                "legal_areas_count": len(legal_areas),
            })
            return self._fallback_checklist(contract_type, legal_areas, discovered_laws)

        # 快速路径：法律依据不足且风险信号弱，跳过 LLM checklist
        if not self._has_strong_risk_signals(risk_signals):
            self.logs.append({
                "action": "generate_review_checklist",
                "fallback_reason": "风险信号弱且法律依据不足，跳过 LLM",
                "discovered_laws_count": len(discovered_laws),
                "legal_areas_count": len(legal_areas),
                "risk_signals_count": len(risk_signals),
            })
            return self._fallback_checklist(contract_type, legal_areas, discovered_laws)

        area_summary = "、".join(a.get("area", "") for a in legal_areas[:5])
        law_summary = "\n".join(
            f"- {law.get('law_name', '')} {law.get('article_number', '')}: "
            f"{law.get('article_text', '')[:150]}"
            for law in discovered_laws[:5]
        )

        prompt = CHECKLIST_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            area_summary=area_summary,
            contract_text=contract_text[:1500],
            law_summary=law_summary,
        )

        for attempt in range(2):
            try:
                response = await self.llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": "你是专业的合同审查助手，只输出中文编号列表。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                )
            except Exception as e:
                self.logs.append({"action": "generate_review_checklist", "error": str(e)})
                continue

            checklist = self._parse_numbered_list(response)
            if checklist:
                return checklist[:8]

            prompt = CHECKLIST_RETRY_PROMPT_TEMPLATE.format(
                contract_type=contract_type,
                contract_text=contract_text[:1000],
            )

        # LLM 失败兜底：根据已发现的法律领域和法条生成基础检查清单
        return self._fallback_checklist(contract_type, legal_areas, discovered_laws)

    def _fallback_checklist(
        self,
        contract_type: str,
        legal_areas: list[dict[str, Any]],
        discovered_laws: list[dict[str, Any]],
    ) -> list[str]:
        """LLM 不可用时，基于推断领域和法条生成兜底检查清单。"""
        checklist: list[str] = []
        area_names = [a.get("area", "") for a in legal_areas if a.get("area")]
        if area_names:
            checklist.append(f"核对合同是否涉及以下法律领域：{'、'.join(area_names[:5])}")

        for law in discovered_laws[:5]:
            review_points = law.get("review_points", [])
            for point in review_points[:1]:
                if point and isinstance(point, str):
                    checklist.append(point[:100])

        # 通用兜底项
        if contract_type != "通用":
            checklist.append(f"检查该{contract_type}是否具备该类合同通常应有的关键条款")
        checklist.append("检查是否存在明显免除一方责任、加重对方责任的条款")
        checklist.append("检查违约金、赔偿金额是否显著高于实际损失")

        # 去重并限制数量
        seen: set[str] = set()
        unique: list[str] = []
        for item in checklist:
            if item and item not in seen:
                seen.add(item)
                unique.append(item)
            if len(unique) >= 8:
                break
        return unique

    def _law_already_in(self, article: dict[str, Any], articles: list[dict[str, Any]]) -> bool:
        """检查法条是否已存在于列表中（按 law_name + article_number 判断）。"""
        name = article.get("law_name", "")
        number = article.get("article_number", "")
        for existing in articles:
            if (
                existing.get("law_name") == name
                and existing.get("article_number") == number
            ):
                return True
        return False

    def _is_relevant_to_area(self, article: dict[str, Any], area: dict[str, Any]) -> bool:
        """
        判断检索到的法条是否与推断的法律领域相关。
        采用宽松策略：只要法条名称、标题或正文包含领域关键词，即视为相关。
        """
        law_name = (article.get("law_name", "") or "").lower()
        article_number = (article.get("article_number", "") or "").lower()
        article_title = (article.get("article_title", "") or "").lower()
        article_text = (article.get("article_text", "") or "").lower()

        area_name = (area.get("area", "") or "").lower()
        area_law_name = (area.get("law_name", "") or "").lower()
        keywords = (area.get("keywords", "") or "").lower()

        # 如果推断出了具体法律名称，优先匹配法律名称
        if area_law_name:
            # 法律名称可以是全称或简称，例如"民法典"匹配"中华人民共和国民法典"
            if area_law_name in law_name or law_name in area_law_name:
                return True

        # 收集所有待匹配词（领域名 + 关键词）
        raw_tokens = f"{area_name} {keywords}"
        tokens = [t for t in re.split(r"\s+", raw_tokens) if len(t) >= 2]

        # 过滤掉过于宽泛的词
        stopwords = {"法律", "合同", "规定", "条款", "相关", "纠纷", "诉讼", "第条"}
        tokens = [t for t in tokens if t not in stopwords]

        # 在法条各字段中匹配
        combined_text = f"{law_name} {article_number} {article_title} {article_text}"
        matched = sum(1 for token in tokens if token in combined_text)

        # 命中至少一个关键词即视为相关；若只有一个 token，要求必须命中
        if len(tokens) == 0:
            return True
        if len(tokens) == 1:
            return matched >= 1
        return matched >= 1

    def _parse_json_output(self, text: str) -> Any:
        """解析 LLM 的 JSON 输出，兼容 markdown 代码块。"""
        text = (text or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 兜底：尝试提取第一个 { ... } 或 [ ... ]
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        return text
