"""条款级版本对比服务（M3 双版本对比审查）。

对比策略：
1. difflib.SequenceMatcher 对两版条款文本序列求操作码，完全相同的条款视为 unchanged；
2. replace 块内部按文本相似度贪心配对，ratio >= 0.5 视为修改，否则拆成删除+新增；
3. 变更条款文本截断保存，报告页只做展示，不做二次检索。
"""

from difflib import SequenceMatcher
from typing import Any

_TEXT_TRUNCATE = 500
_MODIFIED_RATIO = 0.5


def extract_clauses(storage_path: str, file_type: str) -> list[dict[str, Any]]:
    """解析合同文件为条款列表（历史版本 parsed_data 已被覆盖，需现场重解析）。"""
    from app.contracts.parser import ContractParser

    parser = ContractParser()
    result = parser.parse(storage_path, file_type)
    return result.get("clauses", [])


def _brief(clause: dict[str, Any] | None) -> dict[str, str] | None:
    if not clause:
        return None
    return {
        "title": (clause.get("title") or "")[:200],
        "text": (clause.get("text") or "")[:_TEXT_TRUNCATE],
    }


def diff_clauses(base_clauses: list[dict], target_clauses: list[dict]) -> dict[str, Any]:
    """条款级 diff：返回统计与变更清单，每项 {type, base, target, ratio}。"""
    base_texts = [c.get("text") or "" for c in base_clauses]
    target_texts = [c.get("text") or "" for c in target_clauses]
    matcher = SequenceMatcher(a=base_texts, b=target_texts, autojunk=False)

    changes: list[dict[str, Any]] = []
    added = removed = modified = unchanged = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
        elif tag == "delete":
            for i in range(i1, i2):
                removed += 1
                changes.append({"type": "removed", "base": _brief(base_clauses[i]), "target": None, "ratio": None})
        elif tag == "insert":
            for j in range(j1, j2):
                added += 1
                changes.append({"type": "added", "base": None, "target": _brief(target_clauses[j]), "ratio": None})
        elif tag == "replace":
            block = _match_replace_block(base_clauses[i1:i2], target_clauses[j1:j2])
            modified += sum(1 for c in block if c["type"] == "modified")
            added += sum(1 for c in block if c["type"] == "added")
            removed += sum(1 for c in block if c["type"] == "removed")
            changes.extend(block)

    return {
        "summary": {
            "total_base": len(base_clauses),
            "total_target": len(target_clauses),
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": unchanged,
        },
        "changes": changes,
    }


def _match_replace_block(base_block: list[dict], target_block: list[dict]) -> list[dict]:
    """replace 块内按文本相似度贪心配对：相似视为修改，剩余归为新增/删除。"""
    pairs: list[tuple[int, int, float]] = []
    used_target: set[int] = set()
    for i, b in enumerate(base_block):
        best_j, best_ratio = -1, _MODIFIED_RATIO
        for j, t in enumerate(target_block):
            if j in used_target:
                continue
            ratio = SequenceMatcher(None, b.get("text") or "", t.get("text") or "").ratio()
            if ratio > best_ratio:
                best_j, best_ratio = j, ratio
        if best_j >= 0:
            pairs.append((i, best_j, best_ratio))
            used_target.add(best_j)

    used_base = {i for i, _, _ in pairs}
    result: list[dict[str, Any]] = []

    for i, j, ratio in pairs:
        result.append({
            "type": "modified",
            "base": _brief(base_block[i]),
            "target": _brief(target_block[j]),
            "ratio": round(ratio, 3),
        })

    for i, b in enumerate(base_block):
        if i not in used_base:
            result.append({"type": "removed", "base": _brief(b), "target": None, "ratio": None})
    for j, t in enumerate(target_block):
        if j not in used_target:
            result.append({"type": "added", "base": None, "target": _brief(t), "ratio": None})
    return result
