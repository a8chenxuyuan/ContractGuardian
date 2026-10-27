"""
文件：app/review/pipeline.py
作用：Coordinator 是 AI 审查引擎的调度中心，负责控制整个合同审查流程。

需要实现的类与函数：

1. class ReviewCoordinator
   整个 Coordinator 的核心类，持有 SessionGraph、AgentBus、配置和工具注册表。

2. def __init__(self, config: dict)
   初始化 Coordinator。
   参数：
     - config：包含 LLM 配置、工具注册表、Agent 列表、最大轮次等
   逻辑：
     - 初始化 SessionGraph 工厂
     - 初始化 AgentBus
     - 注册所有 Agent 和工具
     - 加载法律知识库检索器（Qdrant + Neo4j）

3. async def run_review(
       self,
       contract_id: int,
       chunks: list[dict],
       section_tree: dict,
       vector_index: str,
   ) -> dict
   入口函数，后端 Celery 任务调用它启动审查。
   参数：
     - contract_id：合同 ID
     - chunks：Chunk 列表，每个 Chunk 包含 text / page / bbox / section_path
     - section_tree：合同章节树
     - vector_index：Qdrant collection 名称
   返回：
     - dict：包含 findings（风险列表）、graph_data（SessionGraph 序列化）、human_review_items（人工复核项）
   逻辑：
     - 创建 SessionGraph 根节点
     - 按顺序执行七阶段管线
     - 每个阶段通过 AgentBus 发布 phase_changed 事件
     - 最终返回审查结果

4. async def _route(self, session_graph, chunks) -> list[tuple]
   Route 阶段：根据 Chunk 内容特征决定派发给哪些 Agent，并分配风险等级 L1/L2/L3。
   逻辑：
     - 关键词初筛：匹配"试用期""违约金""竞业限制""社保"等高风险关键词
     - 向量相似度确认：用 BGE-M3 计算 Chunk 与已知风险模板的相似度
     - 返回 (chunk, agent_names, risk_level) 三元组列表

5. async def _preload(self, session_graph, chunks, section_tree)
   Preload 阶段：预加载共享上下文。
   逻辑：
     - 把 Chunk 写入 SessionGraph 作为 Clause 节点
     - 预加载基础法律知识（如劳动合同法第 17、19、22 条等）
     - 预加载历史相似审查结果（可选）

6. async def _execute(self, session_graph, assignments)
   Execute 阶段：并行执行多个 Agent。
   逻辑：
     - 使用 asyncio.gather 或线程池并行启动 Agent
     - 每个 Agent 内部运行独立的 ReAct 循环
     - Agent 发现风险时写入 SessionGraph 并通过 AgentBus 广播

7. async def _merge_and_link(self, session_graph)
   Merge+Link 阶段：合并重复风险，发现跨条款组合风险。
   逻辑：
     - 去重：根据 risk_type + clause_text 相似度合并
     - 关联：建立 Clause → RELATES_TO → Clause 边
     - 冲突：建立 Clause → CONTRADICTS → Clause 边
     - 动态调整风险等级

8. async def _legal_verify(self, session_graph)
   LegalVerify 阶段：验证所有 Risk → Law 边的法律依据。
   逻辑：
     - 调用 LegalVerifyAgent
     - 对每个法条在 Qdrant/Neo4j 中核对
     - 无法验证的降低置信度或标记为人工复核

9. async def _debate(self, session_graph)
   Debate 阶段：对高风险或低置信度发现进行正反辩论。
   逻辑：
     - 调用 DebateAgent
     - 正方论证是风险，反方论证不是风险或存在例外
     - Coordinator 根据辩论结果裁决保留/调整/撤销

10. async def _triage(self, session_graph) -> tuple[list, list]
    Triage 阶段：分流输出。
    返回：
      - findings：最终风险列表（必须改 / 需复核 / 优化建议）
      - human_review_items：需要人工复核的项
    逻辑：
      - 按 level 和 confidence 分类
      - 低置信度、组合风险、Agent 冲突项进入人工复核队列

实现提示：
- 使用自定义 Coordinator 管理状态流转，每个阶段的具体逻辑自定义实现
- 使用 Pydantic 模型校验 Agent 输出
- 控制最大 ReAct 轮次，防止 token 过度消耗
- 每个阶段都要发布 SSE 事件，方便前端展示进度
"""

