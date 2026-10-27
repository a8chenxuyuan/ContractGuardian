"""
服务：rag.knowledge_cache
作用：动态法规原文缓存。

核心流程：
1. 当本地知识库未命中或命中不足时，根据查询词推断目标法规与条款；
2. 使用 Tavily 联网搜索对应法规原文；
3. 通过 LLM 从搜索结果中提取、校验条款原文；
4. 仅当确认获得原文（非简介、非摘要）时，写入 PostgreSQL 与 Qdrant；
5. 写入前按 law_name + article_number 去重。

使用方式：
    from app.rag.knowledge_cache import cache_articles_from_web_search
    articles = await cache_articles_from_web_search("劳动合同法 试用期", category="劳动合同法")
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.llm import get_llm_client
from app.models.knowledge import KnowledgeArticle
from app.rag.vector_store import get_vector_store

settings = get_settings()

# 常见法律简称 -> 全称映射，用于规范化 law_name
LAW_NAME_ALIASES: dict[str, str] = {
    "民法典": "《中华人民共和国民法典》",
    "合同法": "《中华人民共和国民法典》",
    "公司法": "《中华人民共和国公司法》",
    "劳动合同法": "《中华人民共和国劳动合同法》",
    "劳动法": "《中华人民共和国劳动法》",
    "社会保险法": "《中华人民共和国社会保险法》",
    "民间借贷司法解释": "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》",
    "民间借贷规定": "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》",
}

# 法律 -> 默认 category 映射
LAW_CATEGORY_MAP: dict[str, str] = {
    "《中华人民共和国民法典》": "民法典",
    "《中华人民共和国公司法》": "公司法",
    "《中华人民共和国劳动合同法》": "劳动合同法",
    "《中华人民共和国劳动法》": "劳动法",
    "《中华人民共和国社会保险法》": "社会保险法",
    "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》": "借款合同",
}


def _normalize_law_name(law_name: str) -> str:
    """将法律简称/片段统一为规范全称。"""
    law_name = law_name.strip()
    # 如果已经包含书名号且为全称，直接返回
    if law_name.startswith("《") and law_name.endswith("》"):
        return law_name
    for alias, full in LAW_NAME_ALIASES.items():
        if alias in law_name:
            return full
    # 兜底：补全书名号
    if not law_name.startswith("《"):
        return f"《{law_name}》"
    return law_name


def _extract_article_number(text: str) -> str | None:
    """从文本中提取「第X条」格式，优先匹配阿拉伯数字。"""
    if not text:
        return None
    # 第123条
    m = re.search(r"第\s*([0-9]+)\s*条", text)
    if m:
        return f"第{m.group(1)}条"
    # 第八十六条
    m = re.search(r"第\s*([一二三四五六七八九十百千万零〇]+)\s*条", text)
    if m:
        return f"第{m.group(1)}条"
    return None


def _cn_to_int(s: str) -> int:
    """将中文数字转换为整数，用于去重比较。"""
    cn = {
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "百": 100, "千": 1000, "万": 10000, "零": 0, "〇": 0,
    }
    s = s.strip()
    if not s:
        return 0
    # 纯数字
    if s.isdigit():
        return int(s)
    total = 0
    current = 0
    for ch in s:
        if ch not in cn:
            continue
        v = cn[ch]
        if v >= 10:
            if current == 0:
                current = 1
            total += current * v
            current = 0
        else:
            current = current * 10 + v
    return total + current


def _article_numbers_equal(a: str, b: str) -> bool:
    """比较两个「第X条」是否相同（支持中文/阿拉伯数字）。"""
    ma = re.search(r"第\s*([0-9一二三四五六七八九十百千万零〇]+)\s*条", a or "")
    mb = re.search(r"第\s*([0-9一二三四五六七八九十百千万零〇]+)\s*条", b or "")
    if not ma or not mb:
        return (a or "").strip() == (b or "").strip()
    return _cn_to_int(ma.group(1)) == _cn_to_int(mb.group(1))


def _get_db_session() -> Session:
    """创建同步数据库会话。"""
    engine = create_engine(settings.SYNC_DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _article_exists(db: Session, law_name: str, article_number: str) -> bool:
    """检查数据库中是否已存在该法条（支持中文/阿拉伯数字互认）。"""
    records = (
        db.query(KnowledgeArticle)
        .filter(KnowledgeArticle.law_name == law_name)
        .all()
    )
    for r in records:
        if _article_numbers_equal(r.article_number, article_number):
            return True
    return False


def _build_search_query(law_name: str, article_number: str | None = None, keywords: str | None = None) -> str:
    """构造 Tavily 搜索查询词。"""
    parts = [law_name]
    if article_number:
        parts.append(article_number)
    if keywords:
        parts.append(keywords)
    parts.append("原文")
    return " ".join(parts)


async def _call_tavily(law_name: str, article_number: str | None = None, keywords: str | None = None) -> dict[str, Any]:
    """调用 Tavily 搜索法规原文。"""
    # 延迟导入，避免与 app.review.tools 包产生循环导入
    from app.review.tools.web_search import web_search

    query = _build_search_query(law_name, article_number, keywords)
    return await web_search(
        {
            "query": query,
            "max_results": settings.TAVILY_MAX_RESULTS,
            "search_depth": settings.TAVILY_SEARCH_DEPTH,
            "include_raw_content": True,
        },
        {},
    )


def _regex_extract_article(article_number: str, content: str) -> str | None:
    """
    使用正则从搜索结果正文中提取指定法条原文。

    支持以下格式：
    - **第四百九十六条**  格式条款是...
    - 第四百九十六条【格式条款】格式条款是...
    - 第四百九十六条 格式条款是...
    到下一个「第X条」或文本结束为止。
    会跳过标题、释义等位置，优先匹配紧跟正文的位置。
    """
    if not content:
        return None

    # 候选：article_number 后跟中文标题【...】、空格、或正文
    patterns = [
        # 第X条【标题】正文
        rf"(?:\*\*)?\s*{re.escape(article_number)}\s*(?:\*\*)?\s*【[^】]+】\s*",
        # 第X条 正文（排除紧跟「释义」「理解」等词的标题位置）
        rf"(?:\*\*)?\s*{re.escape(article_number)}\s*(?:\*\*)?\s+(?!释义|理解|主旨|标题|来源)(?=[\u4e00-\u9fa5])",
    ]

    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            start = match.end()
            # 在下一条、章节标题、案例/释义标记处截断
            next_match = re.search(
                r"(?:第\s*[一二三四五六七八九十百千万零〇0-9]+\s*条)|"
                r"(?:【(?:条文主旨|条文释义|条文理解|理解与适用|法条链接).*?】)|"
                r"(?:相关案例|典型案例|法官解析|特别声明|释义|理解|主旨|来源[:：])|"
                r"(?:\n\s*（[一二三四五六七八九十]）)",
                content[start:],
            )
            end = start + next_match.start() if next_match else len(content)
            text = content[start:end].strip()
            # 清理 markdown 标记和多余空行
            text = re.sub(r"\*+", "", text)
            text = re.sub(r"\n\s*\n+", "\n", text)
            text = text.strip()
            if len(text) >= 30:
                candidates.append(text)

    # 返回最长候选，通常更可能是完整原文
    return max(candidates, key=len) if candidates else None


async def _extract_original_text(
    law_name: str,
    article_number: str,
    search_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    从 Tavily 搜索结果中提取指定法条原文。

    先尝试正则提取；若失败，再调用 LLM 提取。
    返回 {"law_name", "article_number", "article_title", "article_text", "source_url"}
    若无法确认原文，返回 None。
    """
    if not search_results:
        return None

    # ---------- 阶段 1：正则提取（更稳定） ----------
    for item in search_results:
        content = item.get("raw_content", "") or item.get("content", "")
        if not content:
            continue
        text = _regex_extract_article(article_number, content)
        if text:
            return {
                "law_name": _normalize_law_name(law_name),
                "article_number": article_number,
                "article_title": "",
                "article_text": text,
                "source_url": item.get("url", ""),
            }

    # ---------- 阶段 2：LLM 提取（兜底） ----------
    context_parts = []
    for idx, item in enumerate(search_results[:3], 1):
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("raw_content", "") or item.get("content", "")
        if not content.strip():
            continue
        # 控制输入长度：qwen-math-turbo 总上下文 4096，输出约 1024，输入需控制在 2000 token 以内
        context_parts.append(
            f"[来源{idx}]\n标题: {title}\nURL: {url}\n内容:\n{content[:1000]}\n"
        )

    if not context_parts:
        return None

    prompt = f"""你是一名法律文本提取专家。请从以下搜索结果中，提取《{law_name}》{article_number}的完整原文。

要求：
1. 仅返回该条款的原文正文，不要解释、不要总结、不要添加编号外的内容；
2. 如果某条搜索结果包含完整原文，优先使用它；
3. 如果多个来源的原文略有差异，以国家机关（全国人大、最高人民法院等）官方来源为准；
4. 如果无法确认原文，请明确回答「未找到原文」；
5. 如果原文中自然包含款项（如"（一）..."），保留完整款项。

请按以下 JSON 格式返回，不要添加 markdown 代码块标记：
{{
  "found": true/false,
  "article_title": "条款标题（如有）",
  "article_text": "条款完整原文",
  "source_url": "最可信来源的 URL"
}}

搜索结果：
{''.join(context_parts)}
"""

    try:
        client = get_llm_client()
        response = await client.chat_completion(
            messages=[
                {"role": "system", "content": "你是专业的中国法律文本提取助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
    except Exception:
        return None

    if not response:
        return None

    # 尝试解析 JSON
    parsed = None
    try:
        parsed = json.loads(response.strip())
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON 块
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if not parsed or not parsed.get("found"):
        return None

    article_text = (parsed.get("article_text") or "").strip()
    if not article_text or len(article_text) < 10:
        return None

    # 校验：原文中应当包含该条款号（中文或阿拉伯数字）
    number_core = re.sub(r"[第条]", "", article_number)
    if number_core not in article_text and str(_cn_to_int(number_core)) not in article_text:
        # 允许标题中已含条款号的情况
        title = parsed.get("article_title") or ""
        if number_core not in title and str(_cn_to_int(number_core)) not in title:
            return None

    return {
        "law_name": _normalize_law_name(law_name),
        "article_number": article_number,
        "article_title": (parsed.get("article_title") or "").strip(),
        "article_text": article_text,
        "source_url": parsed.get("source_url") or (search_results[0].get("url") if search_results else ""),
    }


def _save_article_to_sql(db: Session, article: dict[str, Any]) -> KnowledgeArticle | None:
    """将法条写入 PostgreSQL/SQLite，并返回记录。"""
    law_name = _normalize_law_name(article["law_name"])
    article_number = article["article_number"]

    if _article_exists(db, law_name, article_number):
        return None

    category = article.get("category") or LAW_CATEGORY_MAP.get(law_name, "其他")
    record = KnowledgeArticle(
        law_name=law_name,
        article_number=article_number,
        article_title=article.get("article_title") or None,
        article_text=article["article_text"],
        category=category,
        metadata_json={
            "source": "tavily_web_search",
            "source_url": article.get("source_url"),
        },
    )
    db.add(record)
    db.flush()
    return record


async def _save_article_to_vector(record: KnowledgeArticle) -> bool:
    """将单条法条写入 Qdrant（父子切块 + 双路向量）。"""
    try:
        store = get_vector_store()
        await store.upsert_knowledge_async(
            [
                {
                    "id": record.id,
                    "law_name": record.law_name,
                    "article_number": record.article_number,
                    "article_title": record.article_title or "",
                    "article_text": record.article_text,
                    "category": record.category,
                }
            ]
        )
        return True
    except Exception:
        return False


async def fetch_and_cache_article(
    law_name: str,
    article_number: str,
    keywords: str | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """
    联网搜索指定法条原文并缓存。

    仅在成功提取原文且数据库不存在重复时才缓存。
    返回缓存后的法条字典，未成功则返回 None。
    """
    law_name = _normalize_law_name(law_name)
    article_number = article_number.strip()

    should_close_db = db is None
    if db is None:
        db = _get_db_session()

    try:
        # 再次检查是否已缓存
        if _article_exists(db, law_name, article_number):
            return None

        search_result = await _call_tavily(law_name, article_number, keywords)
        if search_result.get("error"):
            return {"error": search_result["error"], "cached": False}

        article = await _extract_original_text(
            law_name, article_number, search_result.get("results", [])
        )
        if not article:
            return None

        record = _save_article_to_sql(db, article)
        if record is None:
            # 可能是并发写入导致重复，视为已存在
            return None

        _save_article_to_vector(record)
        db.commit()

        return {
            "law_name": record.law_name,
            "article_number": record.article_number,
            "article_title": record.article_title,
            "article_text": record.article_text,
            "category": record.category,
            "source_url": (record.metadata_json or {}).get("source_url"),
            "cached": True,
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e), "cached": False}
    finally:
        if should_close_db:
            db.close()


async def cache_articles_from_web_search(
    query: str,
    category: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """
    根据自然语言查询词，先联网搜索，再提取并缓存相关法条。

    返回成功缓存的法条列表（不会去重已存在的）。
    """
    # 延迟导入，避免与 app.review.tools 包产生循环导入
    from app.review.tools.web_search import web_search

    search_result = await web_search(
        {
            "query": query,
            "max_results": settings.TAVILY_MAX_RESULTS,
            "search_depth": settings.TAVILY_SEARCH_DEPTH,
            "include_raw_content": True,
        },
        {},
    )
    if search_result.get("error"):
        return [{"error": search_result["error"], "cached": False}]

    results = search_result.get("results", [])
    if not results:
        return []

    # 用 LLM 识别搜索结果中提到的所有法条（law_name + article_number）
    context_parts = []
    for idx, item in enumerate(results[:3], 1):
        title = item.get("title", "")
        url = item.get("url", "")
        content = (item.get("raw_content", "") or item.get("content", ""))[:1000]
        if not content.strip():
            continue
        context_parts.append(f"[来源{idx}]\n标题: {title}\nURL: {url}\n内容:\n{content}\n")

    if not context_parts:
        return []

    prompt = f"""请从以下搜索结果中，识别出所有明确提到的中国法律法规及其条款号。

要求：
1. 仅返回确实出现在搜索结果中的法条；
2. 每个法条包含 law_name（法律全称，带《》）和 article_number（如"第八十六条"）；
3. 如果无法识别任何法条，返回空数组；
4. 只输出 JSON，不要解释。

输出格式：
{{"articles": [{{"law_name": "...", "article_number": "..."}}]}}

搜索结果：
{''.join(context_parts)}
"""

    try:
        client = get_llm_client()
        response = await client.chat_completion(
            messages=[
                {"role": "system", "content": "你是法律信息识别助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
        )
    except Exception:
        return []

    parsed = None
    try:
        parsed = json.loads(response.strip())
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if not parsed or not isinstance(parsed.get("articles"), list):
        return []

    cached_articles: list[dict[str, Any]] = []
    db = _get_db_session()
    try:
        for article_meta in parsed["articles"][:limit]:
            law_name = _normalize_law_name(article_meta.get("law_name", ""))
            article_number = article_meta.get("article_number", "").strip()
            if not law_name or not article_number:
                continue

            # 去重检查
            if _article_exists(db, law_name, article_number):
                continue

            result = await fetch_and_cache_article(law_name, article_number, db=db)
            if result and result.get("cached"):
                cached_articles.append(result)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    return cached_articles
