"""关键履约日期提取（D3 履约日期管家）。

正则匹配中文合同常见日期写法，按上下文关键词归类（到期 > 生效 > 签订 > 付款 > 交付），
同日期同类型去重。只提取带年份的具体日期，"每月5日"等周期性表述不视为履约节点。
"""

import re
from datetime import date

_PATTERNS = [
    re.compile(r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    re.compile(r"(?P<y>\d{4})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})"),
]

_TYPE_KEYWORDS = [
    ("expiry", ("到期", "届满", "有效期至", "截止", "终止日", "失效")),
    ("effective", ("生效", "之日起执行", "起施行")),
    ("signing", ("签订", "签署", "订立")),
    ("payment", ("付款", "支付", "缴费", "缴纳", "结算")),
    ("delivery", ("交付", "验收", "竣工", "完成")),
]

_CONTEXT_WINDOW = 30
_PRIORITY = {"expiry": 0, "effective": 1, "signing": 2, "payment": 3, "delivery": 4, "other": 5}


def _classify(context: str) -> str:
    for dtype, keywords in _TYPE_KEYWORDS:
        if any(keyword in context for keyword in keywords):
            return dtype
    return "other"


def _valid_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        # 误匹配（如金额 1,234.56）直接丢弃
        return None


def extract_key_dates(clauses: list[dict]) -> list[dict]:
    """从条款列表提取关键日期，返回 [{date_value, date_type, raw_text, context}]。"""
    found: dict[tuple, dict] = {}
    for clause in clauses:
        text = clause.get("text") or ""
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                dt = _valid_date(int(match["y"]), int(match["m"]), int(match["d"]))
                if not dt:
                    continue
                start = max(0, match.start() - _CONTEXT_WINDOW)
                end = min(len(text), match.end() + _CONTEXT_WINDOW)
                context = text[start:end].replace("\n", " ").strip()
                dtype = _classify(context)
                key = (dt, dtype)
                if key not in found:
                    found[key] = {
                        "date_value": dt,
                        "date_type": dtype,
                        "raw_text": match.group(0)[:50],
                        "context": context[:160],
                    }

    return sorted(found.values(), key=lambda x: (_PRIORITY.get(x["date_type"], 9), x["date_value"]))
