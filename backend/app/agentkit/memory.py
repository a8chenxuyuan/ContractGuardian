"""
文件：app/agentkit/memory.py
作用：跨会话用户记忆（架构 L5，协议 docs/plans/platform_upgrade_v2.md M2'）。

存储：memory/users/{user_id}.jsonl，每条 {timestamp, kind, text}。
防膨胀：单用户封顶 20 条（留最新）、每条 200 字内。
读取：渲染为 prompt 记忆层，经 ContextManager.assemble() 注入（Layer "memory"）。

不做：三层记忆/向量化检索——触发条件：偏好条目需要跨类型语义检索时。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory" / "users"
MAX_ENTRIES = 20
MAX_TEXT_CHARS = 200


def _memory_file(user_id: int | str) -> Path:
    # 用户 ID 进入文件路径，仅允许数字与字母下划线，防路径穿越
    safe = "".join(ch for ch in str(user_id) if ch.isalnum() or ch == "_")
    if not safe:
        raise ValueError(f"非法 user_id: {user_id!r}")
    return MEMORY_DIR / f"{safe}.jsonl"


def add_memory(user_id: int | str, kind: str, text: str) -> bool:
    """写入一条用户记忆；封顶 20 条（超限丢最旧）。返回是否写入成功。"""
    if not text or not text.strip():
        return False
    path = _memory_file(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    entries = load_memory_entries(user_id)
    entries.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "text": text.strip()[:MAX_TEXT_CHARS],
        }
    )
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]

    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def load_memory_entries(user_id: int | str) -> list[dict]:
    """读取该用户全部记忆条目（文件缺失返回空）。"""
    path = _memory_file(user_id)
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def render_memory(user_id: int | str, top_n: int = 5) -> str:
    """渲染最近 top_n 条记忆为 prompt 片段；无记忆返回空串。"""
    entries = load_memory_entries(user_id)[-top_n:]
    if not entries:
        return ""
    kind_label = {
        "dismissed_risk": "已确认的误报（同类不再报）",
        "preference": "用户显式偏好",
    }
    lines = []
    for e in entries:
        label = kind_label.get(e.get("kind", ""), e.get("kind", "记录"))
        lines.append(f"- [{label}] {e.get('text', '')}")
    return "\n".join(lines)


# 追问中的显式偏好识别（触发条件词表，识别到即写入记忆）
PREFERENCE_PATTERN = r"(以后(请)?(不要|别)|别再|下次别|不要(再)?报|以后只)"


def maybe_record_preference(user_id: int | str, question: str) -> bool:
    """检测追问中的显式偏好句式并写入记忆；未命中返回 False。"""
    import re

    if not question or not re.search(PREFERENCE_PATTERN, question):
        return False
    return add_memory(user_id, "preference", question)
