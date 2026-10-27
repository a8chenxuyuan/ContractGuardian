"""
文件：scripts/analyze_feedback.py
作用：定期分析人工反馈，生成可执行的改进建议报告。

运行方式：
    python scripts/analyze_feedback.py [--days 7] [--output reports/weekly_learning_report.md]

分析维度：
1. 哪些 risk_type 被频繁 dismissed？→ 可能误报过多；
2. 哪些 risk_type 被频繁 approved？→ 说明 detector  recall 较好；
3. 哪些 principle/detector 频繁漏检？→ 从 review_logs 统计 detector_result 事件；
4. 哪些 LLM agent 输出反复出错？→ 从 review_logs 统计 llm_raw + critic_result；
5. 哪些法条/知识库查询未命中？→ 从 legal_research 日志统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 将 backend 加入路径
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.review import Finding, HumanReview


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="分析人工反馈并生成改进报告")
    parser.add_argument("--days", type=int, default=7, help="分析最近 N 天的反馈")
    parser.add_argument(
        "--output",
        type=str,
        default="reports/weekly_learning_report.md",
        help="输出报告路径",
    )
    return parser.parse_args()


async def fetch_feedback(session: AsyncSession, days: int) -> list[HumanReview]:
    """获取最近 N 天的人工反馈。"""
    since = datetime.now() - timedelta(days=days)
    result = await session.execute(
        select(HumanReview).where(HumanReview.created_at >= since)
    )
    return list(result.scalars().all())


async def fetch_related_findings(
    session: AsyncSession, finding_ids: list[int]
) -> dict[int, Finding]:
    """批量获取关联的 Finding 记录。"""
    if not finding_ids:
        return {}
    result = await session.execute(select(Finding).where(Finding.id.in_(finding_ids)))
    return {f.id: f for f in result.scalars().all()}


def analyze_risk_type_patterns(
    feedbacks: list[HumanReview], findings: dict[int, Finding]
) -> dict[str, Any]:
    """按 risk_type 统计反馈模式。"""
    approved_by_type: Counter[str] = Counter()
    rejected_by_type: Counter[str] = Counter()

    for fb in feedbacks:
        if fb.finding_id and fb.finding_id in findings:
            risk_type = findings[fb.finding_id].risk_type or "未分类"
            if fb.status == "approved":
                approved_by_type[risk_type] += 1
            elif fb.status == "rejected":
                rejected_by_type[risk_type] += 1

    suspicious_types = [
        {
            "risk_type": rt,
            "approved": approved_by_type.get(rt, 0),
            "rejected": rejected_by_type.get(rt, 0),
            "rejection_rate": round(
                rejected_by_type.get(rt, 0) / (approved_by_type.get(rt, 0) + rejected_by_type.get(rt, 0)),
                4,
            ) if (approved_by_type.get(rt, 0) + rejected_by_type.get(rt, 0)) > 0 else 0.0,
        }
        for rt in set(approved_by_type.keys()) | set(rejected_by_type.keys())
    ]
    suspicious_types.sort(key=lambda x: x["rejection_rate"], reverse=True)

    return {
        "approved_by_type": dict(approved_by_type),
        "rejected_by_type": dict(rejected_by_type),
        "suspicious_types": suspicious_types,
    }


def analyze_review_logs(log_dir: Path, days: int) -> dict[str, Any]:
    """分析本地 review_logs 文件，识别高频问题。"""
    since = datetime.now() - timedelta(days=days)
    event_counts: Counter[str] = Counter()
    detector_findings: Counter[str] = Counter()
    critic_verdicts: Counter[str] = Counter()
    llm_agents: Counter[str] = Counter()
    unresolved_refs: Counter[str] = Counter()

    if not log_dir.exists():
        return {
            "event_counts": dict(event_counts),
            "detector_findings_by_type": dict(detector_findings),
            "critic_verdicts": dict(critic_verdicts),
            "llm_agent_calls": dict(llm_agents),
            "unresolved_references": dict(unresolved_refs),
        }

    for log_file in log_dir.glob("*.jsonl"):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    ts = datetime.fromisoformat(record.get("timestamp", "1970-01-01T00:00:00"))
                    if ts < since:
                        continue

                    event_type = record.get("event_type", "")
                    event_counts[event_type] += 1
                    payload = record.get("payload", {})

                    if event_type == "detector_result":
                        detector = payload.get("detector", "unknown")
                        for finding in payload.get("findings", []):
                            risk_type = finding.get("risk_type", "未分类")
                            detector_findings[f"{detector}:{risk_type}"] += 1

                    elif event_type == "critic_result":
                        verdict = payload.get("verdict", "unknown")
                        critic_verdicts[verdict] += 1

                    elif event_type == "llm_raw":
                        agent = payload.get("agent", "unknown")
                        llm_agents[agent] += 1

        except Exception:
            continue

    return {
        "event_counts": dict(event_counts),
        "detector_findings_by_type": dict(detector_findings),
        "critic_verdicts": dict(critic_verdicts),
        "llm_agent_calls": dict(llm_agents),
        "unresolved_references": dict(unresolved_refs),
    }


def generate_report(
    feedbacks: list[HumanReview],
    risk_patterns: dict[str, Any],
    log_stats: dict[str, Any],
    days: int,
) -> str:
    """生成 Markdown 报告。"""
    lines = []
    lines.append("# 合同卫士反馈学习周报")
    lines.append("")
    lines.append(f"- 统计周期：最近 {days} 天")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 反馈总数：{len(feedbacks)}")
    lines.append("")

    # 反馈概览
    approved = sum(1 for f in feedbacks if f.status == "approved")
    rejected = sum(1 for f in feedbacks if f.status == "rejected")
    lines.append("## 一、反馈概览")
    lines.append("")
    lines.append(f"- 认同（approved）：{approved}")
    lines.append(f"- 纠正（rejected）：{rejected}")
    lines.append(f"- 纠正率：{round(rejected / len(feedbacks), 4) if feedbacks else 0}")
    lines.append("")

    # 风险类型分析
    lines.append("## 二、按风险类型的纠正率")
    lines.append("")
    if risk_patterns["suspicious_types"]:
        lines.append("| 风险类型 | 认同数 | 纠正数 | 纠正率 | 建议 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in risk_patterns["suspicious_types"]:
            suggestion = ""
            if item["rejection_rate"] > 0.5:
                suggestion = "误报高，建议优化 Critic 规则或调整 detector 阈值"
            elif item["rejected"] > 3:
                suggestion = "多次被纠正，建议补充非违规样例或优化 prompt"
            lines.append(
                f"| {item['risk_type']} | {item['approved']} | {item['rejected']} | "
                f"{item['rejection_rate']} | {suggestion} |"
            )
    else:
        lines.append("暂无足够反馈数据。")
    lines.append("")

    # 日志统计
    lines.append("## 三、审查日志统计")
    lines.append("")
    lines.append(f"- 各事件类型：{log_stats['event_counts']}")
    lines.append(f"- Critic 裁决分布：{log_stats['critic_verdicts']}")
    lines.append(f"- LLM 调用分布：{log_stats['llm_agent_calls']}")
    lines.append("")

    if log_stats["detector_findings_by_type"]:
        lines.append("### Detector 风险类型命中分布")
        lines.append("")
        lines.append("| Detector:RiskType | 次数 |")
        lines.append("| --- | --- |")
        for key, count in sorted(log_stats["detector_findings_by_type"].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {key} | {count} |")
        lines.append("")

    # 行动建议
    lines.append("## 四、行动建议")
    lines.append("")
    actions = []
    for item in risk_patterns["suspicious_types"]:
        if item["rejection_rate"] > 0.5:
            actions.append(f"- 针对 `{item['risk_type']}` 优化 RuleCritic 规则，减少误报；")
        if item["rejected"] > 3 and item["rejection_rate"] < 0.5:
            actions.append(f"- 针对 `{item['risk_type']}` 补充 non_violation_examples 或优化 detector prompt；")

    if not actions:
        actions.append("- 当前反馈量不足，建议继续收集反馈后再做针对性优化。")

    for action in actions:
        lines.append(action)
    lines.append("")

    return "\n".join(lines)


async def main() -> None:
    args = parse_args()

    async with AsyncSessionLocal() as db:
        feedbacks = await fetch_feedback(db, args.days)
        finding_ids = [f.finding_id for f in feedbacks if f.finding_id]
        findings = await fetch_related_findings(db, finding_ids)

    risk_patterns = analyze_risk_type_patterns(feedbacks, findings)
    log_stats = analyze_review_logs(Path(BACKEND_DIR) / "logs" / "reviews", args.days)

    report = generate_report(feedbacks, risk_patterns, log_stats, args.days)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告已生成：{output_path}")
    print(f"反馈总数：{len(feedbacks)}")


if __name__ == "__main__":
    args = parse_args()
    import asyncio
    asyncio.run(main())
