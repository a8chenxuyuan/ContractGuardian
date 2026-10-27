"""
文件：app/review/learning.py
作用：收集和统计 detector/Critic 的“反例”——即系统曾经误判、后被规则或 LLM 纠正的案例模式。

设计目标：
- 不针对具体合同文本，而是抽象出“误判模式”；
- 支持按风险类型、规则、证据类型聚合；
- 为持续改进 detector/Critic 规则提供数据支撑。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 默认存储路径：项目根目录下的 learning 文件夹
DEFAULT_STORE_DIR = Path(__file__).resolve().parent.parent.parent / "learning"


class CounterExampleStore:
    """
    反例存储。

    每条反例记录包含：
    - pattern: 误判模式摘要（如"否定语境下的违法目的"）
    - risk_type: 风险类型
    - rule: 触发纠正的规则或来源
    - evidence_type: 原始证据类型（keyword_match / semantic_inference / numeric_violation）
    - contract_type: 合同类型
    - reason: 被过滤前的理由
    - corrected_reason: 纠正后的理由
    - timestamp: 时间戳
    """

    def __init__(self, store_dir: str | Path | None = None):
        self.store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.store_dir / "counter_examples.jsonl"

    def add(
        self,
        pattern: str,
        risk_type: str,
        rule: str,
        evidence_type: str = "keyword_match",
        contract_type: str = "通用",
        reason: str = "",
        corrected_reason: str = "",
        metadata: dict[str, Any] | None = None,
        dedupe: bool = False,
    ) -> None:
        """添加一条反例记录。

        dedupe=True 时按 (pattern, risk_type, evidence_type) 判重，
        已存在的模式只更新 timestamp 不重复追加，供回测脚本反复运行不刷爆库。
        """
        if dedupe:
            existing = {
                (r.get("pattern", ""), r.get("risk_type", ""), r.get("evidence_type", ""))
                for r in self.load_all()
            }
            if (pattern, risk_type, evidence_type) in existing:
                return
        record = {
            "pattern": pattern,
            "risk_type": risk_type,
            "rule": rule,
            "evidence_type": evidence_type,
            "contract_type": contract_type,
            "reason": reason[:300],
            "corrected_reason": corrected_reason[:300],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        with open(self.store_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        """加载所有反例记录。"""
        if not self.store_file.exists():
            return []
        records = []
        with open(self.store_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def record_wrong_citation(
        self,
        law_name: str,
        article_number: str,
        reason: str,
        contract_type: str = "通用",
    ) -> None:
        """记录「引用了某法条但结论错误」的用户反馈（M5 检索负样本回流）。

        该法条之后会在检索层被降权（score × 0.5），逐步减少同类误引用。
        """
        self.add(
            pattern=f"误引用 {law_name}{article_number}",
            risk_type="citation_error",
            rule="user_feedback",
            evidence_type="retrieval_negative",
            contract_type=contract_type,
            reason=reason,
            metadata={"law_name": law_name, "article_number": article_number},
        )

    def get_negative_law_keys(self) -> set[str]:
        """负样本法条 key 集合（law_name|article_number），供检索降权。"""
        keys: set[str] = set()
        for r in self.load_all():
            if r.get("evidence_type") != "retrieval_negative":
                continue
            meta = r.get("metadata") or {}
            law = meta.get("law_name")
            if law:
                keys.add(f"{law}|{meta.get('article_number', '')}")
        return keys

    def get_top_patterns(
        self,
        n: int = 10,
        days: int | None = None,
        evidence_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        统计 Top N 误判模式。

        返回每条模式的出现次数、涉及的风险类型、最近时间。
        """
        records = self.load_all()
        if days is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
            records = [
                r for r in records
                if datetime.fromisoformat(r["timestamp"]).timestamp() >= cutoff
            ]
        if evidence_type:
            records = [r for r in records if r.get("evidence_type") == evidence_type]

        grouped: dict[str, dict[str, Any]] = {}
        for r in records:
            key = (r.get("pattern", ""), r.get("risk_type", ""), r.get("rule", ""))
            if key not in grouped:
                grouped[key] = {
                    "pattern": r.get("pattern", ""),
                    "risk_type": r.get("risk_type", ""),
                    "rule": r.get("rule", ""),
                    "count": 0,
                    "evidence_types": set(),
                    "contract_types": set(),
                    "latest": r.get("timestamp", ""),
                    # 带一条纠正样例，供 prompt 回灌时展示"应该怎么改"
                    "sample_correction": r.get("corrected_reason", ""),
                }
            grouped[key]["count"] += 1
            grouped[key]["evidence_types"].add(r.get("evidence_type", ""))
            grouped[key]["contract_types"].add(r.get("contract_type", ""))
            if r.get("timestamp", "") > grouped[key]["latest"]:
                grouped[key]["latest"] = r["timestamp"]

        # 转 set 为 list 以便 JSON 序列化
        for g in grouped.values():
            g["evidence_types"] = sorted(g["evidence_types"])
            g["contract_types"] = sorted(g["contract_types"])

        sorted_patterns = sorted(
            grouped.values(), key=lambda x: x["count"], reverse=True
        )
        return sorted_patterns[:n]


# 全局默认实例（非单例，但便于直接导入使用）
def get_counter_example_store(store_dir: str | Path | None = None) -> CounterExampleStore:
    return CounterExampleStore(store_dir)