# ============================================================
# 下面是 ReviewCoordinator 的代码框架，供你逐行手敲学习。
# 每一行或每一段都有中文注释，说明它是做什么的。
# 注意：这只是一个可直接填充的骨架，具体 LLM 调用、
#       向量检索、图数据库查询需要你自己接入真实实现。
# ============================================================

# 1. 导入需要用到的标准库和第三方库
import asyncio
import json
import re
import time
import uuid
from typing import Any

# app.agentkit.bus 是消息总线
from app.agentkit.bus import AgentBus

# app.agentkit.session_graph 是共享记忆图
from app.agentkit.session_graph import SessionGraph

# LLM 客户端
from app.llm import get_llm_client

# 向量存储
from app.rag.vector_store import VectorStoreError, get_vector_store
from app.review.agents.balance import BalanceAgent
from app.review.agents.blind_spot import BlindSpotAgent
from app.review.agents.cross_reference import CrossReferenceAgent
from app.review.agents.debate import DebateAgent
from app.review.agents.human_review import HumanReviewAgent
from app.review.agents.industry_compliance import IndustryComplianceAgent
from app.review.agents.legal_basis import LegalBasisAgent
from app.review.agents.legal_research import LegalResearchAgent
from app.review.agents.legal_verify import LegalVerifyAgent
from app.review.agents.missing_clause import MissingClauseAgent
from app.review.agents.risk_review import RiskReviewAgent
from app.review.agents.suggestion import SuggestionAgent

# 导入所有内置 Agent，后面会逐个注册
from app.review.agents.term_extraction import TermExtractionAgent
from app.review.prompts.pipeline import CROSS_CLAUSE_PROMPT_TEMPLATE


