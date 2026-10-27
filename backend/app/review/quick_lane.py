"""
文件：app/review/quick_lane.py
作用：M4 —— 快车道单点问答（检索 + 单次生成 + 强制引用）。

设计动机（为什么）：
- 完整审查走 13 Agent 管线（分钟级），但用户在对话框问"试用期最长多久"这类
  单点问题时，全量审查纯属浪费；
- 快车道 = CRAG 检索 + 一次 LLM 生成 + 强制引用，秒级返回；
- 替换 chat.py 里旧的规则模拟回答（TODO 注释遗留）。

引用透明：citations 直接来自 M1 检索结果（law_name/article_number/locator/原文），
生成提示词要求逐条标注来源，无法编造库里没有的法条。
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.review.prompts.quick_lane import QUICK_LANE_SYSTEM_PROMPT


async def quick_answer(
    question: str,
    contract_id: int | None = None,
    selected_text: str | None = None,
    extra_context: str | None = None,
    user_id: int | str | None = None,
) -> dict[str, Any]:
    """快车道问答主入口。

    extra_context：调用方补充的背景信息（如审查发现的风险说明），拼进生成提示词。
    user_id：提问用户；提供时注入技能/记忆能力层并检测显式偏好（M2-1/M2-3）。

    返回：
    {
        "answer": str,
        "citations": [  # 生成时实际用到的依据
            {"law_name", "article_number", "locator", "text", "score"}       # 法条
            | {"section_path", "page", "text", "score", "source": "contract"}  # 合同条款
        ],
        "degraded": bool,  # True = 检索两轮仍不足，回答可能不完整
    }
    """
    from app.agentkit.context import ContextManager, Layer, Priority
    from app.agentkit.memory import maybe_record_preference, render_memory
    from app.agentkit.skills import match_skills, render_skills
    from app.llm import get_llm_client
    from app.rag.crag import corrective_search
    from app.rag.vector_store import get_vector_store

    # 显式偏好句式（"以后别报…"）先落跨会话记忆
    if user_id is not None:
        maybe_record_preference(user_id, question)

    settings = get_settings()
    store = get_vector_store()
    client = get_llm_client()

    # 组合检索查询：划词优先（用户选中了具体条款追问时，划词是最强信号）
    base_query = question if not selected_text else f"{selected_text} {question}"

    async def _knowledge_search(q: str) -> list[dict[str, Any]]:
        return await store.search_knowledge_async(q, top_k=5)

    knowledge_hits, degraded = await corrective_search(
        _knowledge_search, base_query, client
    )

    # 有 contract_id 时同时检索本合同条款
    clause_hits: list[dict[str, Any]] = []
    if contract_id is not None:
        try:
            clause_hits = await store.search_clauses_async(
                base_query, contract_id=contract_id, top_k=3
            )
        except Exception:
            clause_hits = []

    if not knowledge_hits and not clause_hits:
        return {
            "answer": "知识库中暂时没有找到与该问题相关的法律依据，请稍后重试或换一种问法。",
            "citations": [],
            "degraded": True,
        }

    # 组装带引用编号的上下文
    citations: list[dict[str, Any]] = []
    context_blocks: list[str] = []
    for i, hit in enumerate(knowledge_hits, 1):
        citations.append(
            {
                "law_name": hit.get("law_name", ""),
                "article_number": hit.get("article_number", ""),
                "article_title": hit.get("article_title", ""),
                "locator": hit.get("locator", ""),
                "text": hit.get("article_text", ""),
                "score": hit.get("score", 0.0),
            }
        )
        context_blocks.append(
            f"[{i}] {hit.get('law_name', '')}{hit.get('article_number', '')}"
            f"（{hit.get('article_title', '')}）：\n{hit.get('article_text', '')[:800]}"
        )
    clause_start = len(citations)
    for j, hit in enumerate(clause_hits, clause_start + 1):
        citations.append(
            {
                "section_path": hit.get("section_path", ""),
                "page": hit.get("page"),
                "text": hit.get("text", ""),
                "score": hit.get("score", 0.0),
                "source": "contract",
            }
        )
        context_blocks.append(
            f"[{j}] 本合同 {hit.get('section_path', '')}：\n{hit.get('text', '')[:800]}"
        )

    context_text = "\n\n".join(context_blocks)
    degrade_note = (
        "\n\n（注意：以上材料经两轮检索仍不充分，如材料不足以回答，请明确说明。）"
        if degraded
        else ""
    )

    system_prompt = QUICK_LANE_SYSTEM_PROMPT

    # 能力层注入（协议 context_assembly.md 唯一入口）：
    # 技能按问题触发词匹配、记忆按 user_id 加载，检索材料同层受预算约束。
    matched = match_skills(question)
    skills_ctx = render_skills(matched)
    memory_ctx = render_memory(user_id) if user_id is not None else ""
    assembled = ContextManager().assemble(
        layers=[
            Layer("skills", skills_ctx, Priority.HIGH),
            Layer("memory", memory_ctx, Priority.HIGH),
            Layer("tool", context_text, Priority.NORMAL),
        ],
    )

    parts_note = ""
    if assembled.parts.get("skills"):
        parts_note += f"\n\n[适用技能]\n{assembled.parts['skills']}"
    if assembled.parts.get("memory"):
        parts_note += f"\n\n[该用户历史偏好]\n{assembled.parts['memory']}"

    user_prompt = (
        f"用户问题：{question}\n"
        + (f"用户选中的合同原文：{selected_text}\n" if selected_text else "")
        + (f"\n背景信息（用户正在查看的审查发现）：\n{extra_context}\n" if extra_context else "")
        + f"\n检索材料：\n{assembled.parts.get('tool', '')}{degrade_note}{parts_note}"
    )

    try:
        answer = await client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=settings.LLM_MODEL,
            temperature=0.2,
            max_tokens=1200,
        )
    except Exception:
        # LLM 失败兜底：直接返回检索到的法条原文
        fallback = "\n\n".join(
            f"【{c.get('law_name', '')}{c.get('article_number', '')}】{c.get('text', '')[:300]}"
            for c in citations[:3]
        )
        answer = f"生成服务暂时不可用，以下是与问题相关的法律原文：\n\n{fallback}"

    return {"answer": answer, "citations": citations, "degraded": degraded}


def citations_from_answer(answer: str, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按回答中实际标注的引用编号过滤 citations（未引用的不返回给前端）。

    解析 [数字] 标记；无任何标记时返回全部（LLM 偶尔漏标时保底展示）。
    """
    import re

    used = {int(m) for m in re.findall(r"\[(\d{1,2})\]", answer or "")}
    if not used:
        return citations
    return [c for i, c in enumerate(citations, 1) if i in used]
