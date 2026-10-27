"""
文件：scripts/run_review_backtest.py
作用：M1 数据闭环的回测入口——读黄金集测试结果算指标、FP/FN 自动回流反例库、
     与上一轮 baseline 对比，生成结构化审查报告（含 trace 运行概览）。

闭环链路：
    黄金集回测 → 反例库(backtest_fp/backtest_fn) → RiskReview prompt 注入 → 下轮审查/回测验证

运行方式（LLM 配额受限时也完全离线可用，只读现成结果文件）：
    python scripts/run_review_backtest.py [--results <summary.json>] [--no-trace]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 将 backend 加入路径
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.metrics import (  # noqa: E402
    compare_with_baseline,
    compute_clause_level_metrics,
    compute_contract_level_metrics,
    load_annotations,
)
from app.review.learning import get_counter_example_store  # noqa: E402

# 黄金集位于项目根的 测试集/ 目录（backend 的上两级）
GOLDEN_SET_DIR = BACKEND_DIR.parent.parent / "测试集"
DEFAULT_RESULTS = GOLDEN_SET_DIR / "full_test_summary.json"
DEFAULT_ANNOTATIONS = GOLDEN_SET_DIR / "annotations.example.json"
BASELINE_FILE = GOLDEN_SET_DIR / "backtest_baseline.json"
REPORT_DIR = BACKEND_DIR / "reports"
TRACE_DIR = BACKEND_DIR / "logs" / "reviews"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="黄金集回测 + 反例回流 + 报告生成")
    parser.add_argument("--results", type=str, default=str(DEFAULT_RESULTS), help="测试结果 JSON 路径")
    parser.add_argument("--annotations", type=str, default=str(DEFAULT_ANNOTATIONS), help="条款级标注 JSON 路径")
    parser.add_argument("--no-trace", action="store_true", help="跳过 trace 日志概览")
    parser.add_argument("--no-reflow", action="store_true", help="只算指标不写反例库")
    parser.add_argument("--output", type=str, default="", help="报告输出路径（默认 reports/backtest_report_时间戳.md）")
    return parser.parse_args()


def load_results(path: Path) -> list[dict[str, Any]]:
    """读测试结果文件，兼容 contracts_summary / contracts 两种键名。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("contracts") or data.get("contracts_summary") or []