# 2. 定义 ReviewCoordinator 类
class ReviewCoordinator:
    """
    审查调度中心。
    作用：控制一次合同审查的完整流程，像工厂里的工头。
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        初始化 Coordinator。
        config 里可以传 LLM 配置、工具注册表、Agent 列表、最大轮次等。
        如果外部没传，就用默认配置。
        """
        # 保存配置，后续 Agent 和工具都会用到
        self.config = config or {}

        # 默认开启 LLM 跨条款兜底检测
        self.config.setdefault("enable_llm_cross_clause_fallback", True)

        # 最大 ReAct 轮次，防止某个 Agent 陷入死循环或 token 爆掉（可按环境配置）
        from app.core.config import get_settings

        self.max_turns = self.config.get("max_turns", get_settings().AGENT_MAX_TURNS)

        # 创建工具注册表：工具名 -> 工具函数
        # 后面 _execute 阶段，Agent 会通过名字从这里查找工具
        self.tools: dict[str, Any] = {}
        # 注册工具，具体每个工具怎么写在 tools/ 目录下
        self._register_tools()

        # 创建 Agent 注册表：Agent 名 -> Agent 实例
        self.agents: dict[str, Any] = {}
        # 注册所有内置 Agent
        self._register_agents()

    def _register_tools(self) -> None:
        """
        注册所有工具函数。
        工具通过 @register_tool 装饰器自登记到 TOOL_REGISTRY，
        这里导入即触发登记，再从注册表统一构建本协调器的工具表。
        """
        # 导入即执行各工具文件顶部的 @register_tool 登记
        from app.agentkit.tool_registry import TOOL_REGISTRY
        from app.review.tools.check_cross_reference import check_cross_reference  # noqa: F401
        from app.review.tools.compare_with_template import compare_with_template  # noqa: F401
        from app.review.tools.extract_obligations import extract_obligations  # noqa: F401
        from app.review.tools.output_finding import output_finding  # noqa: F401
        from app.review.tools.query_knowledge_graph import query_knowledge_graph  # noqa: F401
        from app.review.tools.read_section import read_section  # noqa: F401
        from app.review.tools.search_document import search_document  # noqa: F401
        from app.review.tools.search_knowledge import search_knowledge  # noqa: F401
        from app.review.tools.validate_calculation import validate_calculation  # noqa: F401
        from app.review.tools.web_search import web_search  # noqa: F401

        # 注册表是唯一事实源：工具名 -> 函数对象
        self.tools = {name: spec.func for name, spec in TOOL_REGISTRY.items()}

    def _register_agents(self) -> None:
        """
        注册所有 Agent。
        每个 Agent 初始化时拿到：自己的名字、系统提示词、可调用的工具、最大轮次。
        """
        # TermExtractionAgent 不需要太多工具，主要是提取
        self.agents["term_extraction"] = TermExtractionAgent(
            tools={"read_section": self.tools["read_section"]}
        )

        # RiskReviewAgent 需要查法律、查合同、输出发现
        self.agents["risk_review"] = RiskReviewAgent(
            tools={
                "search_knowledge": self.tools["search_knowledge"],
                "search_document": self.tools["search_document"],
                "read_section": self.tools["read_section"],
                "output_finding": self.tools["output_finding"],
            }
        )

        # LegalResearchAgent：在 RiskReview 之前动态推断适用法律并检索法条
        self.agents["legal_research"] = LegalResearchAgent(
            tools={
                "search_knowledge": self.tools["search_knowledge"],
                "web_search": self.tools["web_search"],
            }
        )

        # 其他 Agent 也类似，按需传入工具
        self.agents["missing_clause"] = MissingClauseAgent(
            tools={"read_section": self.tools["read_section"]}
        )
        self.agents["balance"] = BalanceAgent(
            tools={
                "extract_obligations": self.tools["extract_obligations"],
                "search_knowledge": self.tools["search_knowledge"],
                "output_finding": self.tools["output_finding"],
            }
        )
        self.agents["cross_reference"] = CrossReferenceAgent(
            tools={
                "check_cross_reference": self.tools["check_cross_reference"],
                "read_section": self.tools["read_section"],
            },
            use_function_calling=True,
        )
        self.agents["legal_basis"] = LegalBasisAgent(
            tools={
                "search_knowledge": self.tools["search_knowledge"],
                "query_knowledge_graph": self.tools["query_knowledge_graph"],
            }
        )
        self.agents["suggestion"] = SuggestionAgent(
            tools={
                "read_section": self.tools["read_section"],
                "search_knowledge": self.tools["search_knowledge"],
            }
        )
        self.agents["industry_compliance"] = IndustryComplianceAgent(
            tools={
                "search_knowledge": self.tools["search_knowledge"],
                "output_finding": self.tools["output_finding"],
            }
        )
        self.agents["legal_verify"] = LegalVerifyAgent(
            tools={
                "search_knowledge": self.tools["search_knowledge"],
                "web_search": self.tools["web_search"],
                "query_knowledge_graph": self.tools["query_knowledge_graph"],
            },
            use_function_calling=True,
        )
        self.agents["debate"] = DebateAgent(
            tools={
                "search_knowledge": self.tools["search_knowledge"],
                "search_document": self.tools["search_document"],
                "read_section": self.tools["read_section"],
            },
            use_function_calling=True,
        )
        self.agents["blind_spot"] = BlindSpotAgent(
            tools={"read_section": self.tools["read_section"]}
        )
        self.agents["human_review"] = HumanReviewAgent(tools={})

    async def run_review(
        self,
        contract_id: int,
        chunks: list[dict[str, Any]],
        section_tree: dict[str, Any],
        vector_index: str,
        contract_type: str = "通用",
        review_session_id: int | None = None,
    ) -> dict[str, Any]:
        """
        审查入口函数。
        后端 Celery 任务会调用这个函数启动一次完整审查。
        返回的结果会被写入数据库 review_sessions 表。

        参数 review_session_id：数据库 ReviewSession.id，
        用于让 AgentBus 与 SSEManager 使用同一个 Redis 频道。
        """
        # 生成唯一的审查会话 ID；如果外部传入 review_session_id，
        # 则优先使用它，保证 SSE 和 AgentBus 在同一频道
        session_id = review_session_id or (uuid.uuid4().int % (10**12))

        # 创建本次审查的共享记忆图，同时传入合同类型以支持配置化跨条款风险检测
        session_graph = SessionGraph(
            session_id=session_id,
            contract_id=contract_id,
            contract_type=contract_type,
        )

        # 创建消息总线，用于 Agent 之间广播事件
        # 同时把 redis_url 传进去，支持多 Worker 场景
        from app.core.config import get_settings
        agent_bus = AgentBus(
            session_id=session_id,
            redis_url=get_settings().REDIS_URL,
        )
        # 把 agent_bus 保存到 session_graph 的 metadata 里，方便 Agent 调用
        session_graph.set_bus(agent_bus)

        # trace 落盘：订阅事件流写入 logs/reviews/{session_id}.jsonl（事件协议 §4）
        from app.review.logger import ReviewLogger

        trace_logger = ReviewLogger(session_id)
        trace_logger.log_input(
            contract_text=chunks[0].get("text", "") if chunks else "",
            contract_type=contract_type,
            model=getattr(get_settings(), "LLM_MODEL", "unknown"),
        )
        await trace_logger.attach(agent_bus)

        # 构造上下文对象，所有 Agent 都能读到
        # 把 session_graph 也放进去，方便工具函数查询图
        context = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "vector_index": vector_index,
            "tools": self.tools,
            "max_turns": self.max_turns,
            "session_graph": session_graph,
            "chunks": chunks,
        }

        try:
            # ---------- LangGraph 编排（M3）：8 阶段由 StateGraph 驱动 ----------
            from app.review.graph import ReviewState, build_review_graph

            graph = build_review_graph(self)
            initial_state: ReviewState = {
                "contract_id": contract_id,
                "chunks": chunks,
                "section_tree": section_tree,
                "contract_type": contract_type,
                "review_session_id": review_session_id,
                "coordinator": self,
                "session_graph": session_graph,
                "agent_bus": agent_bus,
                "context": context,
                "costs": {},
            }
            t0 = time.time()
            print(f"[{t0}] run_review start (LangGraph)")
            final_state = await graph.ainvoke(initial_state)

            findings = final_state.get("findings", [])
            human_review_items = final_state.get("human_review_items", [])
            costs = final_state.get("costs", {})
            print(f"[{time.time()}] graph done, costs={ {k: round(v, 2) for k, v in costs.items()} }")

            # 计算风险统计 high / medium / low
            stats = {"high": 0, "medium": 0, "low": 0, "total": len(findings)}
            for f in findings:
                level = f.get("level", "low")
                if level in stats:
                    stats[level] += 1

            # 法条验证统计（可信度指标）
            law_verification = context.get("law_verification") or {}
            stats["law_verified_count"] = law_verification.get("verified_count", 0)
            stats["law_invalid_count"] = law_verification.get("invalid_count", 0)
            stats["law_unverified_count"] = len(law_verification.get("unverified", []))

            # 误报控制与置信度校准统计（可信度指标）
            vetoed_count = 0
            downgraded_count = 0
            for risk in session_graph.find_nodes(node_type="Risk"):
                conclusion = risk.get("properties", {}).get("debate_conclusion")
                if conclusion == "撤销":
                    vetoed_count += 1
                elif conclusion == "降级":
                    downgraded_count += 1
            stats["vetoed_count"] = vetoed_count
            stats["downgraded_count"] = downgraded_count
            if findings:
                stats["avg_confidence"] = round(
                    sum(f.get("confidence", 0.0) for f in findings) / len(findings), 4
                )
                stats["low_confidence_count"] = sum(
                    1 for f in findings if f.get("confidence", 0.0) < 0.7
                )

            # 发布完成事件
            from app.agentkit.events import EventType

            await agent_bus.publish(
                EventType.COMPLETED,
                {"phase": "completed", "message": "审查完成", "stats": stats},
            )
            sum(costs.values())

            # 返回最终结果
            return {
                "session_id": session_id,
                "findings": findings,
                "graph_data": session_graph.to_dict(),
                "human_review_items": human_review_items,
                "stats": stats,
                "costs": {k: round(v, 2) for k, v in costs.items()},
            }

        except Exception as e:
            # 用户取消：发布 cancelled 事件让前端停止等待，再原样抛出给 Celery 归类
            from app.review.graph import ReviewCancelledError

            if isinstance(e, ReviewCancelledError):
                from app.agentkit.events import EventType

                await agent_bus.publish(
                    EventType.CANCELLED,
                    {"phase": "cancelled", "message": "审查已取消"},
                )
                raise
            # 发生异常时发布错误事件，并抛出
            from app.agentkit.events import EventType

            await agent_bus.publish(
                EventType.ERROR,
                {"phase": "error", "message": str(e)},
            )
            raise
        finally:
            # 先停 trace 订阅再关总线，保证收尾事件（completed/error）也落盘
            await trace_logger.detach()
            # 无论成功或失败，都关闭 AgentBus，释放 Redis 连接与监听任务
            await agent_bus.close()

    async def _route(
        self,
        session_graph: SessionGraph,
        chunks: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], list[str], str]]:
        """
        Route 阶段：决定每个 Chunk 派给哪些 Agent，以及初始风险等级。
        返回三元组列表：(chunk, agent_names, risk_level)
        """
        # 分配结果列表
        assignments: list[tuple[dict[str, Any], list[str], str]] = []

        # 高风险关键词表：关键词 -> 建议分配的 Agent + 风险等级
        # 风险等级统一使用 high / medium / low，与项目规范保持一致
        keyword_map = {
            "试用期": (["risk_review", "term_extraction"], "high"),
            "违约金": (["risk_review", "balance"], "high"),
            "竞业限制": (["risk_review", "balance", "legal_basis"], "high"),
            "保密": (["risk_review", "balance"], "medium"),
            "社保": (["risk_review", "missing_clause"], "high"),
            "工资": (["risk_review", "balance"], "medium"),
            "解除": (["risk_review", "balance"], "medium"),
            "工作地点": (["risk_review"], "medium"),
        }

        # 遍历每个 Chunk
        for chunk in chunks:
            text = chunk.get("text", "")
            # 默认所有 Chunk 都过 risk_review 和 missing_clause
            agent_names = ["risk_review", "missing_clause"]
            risk_level = "low"  # 默认低风险

            # 关键词匹配
            for keyword, (agents, level) in keyword_map.items():
                if keyword in text:
                    # 把对应 Agent 加进去，并提升风险等级
                    for agent in agents:
                        if agent not in agent_names:
                            agent_names.append(agent)
                    # high > medium > low，取最高等级
                    if level == "high" or (level == "medium" and risk_level == "low"):
                        risk_level = level

            # TODO: 这里可以加入 BGE-M3 向量相似度判断
            # 如果 Chunk 向量与已知风险模板相似度超过阈值，也提升风险等级

            assignments.append((chunk, agent_names, risk_level))

        return assignments

    async def _preload(
        self,
        session_graph: SessionGraph,
        chunks: list[dict[str, Any]],
        section_tree: dict[str, Any],
    ) -> None:
        """
        Preload 阶段：把合同结构写入 SessionGraph，并预加载基础法律知识。
        """
        # 1. 把每个 Chunk 写成 Clause 节点
        clause_nodes = []
        for chunk in chunks:
            node_id = chunk.get("id")
            session_graph.add_node(
                node_type="Clause",
                properties={
                    "chunk_id": node_id,
                    "text": chunk.get("text", ""),
                    "page": chunk.get("page", 1),
                    "bbox": chunk.get("bbox"),
                    "section_path": chunk.get("section_path", ""),
                    "risk_level": chunk.get("risk_level", "low"),
                },
                node_id=node_id,
            )
            clause_nodes.append(
                {
                    "section_path": chunk.get("section_path", ""),
                    "text": chunk.get("text", ""),
                    "page": chunk.get("page", 1),
                }
            )

        # 2. 将合同条款向量化写入 Qdrant，供后续语义检索使用
        # Qdrant 不可用时自动忽略，不影响主流程
        try:
            vector_store = get_vector_store()
            vector_store.upsert_clauses(
                contract_id=session_graph.contract_id,
                clauses=clause_nodes,
            )
        except VectorStoreError:
            pass
        except Exception as exc:
            # 合同条款向量写入失败不阻断审查主流程，留痕便于排查
            print(f"[warn] 合同条款向量写入失败 contract_id={session_graph.contract_id}: {exc}", flush=True)

        # 3. 不再预加载固定法条：法律依据改由 LegalResearchAgent 动态推断和检索，
        #    避免对非劳动合同类型造成干扰。

        # 4. 调用 TermExtractionAgent 提取主体信息
        term_agent = self.agents["term_extraction"]
        await term_agent.run(session_graph, {"section_tree": section_tree})

    async def _execute(
        self,
        session_graph: SessionGraph,
        assignments: list[tuple[dict[str, Any], list[str], str]],
        context: dict[str, Any],
    ) -> None:
        """
        Execute 阶段：并行执行所有 Agent。
        这里用 asyncio.gather 同时启动多个协程。
        """
        # 收集所有需要执行的任务
        tasks = []

        # 按 Agent 维度组织：同一个 Agent 可能要处理多个 Chunk
        agent_to_chunks: dict[str, list[dict[str, Any]]] = {}
        for chunk, agent_names, risk_level in assignments:
            for agent_name in agent_names:
                agent_to_chunks.setdefault(agent_name, []).append(chunk)

        # 为每个 Agent 创建一个协程任务
        for agent_name, agent_chunks in agent_to_chunks.items():
            agent = self.agents.get(agent_name)
            if not agent:
                continue

            # 构造该 Agent 的上下文
            agent_context = {
                **context,
                "chunks": agent_chunks,
                "agent_name": agent_name,
            }

            # 创建协程并加入任务列表
            task = agent.run(session_graph, agent_context)
            tasks.append(task)

        # 并行等待所有 Agent 完成
        # return_exceptions=True 表示某个 Agent 出错不会导致整体崩溃
        await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _parse_llm_json_output(text: str) -> Any:
        """
        从 LLM 输出中解析 JSON，兼容直接返回和 markdown 代码块包裹的情况。
        """
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass
        return None

    async def _llm_cross_clause_detector(
        self,
        contract_type: str,
        clauses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        LLM 兜底跨条款风险检测器。

        当配置驱动规则未命中或需要补充时，调用 LLM 对多条 Clause 做组合推理，
        返回与 find_cross_clause_risks 格式一致的组合风险列表。
        """
        if not clauses:
            return []

        # 控制上下文长度，避免 token 爆炸：最多取前 30 条，每条最多 300 字
        max_clauses = 30
        max_text_len = 300
        selected = clauses[:max_clauses]
        valid_ids = {c["id"] for c in selected}

        clause_texts = []
        for i, clause in enumerate(selected):
            text = clause.get("properties", {}).get("text", "")
            if len(text) > max_text_len:
                text = text[:max_text_len] + "..."
            clause_texts.append({
                "index": i,
                "clause_id": clause["id"],
                "text": text,
            })

        prompt = CROSS_CLAUSE_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            clause_list=json.dumps(clause_texts, ensure_ascii=False, indent=2),
        )

        try:
            llm_client = get_llm_client()
            response = await llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一名专业的合同审查律师，擅长发现跨条款组合风险。请只输出 JSON 数组。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json_output(response)
            if not isinstance(parsed, list):
                return []

            valid_risks: list[dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                clause_ids = [cid for cid in item.get("clause_ids", []) if cid in valid_ids]
                if len(clause_ids) < 2:
                    continue
                level = item.get("level", "medium")
                if level not in ("high", "medium", "low"):
                    level = "medium"
                confidence = item.get("confidence", 0.7)
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.7
                valid_risks.append({
                    "risk_type": item.get("risk_type", "跨条款组合风险"),
                    "level": level,
                    "confidence": min(max(confidence, 0.0), 1.0),
                    "reason": item.get("reason", ""),
                    "clause_ids": clause_ids,
                })
            return valid_risks
        except Exception:
            # LLM 兜底失败不应阻断主流程
            return []

    async def _merge_and_link(self, session_graph: SessionGraph) -> None:
        """
        Merge+Link 阶段：
        1. 合并重复风险
        2. 建立 Clause 之间的 RELATES_TO / CONTRADICTS 边
        3. 发现跨条款组合风险
        """
        # 1. 调用 SessionGraph 内置方法合并重复 Risk
        merged_count = session_graph.merge_duplicate_risks()
        print(f"[Merge+Link] 合并了 {merged_count} 个重复风险")

        # 2. 发现跨条款组合风险
        # 如启用 LLM 兜底，可传入异步检测器；目前默认关闭，仅保留接口
        llm_detector = None
        if self.config.get("enable_llm_cross_clause_fallback"):
            llm_detector = self._llm_cross_clause_detector

        cross_risks = await session_graph.find_cross_clause_risks(
            contract_type=session_graph.contract_type,
            llm_detector=llm_detector,
        )
        for cross in cross_risks:
            # 从关联的 Clause 节点继承位置信息，用于前端 PDF 高亮
            clause_ids = cross.get("clause_ids", [])
            page = 1
            bbox = None
            clause_texts = []
            for clause_id in clause_ids:
                clause_node = session_graph.get_node(clause_id)
                if clause_node:
                    clause_props = clause_node.get("properties", {})
                    clause_texts.append(clause_props.get("text", ""))
                    if bbox is None:
                        page = clause_props.get("page", 1)
                        bbox = clause_props.get("bbox")

            # 把组合风险写回 SessionGraph
            session_graph.add_node(
                node_type="Risk",
                properties={
                    "risk_type": cross["risk_type"],
                    "level": cross["level"],
                    "confidence": cross["confidence"],
                    "reason": cross["reason"],
                    "clause_text": "\n".join(clause_texts),
                    "clause_ids": clause_ids,
                    "page": page,
                    "bbox": bbox,
                    "is_cross_clause": True,
                },
            )

        # 3. 跨条款风险写入后，再次合并可能与单条款风险重复的组合风险
        merged_count_after_cross = session_graph.merge_duplicate_risks()
        if merged_count_after_cross > 0:
            print(f"[Merge+Link] 跨条款风险写入后又合并了 {merged_count_after_cross} 个重复风险")

    async def _legal_verify(
        self,
        session_graph: SessionGraph,
        context: dict[str, Any],
    ) -> None:
        """
        LegalVerify 阶段：
        1. 调用 LegalBasisAgent 为 Risk 节点补充法律依据。
        2. 调用 LegalVerifyAgent 验证这些法条是否存在于知识库（白名单校验）。
        验证统计写入 context["law_verification"]，供最终 stats 汇总。
        """
        basis_agent = self.agents["legal_basis"]
        await basis_agent.run(session_graph, context)

        verify_agent = self.agents["legal_verify"]
        verify_result = await verify_agent.run(session_graph, context)
        context["law_verification"] = verify_result.get("output", {})

    async def _debate(
        self,
        session_graph: SessionGraph,
        context: dict[str, Any],
    ) -> None:
        """
        Debate 阶段：调用 DebateAgent 对高风险项辩论。
        """
        agent = self.agents["debate"]
        await agent.run(session_graph, context)

    async def _triage(
        self, session_graph: SessionGraph
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Triage 阶段：整理最终输出。
        返回：(findings, human_review_items)
        """
        # 调用 HumanReviewAgent 判断哪些风险需要人工复核
        human_agent = self.agents["human_review"]
        human_items = await human_agent.run(session_graph, {})

        # 从 SessionGraph 中取出所有 Risk 节点
        risk_nodes = session_graph.find_nodes(node_type="Risk")

        findings = []
        human_review_items = human_items.get("items", [])
        valid_levels = {"high", "medium", "low"}

        for risk in risk_nodes:
            props = risk.get("properties", {})
            level = props.get("level", "low")
            if level not in valid_levels:
                level = "medium"

            # 应用 DebateAgent 的辩论结论
            debate_conclusion = props.get("debate_conclusion")
            if debate_conclusion == "撤销":
                # 辩论后认为不是风险，跳过该节点
                continue
            if debate_conclusion == "降级":
                level = self._downgrade_level(level)

            # 把 Risk 节点转成前端需要的数据格式
            finding = {
                "clause_text": props.get("clause_text", ""),
                "risk_type": props.get("risk_type", ""),
                "level": level,
                "confidence": props.get("confidence", 0.0),
                "reason": props.get("reason", ""),
                "law_refs": props.get("law_refs", []),
                "suggestion": props.get("suggestion", {}),
                "page": props.get("page", 1),
                "bbox": props.get("bbox"),
            }
            findings.append(finding)

        return findings, human_review_items

    @staticmethod
    def _downgrade_level(level: str) -> str:
        """把风险等级降一级。"""
        mapping = {"high": "medium", "medium": "low", "low": "low"}
        return mapping.get(level, "low")
