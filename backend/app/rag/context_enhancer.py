"""
文件：app/rag/context_enhancer.py
作用：为子块生成「定位句」并拼在子块文本前一起编码。

设计动机（为什么）：
- 子块只有 200-400 字，脱离文档语境后向量语义很弱
  （如"试用期为六个月"——不知道是劳动合同的试用期还是买卖合同的验收期）；
- 检索时查询是"用户视角"的描述，定位句相当于给子块注入"文档视角"的锚点，
  让 BGE-M3 这类 embedding 模型在编码时同时看到章节路径与主题概括。

幻觉校验：LLM 生成的定位句只允许使用「文档标题 + 章节路径 + 父块原文」中出现过的词。
校验方式：定位句按「·」分段，标题/章节段要求清洗后逐字出现（硬校验），
最后的主题概括段取所有 4-gram，要求 ≥60% 能在允许文本中命中——
不引入分词依赖，且对 LLM 改写/语序调整足够稳健。
失败重试 ≤2 次，仍失败则降级为机械拼接（标题+章节路径），保证流程永不中断。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.core.config import get_settings

_LOCATOR_PREFIX = "本文档"
# 主题概括段的 n-gram 命中率门槛（允许 LLM 语序改写，不允许编造词）
_GRAM_HIT_THRESHOLD = 0.6
_GRAM_SIZE = 4
# 单批送入 LLM 的子块数：定位句很短，8 条一批在延迟与请求数之间平衡
_BATCH_SIZE = 8
_MAX_RETRY = 2

_PUNCT_RE = re.compile(r"[\s，。、；：！？,.;:!?()（）【】\[\]《》\"'「」『』·—\-…]")


def mechanical_locator(doc_title: str | None, section_path: str, title: str | None = None) -> str:
    """机械定位句：零成本、零幻觉风险，作为兜底与校验基准。"""
    parts = [p for p in (doc_title, section_path, title) if p]
    body = " · ".join(dict.fromkeys(parts))  # 去重保序
    return f"【{_LOCATOR_PREFIX}：{body}】"


def _clean(text: str) -> str:
    """去标点空白，仅保留用于 n-gram 校验的实义字符。"""
    return _PUNCT_RE.sub("", text or "")


def _ngrams(text: str, n: int = _GRAM_SIZE) -> set[str]:
    cleaned = _clean(text)
    if len(cleaned) < n:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def validate_locator(locator: str, allowed_texts: list[str]) -> bool:
    """校验定位句是否只使用了允许文本中的信息。

    定位句按「·」分段后，前段（文档标题/章节路径）是 LLM 的输入，要求清洗后
    完整出现（硬校验）；最后的主题概括段允许语序改写，用 4-gram 命中率兜底。
    """
    body = locator or ""
    for prefix in (f"{_LOCATOR_PREFIX}：", f"{_LOCATOR_PREFIX}:"):
        if body.startswith(prefix):
            body = body[len(prefix) :]
            break

    segments = [s for s in re.split(r"[·]", body) if s.strip()]
    if not segments:
        return True  # 只有前缀，无信息量，交给降级逻辑

    allowed_clean = _clean(" ".join(allowed_texts))

    # 硬校验：标题与章节路径必须逐字出现
    for seg in segments[:-1]:
        c = _clean(seg)
        if c and c not in allowed_clean:
            return False

    # 软校验：主题概括段 4-gram 命中率
    grams = _ngrams(segments[-1])
    if not grams:
        return True
    allowed_grams = _ngrams(allowed_clean)
    hit = sum(1 for g in grams if g in allowed_grams)
    return hit / len(grams) >= _GRAM_HIT_THRESHOLD


def _extract_json(text: str) -> dict[str, Any] | None:
    """从 LLM 输出中提取 JSON 对象（兼容 ```json 包裹与前后噪声）。"""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _llm_batch_locate(
    doc_title: str,
    batch: list[dict[str, Any]],
) -> dict[int, str]:
    """调用 LLM 为一批子块生成定位句，返回 {子块在批内的序号: 定位句}。"""
    from app.llm import get_llm_client

    settings = get_settings()
    items = [
        {
            "i": idx,
            "section_path": item.get("section_path", ""),
            "excerpt": item["text"][:300],
        }
        for idx, item in enumerate(batch)
    ]

    system_prompt = (
        "你是合同/法律文档检索索引构建助手。为每个文本片段生成一句中文定位句，"
        f"格式固定为「{_LOCATOR_PREFIX}：{{文档标题}} · {{章节路径}} · {{片段主题}}」。"
        "主题概括不超过 20 字，且只能使用文档标题、章节路径或片段原文中出现的词语，严禁引入原文没有的信息。"
    )
    user_payload = json.dumps(
        {"doc_title": doc_title, "items": items}, ensure_ascii=False
    )

    client = get_llm_client()
    content = await client.chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        model=settings.LLM_MODEL,
        temperature=0.1,
        max_tokens=600,
        response_format={"type": "json_object"},
    )

    data = _extract_json(content)
    if not data:
        raise ValueError(f"定位句 LLM 输出无法解析: {content[:200]}")

    result: dict[int, str] = {}
    for entry in data.get("locators", []):
        try:
            idx = int(entry.get("i"))
            locator = str(entry.get("locator", "")).strip()
        except (TypeError, ValueError):
            continue
        if locator:
            result[idx] = locator
    return result


async def enhance_locators(
    doc_title: str | None,
    items: list[dict[str, Any]],
) -> list[str]:
    """主入口：为每个子块生成定位句，返回与 items 等长的定位句列表。

    items 每项需含 text（子块文本），可选 section_path / title / parent_text。
    """
    settings = get_settings()
    if not items:
        return []
    if not settings.CONTEXT_ENHANCE_ENABLED or not settings.LLM_API_KEY:
        return [
            mechanical_locator(doc_title, it.get("section_path", ""), it.get("title"))
            for it in items
        ]

    doc_title = doc_title or "合同文档"
    results: list[str] = []
    batches = [items[i : i + _BATCH_SIZE] for i in range(0, len(items), _BATCH_SIZE)]

    # 各批独立并发，定位句之间无依赖
    batch_results = await asyncio.gather(
        *(_enhance_batch_validated(doc_title, b) for b in batches)
    )
    for br in batch_results:
        results.extend(br)
    return results


async def _enhance_batch_validated(
    doc_title: str,
    batch: list[dict[str, Any]],
) -> list[str]:
    """带校验与降级的单批处理。"""
    fallbacks = [
        mechanical_locator(doc_title, item.get("section_path", ""), item.get("title"))
        for item in batch
    ]

    current: dict[int, str] = {}
    pending = list(range(len(batch)))

    for _ in range(_MAX_RETRY + 1):
        if not pending:
            break
        try:
            generated = await _llm_batch_locate(doc_title, [batch[i] for i in pending])
        except Exception:
            break  # LLM 不可用/输出持续异常，全部走机械降级

        next_pending: list[int] = []
        for i in pending:
            locator = generated.get(i, "")
            if not locator:
                next_pending.append(i)
                continue
            allowed = [doc_title, batch[i].get("section_path", ""), batch[i]["text"]]
            if validate_locator(locator, allowed):
                current[i] = locator
            else:
                next_pending.append(i)
        pending = next_pending
        if not generated:
            break

    return [current.get(i, fallbacks[i]) for i in range(len(batch))]
