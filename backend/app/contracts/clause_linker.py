"""
文件：app/contracts/clause_linker.py
作用：解析合同中的跨条款引用，并在审查时合并上下文。

支持的引用表述：
- "详见第八条"
- "按照第五条执行"
- "依据第十条"
- "参见本合同第十二条"
- "如第 3.2 条所述"

设计原则：
- 规则基于通用引用模式，不是针对特定合同；
- 只合并被引用条款的文本，不过度拼接；
- 如找不到对应条款，保留原句并标注 unresolved。
"""

from __future__ import annotations

import re
from typing import Any


class ClauseLinker:
    """跨条款引用解析器。"""

    # 引用表述模式
    REFERENCE_PATTERNS = [
        re.compile(r"详见\s*第\s*([一二三四五六七八九十百零\d]+(?:\.\d+)?)\s*(?:条|款|项)"),
        re.compile(r"按照\s*第\s*([一二三四五六七八九十百零\d]+(?:\.\d+)?)\s*(?:条|款|项).{0,5}(?:执行|履行|办理|处理)"),
        re.compile(r"依据\s*第\s*([一二三四五六七八九十百零\d]+(?:\.\d+)?)\s*(?:条|款|项)"),
        re.compile(r"参见\s*(?:本合同第?|第)\s*([一二三四五六七八九十百零\d]+(?:\.\d+)?)\s*(?:条|款|项)"),
        re.compile(r"如\s*第\s*([一二三四五六七八九十百零\d]+(?:\.\d+)?)\s*(?:条|款|项).{0,5}所述"),
        re.compile(r"第\s*([一二三四五六七八九十百零\d]+(?:\.\d+)?)\s*(?:条|款|项).*?(?:为准|为准则)"),
    ]

    def __init__(self, clauses: list[dict[str, Any]] | None = None):
        self.clauses = clauses or []
        self._index: dict[str, dict[str, Any]] = {}
        self._build_index()

    def _build_index(self) -> None:
        """按条款编号构建索引。"""
        for clause in self.clauses:
            heading = clause.get("heading") or ""
            # 提取阿拉伯数字或中文数字编号
            numbers = self._extract_numbers(heading)
            for num in numbers:
                self._index.setdefault(num, clause)

    @staticmethod
    def _extract_numbers(heading: str) -> set[str]:
        """从标题中提取编号，如'第八条' -> {'8', '八'}。"""
        results: set[str] = set()
        # 中文数字
        cn_match = re.search(r"第([一二三四五六七八九十百零]+)(?:条|章|节|款|项)", heading)
        if cn_match:
            cn_num = cn_match.group(1)
            results.add(cn_num)
            # 尝试转为阿拉伯数字
            arabic = _chinese_to_arabic(cn_num)
            if arabic is not None:
                results.add(str(arabic))
        # 阿拉伯数字（含 3.2 这种）
        arabic_match = re.search(r"第(\d+(?:\.\d+)?)(?:条|章|节|款|项)", heading)
        if arabic_match:
            results.add(arabic_match.group(1))
        return results

    def resolve(self, clause_text: str, max_context_length: int = 800) -> dict[str, Any]:
        """
        解析 clause_text 中的引用，返回合并后的上下文。

        返回：
        {
          "original_text": str,
          "expanded_text": str,
          "references": [{"ref_num": str, "resolved": bool, "clause_text": str}, ...]
        }
        """
        references: list[dict[str, Any]] = []
        expanded_parts = [clause_text]

        for pattern in self.REFERENCE_PATTERNS:
            for match in pattern.finditer(clause_text):
                ref_num = match.group(1)
                referenced = self._index.get(ref_num)
                if referenced:
                    ref_text = referenced.get("text", "") or ""
                    # 截断过长上下文
                    if len(ref_text) > max_context_length:
                        ref_text = ref_text[:max_context_length] + "..."
                    references.append({
                        "ref_num": ref_num,
                        "resolved": True,
                        "clause_text": ref_text,
                    })
                    expanded_parts.append(f"\n【引用第{ref_num}条】{ref_text}")
                else:
                    references.append({
                        "ref_num": ref_num,
                        "resolved": False,
                        "clause_text": "",
                    })

        return {
            "original_text": clause_text,
            "expanded_text": "\n".join(expanded_parts).strip(),
            "references": references,
        }

    def resolve_all(self) -> list[dict[str, Any]]:
        """对所有条款解析引用并返回扩展后的条款列表。"""
        return [
            {
                **clause,
                "linked_context": self.resolve(clause.get("text", "")),
            }
            for clause in self.clauses
        ]


def _chinese_to_arabic(cn: str) -> int | None:
    """简单中文数字转阿拉伯数字，支持一~九十九。"""
    if not cn:
        return None

    cn_nums = {
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }

    if len(cn) == 1:
        return cn_nums.get(cn)

    if cn.startswith("十"):
        return 10 + (cn_nums.get(cn[1], 0) if len(cn) > 1 else 0)
    if cn.endswith("十"):
        return cn_nums.get(cn[0], 0) * 10

    if "十" in cn:
        parts = cn.split("十")
        tens = cn_nums.get(parts[0], 0) * 10
        ones = cn_nums.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens + ones

    # 累加，如 "十一" 已在上面处理，这里处理 "二十五"
    total = 0
    for ch in cn:
        if ch in cn_nums:
            total += cn_nums[ch]
    return total if total > 0 else None
