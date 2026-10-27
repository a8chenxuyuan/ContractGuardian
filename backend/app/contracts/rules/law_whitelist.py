"""法条白名单校验服务。

目的：杜绝 LLM 幻觉法条（编造不存在的法律名称或条文序号）进入最终报告。

原理：
1. 从知识库 knowledge_articles 表加载全部 (法律名, 条号) 对，构成白名单；
2. 对每条 law_ref 引用解析出「法律名 + 第X条」，先做白名单精确匹配；
3. 白名单无法判断时（解析不出条号/法名），由调用方退回语义检索兜底。

匹配策略：
- 法律名做归一化（去书名号、"中华人民共和国"前缀），再双向包含匹配，
  以兼容简称（《劳动合同法》 vs 《中华人民共和国劳动合同法》）；
- 条号支持中文数字（十九 → 19、一百九十二 → 192）与阿拉伯数字。
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.knowledge import KnowledgeArticle

# 《xxx》法律名
LAW_NAME_RE = re.compile(r"《(.+?)》")
# 第X条（支持中文数字与阿拉伯数字混写）
ARTICLE_RE = re.compile(r"第([零一二两三四五六七八九十百千\d]+)条")

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_article_to_int(text: str) -> int | None:
    """把「第X条」中的条号转为整数。支持中文数字与阿拉伯数字。"""
    text = text.strip().replace("第", "").replace("条", "").replace(" ", "")
    if not text:
        return None
    if text.isdigit():
        return int(text)

    total, num = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            if num == 0:
                num = 1
            total += num * _CN_UNITS[ch]
            num = 0
        elif ch == "零":
            num = 0
        else:
            return None
    result = total + num
    return result if result > 0 else None


def normalize_law_name(name: str) -> str:
    """归一化法律名：去书名号、空白与「中华人民共和国」前缀。"""
    name = (name or "").strip().strip("《》").replace(" ", "")
    name = re.sub(r"^中华人民共和国", "", name)
    return name


class LawWhitelist:
    """基于知识库的法条白名单，带 TTL 缓存。"""

    def __init__(self, ttl_seconds: int = 1800):
        self._laws: dict[str, set[str]] = {}
        self._loaded_at: datetime | None = None
        self._ttl = timedelta(seconds=ttl_seconds)

    async def ensure_loaded(self, force: bool = False) -> None:
        """加载知识库全部 (法律名, 条号)，带 TTL 缓存。"""
        now = datetime.now()
        if (not force) and self._loaded_at and (now - self._loaded_at < self._ttl):
            return
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(KnowledgeArticle.law_name, KnowledgeArticle.article_number)
            )
            laws: dict[str, set[str]] = {}
            for law_name, article_number in result.all():
                key = normalize_law_name(law_name or "")
                if not key:
                    continue
                article = str(article_number or "").strip()
                if article:
                    laws.setdefault(key, set()).add(article)
            self._laws = laws
            self._loaded_at = now

    def __len__(self) -> int:
        return sum(len(v) for v in self._laws.values())

    @property
    def law_count(self) -> int:
        return len(self._laws)

    def verify(self, ref: str) -> dict:
        """校验单条法条引用。

        返回:
            {
              "status": "valid" | "invalid" | "unknown",
              "detail": str,        # 判定原因（用于日志/人工复核提示）
              "law": str | None,
              "article": str | None,
            }
        invalid = 法律名或条号确定不存在（幻觉法条）
        unknown = 白名单无法判断，需要调用方兜底（如语义检索）
        """
        law_match = LAW_NAME_RE.search(ref or "")
        article_match = ARTICLE_RE.search(ref or "")

        if not law_match or not article_match:
            return {
                "status": "unknown",
                "detail": "无法从引用中解析出「法律名 + 第X条」结构",
                "law": None,
                "article": None,
            }

        law_key = normalize_law_name(law_match.group(1))
        article_num = cn_article_to_int(article_match.group(1))
        if article_num is None or not law_key:
            return {
                "status": "unknown",
                "detail": "法律名或条号无法解析",
                "law": law_key,
                "article": None,
            }
        article_str = str(article_num)

        if not self._laws:
            return {
                "status": "unknown",
                "detail": "白名单为空（知识库未加载）",
                "law": law_key,
                "article": article_str,
            }

        # 法律名双向包含匹配（兼容简称），优先取名称最接近的候选
        candidates = [
            k for k in self._laws
            if law_key == k or law_key in k or k in law_key
        ]
        if not candidates:
            return {
                "status": "invalid",
                "detail": f"知识库中不存在《{law_key}》",
                "law": law_key,
                "article": article_str,
            }

        for k in sorted(candidates, key=len):
            if article_str in self._laws[k]:
                return {
                    "status": "valid",
                    "detail": f"命中《{k}》第{article_str}条",
                    "law": k,
                    "article": article_str,
                }

        return {
            "status": "invalid",
            "detail": f"《{law_key}》不存在第{article_str}条（知识库范围内）",
            "law": law_key,
            "article": article_str,
        }


# 模块级单例：整个进程共享缓存
law_whitelist = LawWhitelist()
