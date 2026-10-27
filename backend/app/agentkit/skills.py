"""
文件：app/agentkit/skills.py
作用：技能仓库运行时加载（协议 docs/protocols/plugin_registry.md §1）。

skills/index.json 为注册清单（id/name/keywords/entry/doc），
本模块负责：加载清单 → 按触发关键词匹配 → 渲染为 prompt 片段。
新技能 = 往 skills/ 加一个目录 + index.json 登记一条，代码零改动。

匹配为关键词命中打分（首发实现）；触发条件：准确率不够再升级语义匹配。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
INDEX_FILE = SKILLS_DIR / "index.json"

# 渲染时单个技能正文的最大字符数（总量还受 skills 层预算约束）
MAX_SKILL_CHARS = 2500


@dataclass
class Skill:
    """一项已注册技能。"""

    id: str
    name: str
    summary: str
    trigger: str
    keywords: list[str]
    entry: str
    doc: str

    @property
    def doc_path(self) -> Path:
        return SKILLS_DIR.parent / self.doc


_cache: list[Skill] | None = None


def load_skills() -> list[Skill]:
    """加载技能清单（进程内缓存一次）。"""
    global _cache
    if _cache is None:
        with open(INDEX_FILE, encoding="utf-8") as f:
            data = json.load(f)
        _cache = [
            Skill(
                id=item["id"],
                name=item["name"],
                summary=item.get("summary", ""),
                trigger=item.get("trigger", ""),
                keywords=item.get("keywords", []),
                entry=item.get("entry", ""),
                doc=item.get("doc", ""),
            )
            for item in data.get("skills", [])
        ]
    return _cache


def reload_skills() -> list[Skill]:
    """强制重新加载（index.json 变更后调用，测试也用它）。"""
    global _cache
    _cache = None
    return load_skills()


def match_skills(text: str, top_k: int = 2) -> list[tuple[Skill, int]]:
    """按触发关键词匹配技能，返回 [(skill, 命中数)]，命中数降序。"""
    if not text:
        return []
    scored: list[tuple[Skill, int]] = []
    for skill in load_skills():
        score = sum(1 for kw in skill.keywords if kw and kw in text)
        if score > 0:
            scored.append((skill, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def render_skills(matched: list[tuple[Skill, int]]) -> str:
    """把匹配到的技能渲染为 prompt 片段（正文截到 MAX_SKILL_CHARS）。"""
    if not matched:
        return ""
    blocks = []
    for skill, _score in matched:
        body = ""
        try:
            body = skill.doc_path.read_text(encoding="utf-8").strip()
        except OSError:
            body = "（技能正文缺失）"
        if len(body) > MAX_SKILL_CHARS:
            body = body[:MAX_SKILL_CHARS] + "\n…[技能正文截断]"
        blocks.append(
            f"### 技能：{skill.name}\n"
            f"适用：{skill.trigger}\n"
            f"实现入口：{skill.entry}\n\n{body}"
        )
    return "\n\n".join(blocks)