def reflow_counter_examples(
    contracts: list[dict[str, Any]],
    clause_metrics: dict[str, Any] | None,
    annotations_index: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """把回测 FP/FN 写入反例库（去重），返回各类回流条数。"""
    store = get_counter_example_store()
    stats = {"fp": 0, "fn": 0, "skipped_fp": 0, "skipped_fn": 0}

    for c in contracts:
        filename = c.get("filename", "")
        contract_type = c.get("contract_type", "通用")
        legal = c.get("legal", True)
        findings = c.get("findings", [])

        # 合同级 FP：黄金集标注合法却报了风险 → 每条误报 finding 回流
        if legal and findings:
            for f in findings:
                before = len(store.load_all())
                store.add(
                    pattern=f"合法合同误报：{f.get('risk_type', '未知风险')}",
                    risk_type=f.get("risk_type", ""),
                    rule="golden_set_backtest",
                    evidence_type="backtest_fp",
                    contract_type=contract_type,
                    reason=f.get("clause_text", "") or f.get("reason", ""),
                    corrected_reason=f"黄金集标注 {filename} 为合法合同，该情形不应报告为风险",
                    metadata={"filename": filename},
                    dedupe=True,
                )
                if len(store.load_all()) > before:
                    stats["fp"] += 1
                else:
                    stats["skipped_fp"] += 1

        # 合同级 FN：黄金集标注违法却零检出 → 整体漏检回流
        if not legal and not findings:
            expected = c.get("expected_issues") or []
            before = len(store.load_all())
            store.add(
                pattern=f"违法合同整体漏检：{contract_type}",
                risk_type="整体漏检",
                rule="golden_set_backtest",
                evidence_type="backtest_fn",
                contract_type=contract_type,
                reason=f"{filename} 预期风险：{'; '.join(str(x) for x in expected[:3])}",
                corrected_reason="该合同黄金集标注为违法且存在预期问题，审查应至少检出一条",
                metadata={"filename": filename},
                dedupe=True,
            )
            if len(store.load_all()) > before:
                stats["fn"] += 1
            else:
                stats["skipped_fn"] += 1

    # 条款级细粒度回流（仅限标注文件实际覆盖的合同——未覆盖=不可评估，不回流）
    if clause_metrics:
        for item in clause_metrics.get("unmatched_findings", []):
            if item.get("filename") not in annotations_index:
                continue
            finding = item.get("finding", {})
            before = len(store.load_all())
            store.add(
                pattern=f"条款误报：{finding.get('risk_type', '')}",
                risk_type=finding.get("risk_type", ""),
                rule="golden_set_backtest_clause",
                evidence_type="backtest_fp",
                reason=finding.get("clause_text", "")[:200],
                corrected_reason="与黄金集条款标注不匹配的误报",
                metadata={"filename": item.get("filename", "")},
                dedupe=True,
            )
            if len(store.load_all()) > before:
                stats["fp"] += 1
            else:
                stats["skipped_fp"] += 1
        for item in clause_metrics.get("unmatched_annotations", []):
            if item.get("filename") not in annotations_index:
                continue
            ann = item.get("annotation", {})
            before = len(store.load_all())
            store.add(
                pattern=f"条款漏检：{ann.get('risk_type', '')}",
                risk_type=ann.get("risk_type", ""),
                rule="golden_set_backtest_clause",
                evidence_type="backtest_fn",
                reason=ann.get("clause_text", "")[:200],
                corrected_reason="黄金集已标注该条款风险但审查未检出",
                metadata={"filename": item.get("filename", "")},
                dedupe=True,
            )
            if len(store.load_all()) > before:
                stats["fn"] += 1
            else:
                stats["skipped_fn"] += 1

    return stats


def trace_overview() -> dict[str, Any] | None:
    """汇总 logs/reviews/*.jsonl trace：审查场次、事件数、平均耗时。"""
    if not TRACE_DIR.exists():
        return None
    files = sorted(TRACE_DIR.glob("*.jsonl"))
    if not files:
        return None
    total_events = 0
    elapsed_list: list[float] = []
    for fp in files:
        events = 0
        last_elapsed = 0.0
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                events += 1
                try:
                    last_elapsed = json.loads(line).get("elapsed", last_elapsed)
                except json.JSONDecodeError:
                    continue
        total_events += events
        elapsed_list.append(last_elapsed)
    return {
        "sessions": len(files),
        "total_events": total_events,
        "avg_elapsed": round(sum(elapsed_list) / len(elapsed_list), 2) if elapsed_list else 0.0,
    }


def load_previous_baseline() -> dict[str, Any] | None:
    if not BASELINE_FILE.exists():
        return None
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_baseline(contract_level: dict[str, Any], clause_level: dict[str, Any] | None) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "contract_level": contract_level,
        "clause_level": clause_level,
    }
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def build_report(
    contract_level: dict[str, Any],
    clause_level: dict[str, Any] | None,
    delta: dict[str, Any] | None,
    reflow: dict[str, int],
    trace: dict[str, Any] | None,
    n_contracts: int,
) -> str:
    """生成 markdown 结构化审查报告。"""
    ov = contract_level.get("overall", {})
    lines = [
        "# 黄金集回测报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 样本量：{n_contracts} 份合同（黄金集）",
        "",
        "## 一、合同级指标",
        "",
        "| precision | recall | F1 | FP | FN | 误报率 | 漏检率 |",
        "|---|---|---|---|---|---|---|",
        f"| {ov.get('precision')} | {ov.get('recall')} | {ov.get('f1')} | {ov.get('tp')} / {ov.get('fp')} "
        f"| {ov.get('fn')} | {ov.get('false_positive_rate')} | {ov.get('false_negative_rate')} |",
        "",
    ]

    # 分类型指标
    per_type = contract_level.get("per_contract_type", {})
    if per_type:
        lines += ["## 二、分合同类型指标", "", "| 合同类型 | precision | recall | F1 | FP | FN |", "|---|---|---|---|---|---|"]
        for t, m in per_type.items():
            lines.append(f"| {t} | {m['precision']} | {m['recall']} | {m['f1']} | {m['fp']} | {m['fn']} |")
        lines.append("")

    if clause_level:
        cov = clause_level.get("overall", {})
        lines += [
            "## 三、条款级指标（基于现有标注）",
            "",
            "| precision | recall | F1 | TP | FP | FN |",
            "|---|---|---|---|---|---|",
            f"| {cov.get('precision')} | {cov.get('recall')} | {cov.get('f1')} | {cov.get('tp')} | {cov.get('fp')} | {cov.get('fn')} |",
            "",
        ]

    if delta:
        d = delta.get("overall", {})
        lines += [
            "## 四、与上一轮 baseline 对比",
            "",
            "| 指标 | Δ 变化 |",
            "|---|---|",
            f"| precision | {d.get('precision_delta'):+} |",
            f"| recall | {d.get('recall_delta'):+} |",
            f"| F1 | {d.get('f1_delta'):+} |",
            f"| 误报率 | {d.get('false_positive_rate_delta'):+} |",
            f"| 漏检率 | {d.get('false_negative_rate_delta'):+} |",
            "",
        ]
    else:
        lines += ["## 四、与上一轮 baseline 对比", "", "（首次运行，本轮指标已存为 baseline）", ""]

    lines += [
        "## 五、反例回流（FP/FN → 反例库 → prompt 注入）",
        "",
        f"- 本轮新回流误报 {reflow['fp']} 条、漏检 {reflow['fn']} 条；"
        f"去重跳过误报 {reflow['skipped_fp']} 条、漏检 {reflow['skipped_fn']} 条",
        "- 回流记录将以 `backtest_fp` / `backtest_fn` 证据类型注入 RiskReview prompt",
        "",
    ]

    if trace:
        lines += [
            "## 六、审查运行概览（trace）",
            "",
            "| 审查场次 | 日志事件总数 | 平均耗时(s) |",
            "|---|---|---|",
            f"| {trace['sessions']} | {trace['total_events']} | {trace['avg_elapsed']} |",
            "",
        ]

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    results_path = Path(args.results)
    if not results_path.exists():
        print(f"[backtest] 结果文件不存在: {results_path}")
        sys.exit(1)

    contracts = load_results(results_path)
    if not contracts:
        print("[backtest] 结果文件中没有合同数据")
        sys.exit(1)

    # 1. 指标计算
    contract_level = compute_contract_level_metrics(contracts)
    annotations_index = load_annotations(Path(args.annotations))
    clause_level = None
    if annotations_index:
        clause_level = compute_clause_level_metrics(contracts, annotations_index)

    # 2. FP/FN 回流反例库
    if args.no_reflow:
        reflow = {"fp": 0, "fn": 0, "skipped_fp": 0, "skipped_fn": 0}
    else:
        reflow = reflow_counter_examples(contracts, clause_level, annotations_index)

    # 3. baseline 对比（上一轮 → 本轮），并把本轮存为下一轮 baseline
    previous = load_previous_baseline()
    delta = None
    if previous and previous.get("contract_level"):
        delta = compare_with_baseline(contract_level, previous["contract_level"])
    save_baseline(contract_level, clause_level)

    # 4. trace 概览
    trace = None if args.no_trace else trace_overview()

    # 5. 生成报告
    report = build_report(contract_level, clause_level, delta, reflow, trace, len(contracts))
    if args.output:
        report_path = Path(args.output)
    else:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    ov = contract_level["overall"]
    print(f"[backtest] 合同级 precision={ov['precision']} recall={ov['recall']} f1={ov['f1']}")
    print(f"[backtest] 反例回流 fp={reflow['fp']} fn={reflow['fn']} (去重跳过 {reflow['skipped_fp']}/{reflow['skipped_fn']})")
    if delta:
        d = delta["overall"]
        print(f"[backtest] vs baseline: F1 {d['f1_delta']:+}, 误报率 {d['false_positive_rate_delta']:+}")
    print(f"[backtest] 报告已生成: {report_path}")


if __name__ == "__main__":
    main()
