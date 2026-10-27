"""
文件：app/rag/chunker.py
作用：父子两级切块（Parent-Child Chunking）。

设计动机（为什么）：
- 直接对整条条款（可能 2000+ 字）做向量编码，会把多个主题混进一个向量里，
  导致"主题命中但语义被稀释"——检索阶段召回不准；
- 只存小块又会在生成阶段丢失上下文。
- 因此拆成两层：父块（条款级，供 LLM 生成用）+ 子块（200-400 字，供向量检索用），
  子块命中后返回其父块全文。

切块规则：
- 父块：以条款（parser 产出的 clause）为单位；超过 PARENT_MAX_LEN 时按句边界再分段；
- 子块：按句边界贪心打包到 CHILD_MAX_LEN；相邻子块共享上一块的最后一个整句（overlap），
  避免关键句正好跨切块边界导致两块都检索不到。
"""

from __future__ import annotations

from typing import Any

# 子块超过该长度时单句内部按逗号级别再切
CHILD_MAX_LEN = 400
CHILD_MIN_LEN = 180
PARENT_MAX_LEN = 2000
# 单个 overlap 句子最长长度，避免上一块末尾一整段都被重复带上下块
OVERLAP_SENT_MAX_LEN = 100

# 句子终止符（中文合同为主，兼容英文标点与换行）
_SENT_END_CHARS = set("。！？；!?;\n")
# 句内次级切分符：单句超过 max_len 时用逗号级别续切
_SUB_SENT_SPLIT = set("，、,:：")


def split_sentences(text: str) -> list[str]:
    """按句终止符切分文本，分隔符保留在句尾。"""
    sentences: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in _SENT_END_CHARS:
            s = "".join(buf).strip()
            if s:
                sentences.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_long_sentence(sentence: str, max_len: int) -> list[str]:
    """单句超长时按逗号级别切分，仍超长则按定长硬切。"""
    if len(sentence) <= max_len:
        return [sentence]

    parts: list[str] = []
    buf = ""
    for ch in sentence:
        buf += ch
        if ch in _SUB_SENT_SPLIT and len(buf) >= max_len // 2:
            parts.append(buf)
            buf = ""
    if buf.strip():
        parts.append(buf)

    # 逗号级别仍超长的极端情况（如无标点长串）按定长硬切
    result: list[str] = []
    for p in parts:
        while len(p) > max_len:
            result.append(p[:max_len])
            p = p[max_len:]
        if p.strip():
            result.append(p)
    return result


def build_child_chunks(
    text: str,
    max_len: int = CHILD_MAX_LEN,
    min_len: int = CHILD_MIN_LEN,
    overlap: bool = True,
) -> list[dict[str, Any]]:
    """将父块文本切成子块列表。

    返回 [{"index": 0, "text": "..."}]，text 已做空白归一。
    """
    clean = " ".join(text.split())
    if not clean:
        return []

    # 1) 句级切分 + 超长句续切
    units: list[str] = []
    for s in split_sentences(clean):
        units.extend(_split_long_sentence(s, max_len))

    # 2) 贪心打包：尽量凑满 max_len，直接拼接（split_sentences 已含句尾标点）
    children: list[dict[str, Any]] = []
    buf = ""

    def _flush() -> None:
        nonlocal buf
        if buf.strip():
            children.append({"index": len(children), "text": buf.strip()})
        buf = ""

    for u in units:
        candidate = f"{buf}{u}"
        if len(candidate) <= max_len:
            buf = candidate
        else:
            _flush()
            buf = u

    _flush()

    # 2.5) 末尾孤儿块合并：最后一块过短时并入前一块（检索价值太低，还浪费一次编码）
    if len(children) >= 2 and len(children[-1]["text"]) < min_len:
        prev = children[-2]
        if len(prev["text"]) + len(children[-1]["text"]) <= max_len + min_len:
            prev["text"] = f"{prev['text']}{children[-1]['text']}"
            children.pop()

    # 3) 回填 overlap：每个子块开头拼上一子块的最后一个整句
    if overlap and len(children) > 1:
        prev_tail = ""
        for child in children:
            if prev_tail and len(prev_tail) <= OVERLAP_SENT_MAX_LEN:
                # 防止 overlap 后反而超长太多
                if len(prev_tail) + len(child["text"]) <= max_len + OVERLAP_SENT_MAX_LEN:
                    child["text"] = f"{prev_tail}{child['text']}"
            prev_tail = _tail_sentence_of(child["text"])

    return children


def _tail_sentence_of(text: str) -> str:
    """取文本最后一个完整句（含句尾标点）。"""
    sentences = split_sentences(text)
    return sentences[-1] if sentences else text


def build_parents_and_children(
    clauses: list[dict[str, Any]],
    parent_max_len: int = PARENT_MAX_LEN,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把 parser 产出的条款列表拆成 (parents, children)。

    输入 clause：{id, heading, title, text, page, section_path}
    输出 parent：{parent_id, section_path, title, text, page, part_index}
    输出 child ：{parent_id, index, text, section_path, title, page}
    """
    parents: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []

    for clause in clauses:
        clause_id = str(clause.get("id") or f"clause_{len(parents)}")
        section_path = clause.get("section_path", "")
        title = clause.get("title") or clause.get("heading") or ""
        page = clause.get("page", 1)
        text = clause.get("text", "") or ""

        if not text.strip():
            continue

        # 超长条款按句边界拆成多个父块，避免单向量过度稀释
        if len(text) <= parent_max_len:
            segments = [text]
        else:
            segments = []
            buf = ""
            for s in split_sentences(text):
                if buf and len(buf) + len(s) > parent_max_len:
                    segments.append(buf)
                    buf = s
                else:
                    buf = f"{buf}{s}" if buf else s
            if buf.strip():
                segments.append(buf)

        for part_idx, seg in enumerate(segments):
            parent_id = clause_id if len(segments) == 1 else f"{clause_id}#p{part_idx}"
            part_path = (
                section_path
                if len(segments) == 1
                else f"{section_path}({part_idx + 1}/{len(segments)})"
            )
            parents.append(
                {
                    "parent_id": parent_id,
                    "section_path": part_path,
                    "title": title,
                    "text": seg,
                    "page": page,
                    "part_index": part_idx,
                }
            )
            for child in build_child_chunks(seg):
                children.append(
                    {
                        "parent_id": parent_id,
                        "index": child["index"],
                        "text": child["text"],
                        "section_path": part_path,
                        "title": title,
                        "page": page,
                    }
                )

    return parents, children


def build_knowledge_children(
    article_text: str,
    max_len: int = CHILD_MAX_LEN,
) -> list[dict[str, Any]]:
    """法律条文的子块切分。法条通常较短（<400 字），此时只有单子块（即父块本身）。"""
    return build_child_chunks(article_text, max_len=max_len, overlap=False)
