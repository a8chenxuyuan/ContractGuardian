"""
文件：app/evaluation/metrics.py
作用：合同审查系统的可量化评估指标计算。

支持两类评估：
1. 合同级别（contract-level）：基于合同的 legal/illegal 标签，判断系统是否检出至少一条风险；
2. 条款级别（clause-level）：基于条款级标注，匹配预测风险与真实风险，计算 precision/recall/F1。

所有指标都支持按风险类型、合同类型拆分，并支持与 baseline 对比。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


def jaccard_similarity(a: str, b: str) -> float:
    """计算两个字符串的字符级 Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def normalize_risk_type(risk_type: str) -> str:
    """对 risk_type 做轻量归一化，便于同义类型匹配。"""
    if not risk_type:
        return ""
    text = risk_type.lower()
    # 去掉常见后缀/前缀
    for suffix in ("风险", "问题", "条款", "约定"):
        text = text.removesuffix(suffix)
    for prefix in ("涉嫌", "存在", "明显的"):
        text = text.removeprefix(prefix)
    # 同义词映射
    synonyms = {
        "违约金过高": "违约金",
        "违约金畸高": "违约金",
        "违约金显著过高": "违约金",
        "违约金约定过高": "违约金",
        "逾期罚息": "违约金",
        "罚息": "违约金",
        "滞纳金": "违约金",
        "利率超过": "利率",
        "借款利率": "利率",
        "年化利率": "利率",
        "排除对方主要权利": "排除权利",
        "排除对方主要法定权利": "排除权利",
        "排除法定检验权": "排除权利",
        "免除法定质量保证义务": "免除质保",
        "免除己方质量担保义务": "免除质保",
        "不提供质保": "免除质保",
        "权利义务失衡": "失衡",
        "显失公平": "失衡",
    }
    for key, value in synonyms.items():
        if key in text:
            return value
    return text.strip()


def match_risk_type(pred_type: str, true_type: str, threshold: float = 0.5) -> bool:
    """判断两个 risk_type 是否匹配。"""
    pred_norm = normalize_risk_type(pred_type)
    true_norm = normalize_risk_type(true_type)
    if not pred_norm or not true_norm:
        return False
    if pred_norm == true_norm:
        return True
    if pred_norm in true_norm or true_norm in pred_norm:
        return True
    return jaccard_similarity(pred_norm, true_norm) >= threshold


