"""盲测评估跑批工具（阶段一 · 可信度建设）。

对一批合同文件跑完整审查管线（解析 → 多 Agent 审查），
与人工标注对比，输出合同级混淆矩阵与 P/R/F1 指标。

用法：
    # 1. 准备盲测集：把待测合同放入一个文件夹（如 测试集/盲测集/）
    # 2. 提供标注（二选一）：
    #    a) labels.json：{"文件名.docx": {"legal": false, "risk_types": ["..."]}, ...}
    #    b) 文件名内含「合法/违法」字样，自动解析
    # 3. 运行（在 backend 目录下）：
    python scripts/run_blind_eval.py --dir "D:/个人项目/合同卫士/测试集/盲测集"
    python scripts/run_blind_eval.py --dir ... --labels labels.json --out my_eval.json
    python scripts/run_blind_eval.py --dir ... --limit 2   # 只跑前 2 份（快速验证）

输出：
    - evaluation_output/blind_eval_<timestamp>.json  明细（含混淆矩阵、逐份耗时）
    - evaluation_output/blind_eval_<timestamp>.md    可读报告
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.evaluation.metrics import (  # noqa: E402
    compute_clause_level_metrics,
    compute_contract_level_metrics,
)

settings = get_settings()


def _sync_session():
    engine = create_engine(settings.SYNC_DATABASE_URL)
    return engine, sessionmaker(bind=engine)()


def _get_eval_user_id(db) -> int:
    """获取/创建评估专用用户。"""
    from app.models.user import User
    from app.routers.auth import get_password_hash

    email = "eval@contractguard.local"
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        return user.id
    user = User(
        email=email,
        nickname="盲测评估",
        hashed_password=get_password_hash(uuid.uuid4().hex),
        is_active=True,
        is_member=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _guess_label(filename: str, labels: dict) -> tuple[bool | None, str | None]:
    """返回 (legal, contract_type)。legal=None 表示无法判断。"""
    info = labels.get(filename) or {}
    legal = info.get("legal")
    contract_type = info.get("contract_type")
    if legal is None:
        stem = Path(filename).stem
        if "违法" in stem:
            legal = False
        elif "合法" in stem:
            legal = True
    if not contract_type:
        contract_type = Path(filename).stem.split("_")[0]
    return legal, contract_type


def run_one(file_path: Path, contract_type: str, eval_user_id: int) -> dict:
    """对单个合同文件执行 解析+审查，返回结果摘要。"""
    from app.models.contract import Contract, ContractFile
    from app.models.review import ReviewSession
    from app.tasks.celery_tasks import parse_contract_task, review_contract_task

    engine, db = _sync_session()
    contract = None
    t0 = time.perf_counter()
    try:
        # 1. 复制文件到上传目录（与正常上传等价）
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = file_path.suffix.lower()
        storage_path = str(upload_dir / f"{uuid.uuid4().hex}{ext}")
        shutil.copyfile(file_path, storage_path)
        file_size = Path(storage_path).stat().st_size

        file_type = "pdf" if ext == ".pdf" else ("docx" if ext in (".doc", ".docx") else "unknown")

        # 2. 建库记录
        contract = Contract(
            owner_id=eval_user_id,
            filename=file_path.name,
            file_type=file_type,
            status="uploaded",
        )
        db.add(contract)
        db.commit()
        db.refresh(contract)
        db.add(
            ContractFile(
                contract_id=contract.id, version=1,
                storage_path=storage_path, file_size=file_size,
            )
        )
        db.commit()

        # 3. 同步执行解析任务
        parse_contract_task.run(contract.id, storage_path, file_type)
        db.refresh(contract)
        if not (contract.parsed_data or {}).get("chunks"):
            return {"status": "failed", "reason": "解析无结果"}

        # 4. 同步执行审查任务（完整 8 阶段管线）
        session = ReviewSession(contract_id=contract.id, status="pending")
        db.add(session)
        db.commit()
        db.refresh(session)
        try:
            review_contract_task.run(contract.id, session.id)
        except Exception as exc:  # 直接调用时 self.retry 会抛异常，不再自动重试
            db.refresh(session)
            if session.status != "completed":
                return {"status": "failed", "reason": f"审查异常: {exc}"}

        db.refresh(session)
        findings = session.findings or []
        stats = session.stats or {}

        return {
            "status": "completed",
            "review_session_id": session.id,
            "findings": findings,
            "findings_count": len(findings),
            "high_count": stats.get("high", 0),
            "medium_count": stats.get("medium", 0),
            "low_count": stats.get("low", 0),
            "law_verified_count": stats.get("law_verified_count"),
            "law_invalid_count": stats.get("law_invalid_count"),
            "avg_confidence": stats.get("avg_confidence"),
            "duration_sec": round(time.perf_counter() - t0, 1),
        }
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="盲测评估跑批工具")
    parser.add_argument("--dir", required=True, help="盲测合同文件夹路径")
    parser.add_argument("--labels", default=None, help="labels.json 标注文件路径（可选）")
    parser.add_argument("--limit", type=int, default=0, help="最多跑多少份（0=全部）")
    parser.add_argument("--out", default=None, help="输出 JSON 路径（默认 evaluation_output/ 下按时间戳命名）")
    args = parser.parse_args()

    src_dir = Path(args.dir)
    files = sorted(
        p for p in src_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".pdf", ".docx", ".doc")
    )
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        print(f"[error] {src_dir} 下没有可评估的 PDF/Word 文件")
        return 1

    labels = {}
    if args.labels and Path(args.labels).exists():
        labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))

    engine, db = _sync_session()
    try:
        eval_user_id = _get_eval_user_id(db)
    finally:
        db.close()
        engine.dispose()

    print(f"[eval] 共 {len(files)} 份合同，开始逐份评估（每份完整跑 8 阶段管线）\n")
    contracts_summary = []
    for i, fp in enumerate(files, 1):
        legal, contract_type = _guess_label(fp.name, labels)
        print(f"[{i}/{len(files)}] {fp.name}（标注: {'合法' if legal else '违法' if legal is False else '未知'}）")
        try:
            result = run_one(fp, contract_type, eval_user_id)
        except Exception as exc:
            result = {"status": "failed", "reason": str(exc)}
        result["filename"] = fp.name
        result["legal"] = bool(legal) if legal is not None else True
        result["label_known"] = legal is not None
        result["contract_type"] = contract_type
        contracts_summary.append(result)
        print(
            f"    -> {result.get('status')}，发现 {result.get('findings_count', '-')} 条风险，"
            f"耗时 {result.get('duration_sec', '-')}s"
        )

    # 指标计算
    metrics = compute_contract_level_metrics(contracts_summary)
    report = {
        "generated_at": datetime.now().isoformat(),
        "source_dir": str(src_dir),
        "total": len(contracts_summary),
        "metrics": metrics,
        "contracts": contracts_summary,
    }

    # 条款级指标（若标注带 risk_types + clause_text）
    annotations_index = {}
    for fname, info in labels.items():
        anns = info.get("annotations") or []
        for a in anns:
            annotations_index.setdefault(fname, []).append(a)
    if annotations_index:
        report["clause_level"] = compute_clause_level_metrics(contracts_summary, annotations_index)

    # 输出
    out_dir = backend_root / "evaluation_output"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = Path(args.out) if args.out else out_dir / f"blind_eval_{ts}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = json_path.with_suffix(".md")
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    # 控制台摘要
    ov = metrics["overall"]
    print("\n========== 盲测评估结果 ==========")
    print(f"混淆矩阵：TP={ov['tp']}  FP={ov['fp']}  TN={ov['tn']}  FN={ov['fn']}")
    print(f"Precision={ov['precision']}  Recall={ov['recall']}  F1={ov['f1']}")
    print(f"误报率 FPR={ov.get('false_positive_rate', '-')}  漏报率 FNR={ov.get('false_negative_rate', '-')}")
    durations = [c["duration_sec"] for c in contracts_summary if c.get("duration_sec")]
    if durations:
        print(f"平均耗时 {round(sum(durations)/len(durations), 1)}s / 份")
    print(f"\n明细: {json_path}\n报告: {md_path}")
    return 0


def _render_markdown(report: dict) -> str:
    ov = report["metrics"]["overall"]
    lines = [
        "# 盲测评估报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 样本数：{report['total']}",
        "",
        "## 合同级混淆矩阵",
        "",
        "| | 系统检出风险 | 系统未检出 |",
        "|---|---|---|",
        f"| **实际违法** | TP = {ov['tp']} | FN = {ov['fn']} |",
        f"| **实际合法** | FP = {ov['fp']} | TN = {ov['tn']} |",
        "",
        "## 指标",
        "",
        f"- Precision：{ov['precision']}",
        f"- Recall：{ov['recall']}",
        f"- F1：{ov['f1']}",
        f"- 误报率（FPR）：{ov.get('false_positive_rate', '-')}",
        f"- 漏报率（FNR）：{ov.get('false_negative_rate', '-')}",
        "",
        "## 逐份明细",
        "",
        "| 文件 | 标注 | 检出 | 高/中/低 | 法条验证 | 耗时s | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in report["contracts"]:
        label = "合法" if c.get("legal") else "违法"
        law_v = (
            f"{c.get('law_verified_count', 0)}通过/{c.get('law_invalid_count', 0)}剔除"
            if c.get("law_verified_count") is not None
            else "-"
        )
        lines.append(
            f"| {c['filename']} | {label} | {c.get('findings_count', '-')} "
            f"| {c.get('high_count', '-')}/{c.get('medium_count', '-')}/{c.get('low_count', '-')} "
            f"| {law_v} | {c.get('duration_sec', '-')} | {c.get('status')} |"
        )
    if "clause_level" in report:
        cl = report["clause_level"]["overall"]
        lines += [
            "",
            "## 条款级指标",
            "",
            f"- Precision：{cl['precision']}  Recall：{cl['recall']}  F1：{cl['f1']}",
        ]
    lines += ["", "> 免责声明：指标基于该批样本与标注，AI 输出不构成法律意见。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