def compute_contract_level_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    计算合同级别指标。

    输入：run_batch_full_test.py 生成的 contracts_summary 列表，每项包含 legal/findings_count。
    输出：precision / recall / F1 / false_positive_rate / false_negative_rate 等。
    """
    tp = fp = tn = fn = 0
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0})

    for r in results:
        legal = r.get("legal", True)
        has_finding = r.get("findings_count", 0) > 0
        contract_type = r.get("contract_type", "通用")

        if legal and has_finding:
            fp += 1
            per_type[contract_type]["fp"] += 1
        elif legal and not has_finding:
            tn += 1
            per_type[contract_type]["tn"] += 1
        elif not legal and has_finding:
            tp += 1
            per_type[contract_type]["tp"] += 1
        else:
            fn += 1
            per_type[contract_type]["fn"] += 1

    def _calc(metrics: dict[str, int]) -> dict[str, float]:
        p_tp, p_fp, p_fn = metrics["tp"], metrics["fp"], metrics["fn"]
        precision = p_tp / (p_tp + p_fp) if (p_tp + p_fp) > 0 else 0.0
        recall = p_tp / (p_tp + p_fn) if (p_tp + p_fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": p_tp,
            "fp": p_fp,
            "tn": metrics["tn"],
            "fn": p_fn,
        }

    overall = _calc({"tp": tp, "fp": fp, "tn": tn, "fn": fn})
    overall["false_positive_rate"] = round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0
    overall["false_negative_rate"] = round(fn / (fn + tp), 4) if (fn + tp) > 0 else 0.0

    return {
        "overall": overall,
        "per_contract_type": {k: _calc(v) for k, v in per_type.items()},
    }


def compute_clause_level_metrics(
    results: list[dict[str, Any]],
    annotations_index: dict[str, list[dict[str, Any]]],
    text_threshold: float = 0.5,
    type_threshold: float = 0.5,
) -> dict[str, Any]:
    """
    计算条款级别指标。

    输入：
    - results: contracts_summary 列表，每项包含 findings 列表；
    - annotations_index: {filename: [annotation, ...]}，每个 annotation 包含 clause_text / risk_type / level。

    匹配逻辑：
    - 用 Jaccard 相似度匹配 clause_text；
    - 用 normalize_risk_type 匹配 risk_type；
    - 一条 finding 最多匹配一条 annotation，优先匹配 text 相似度最高的。
    """
    tp = fp = fn = 0
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    matches: list[dict[str, Any]] = []
    unmatched_findings: list[dict[str, Any]] = []
    unmatched_annotations: list[dict[str, Any]] = []

    for r in results:
        filename = r.get("filename", "")
        findings = r.get("findings", [])
        annotations = annotations_index.get(filename, [])

        used_annotations: set[int] = set()
        for finding in findings:
            f_text = finding.get("clause_text", "") or finding.get("matched_text", "")
            f_type = finding.get("risk_type", "")

            best_idx = -1
            best_score = 0.0
            for idx, ann in enumerate(annotations):
                if idx in used_annotations:
                    continue
                a_text = ann.get("clause_text", "")
                a_type = ann.get("risk_type", "")

                text_sim = jaccard_similarity(f_text, a_text)
                type_match = match_risk_type(f_type, a_type, threshold=type_threshold)
                if text_sim < text_threshold or not type_match:
                    continue

                score = text_sim
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx >= 0:
                used_annotations.add(best_idx)
                tp += 1
                per_type[normalize_risk_type(f_type)]["tp"] += 1
                matches.append({
                    "filename": filename,
                    "finding": finding,
                    "annotation": annotations[best_idx],
                    "text_similarity": best_score,
                })
            else:
                fp += 1
                per_type[normalize_risk_type(f_type)]["fp"] += 1
                unmatched_findings.append({"filename": filename, "finding": finding})

        for idx, ann in enumerate(annotations):
            if idx not in used_annotations:
                fn += 1
                per_type[normalize_risk_type(ann.get("risk_type", ""))]["fn"] += 1
                unmatched_annotations.append({"filename": filename, "annotation": ann})

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    def _calc(metrics: dict[str, int]) -> dict[str, float]:
        p_tp, p_fp, p_fn = metrics["tp"], metrics["fp"], metrics["fn"]
        p_precision = p_tp / (p_tp + p_fp) if (p_tp + p_fp) > 0 else 0.0
        p_recall = p_tp / (p_tp + p_fn) if (p_tp + p_fn) > 0 else 0.0
        p_f1 = 2 * p_precision * p_recall / (p_precision + p_recall) if (p_precision + p_recall) > 0 else 0.0
        return {
            "precision": round(p_precision, 4),
            "recall": round(p_recall, 4),
            "f1": round(p_f1, 4),
            "tp": p_tp,
            "fp": p_fp,
            "fn": p_fn,
        }

    return {
        "overall": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        },
        "per_risk_type": {k: _calc(v) for k, v in per_type.items()},
        "matches": matches,
        "unmatched_findings": unmatched_findings,
        "unmatched_annotations": unmatched_annotations,
    }


def compare_with_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """
    对比当前指标与 baseline，返回差异。

    输入为 compute_contract_level_metrics 的输出。
    """
    def _diff(cur: float, base: float) -> float:
        return round(cur - base, 4)

    cur_overall = current.get("overall", {})
    base_overall = baseline.get("overall", {})

    return {
        "overall": {
            "precision_delta": _diff(cur_overall.get("precision", 0.0), base_overall.get("precision", 0.0)),
            "recall_delta": _diff(cur_overall.get("recall", 0.0), base_overall.get("recall", 0.0)),
            "f1_delta": _diff(cur_overall.get("f1", 0.0), base_overall.get("f1", 0.0)),
            "false_positive_rate_delta": _diff(
                cur_overall.get("false_positive_rate", 0.0),
                base_overall.get("false_positive_rate", 0.0),
            ),
            "false_negative_rate_delta": _diff(
                cur_overall.get("false_negative_rate", 0.0),
                base_overall.get("false_negative_rate", 0.0),
            ),
        },
        "current": cur_overall,
        "baseline": base_overall,
    }


def load_annotations(annotations_path: Path | str) -> dict[str, list[dict[str, Any]]]:
    """加载条款级标注文件，按 filename 分组。"""
    path = Path(annotations_path)
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = f.read().strip()
        if not data:
            return {}
        annotations = __import__("json").loads(data)

    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in annotations:
        filename = item.get("filename", "")
        if filename:
            index[filename].append(item)
    return dict(index)
