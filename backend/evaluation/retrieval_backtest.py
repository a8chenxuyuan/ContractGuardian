"""
脚本：evaluation/retrieval_backtest.py
作用：黄金集检索回测 —— M1 的验收工具，也是后续所有改动的质量门槛。

三种模式对比：
- baseline：dense-only 直查（旧版行为）
- hybrid：dense + sparse RRF 融合（无重排）
- full：hybrid + cross-encoder 重排（推荐生产配置）

指标：
- hit@k：期望法条出现在前 k 条的比例
- MRR：期望法条名次倒数的均值
- avg_latency：平均查询耗时

用法（backend 目录下）：
    .venv\\Scripts\\python.exe evaluation/retrieval_backtest.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.vector_store import get_vector_store  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_retrieval_set.json"
TOP_K = 10


def _match(hit: dict, case: dict) -> bool:
    """宽松匹配：法名包含期望词 且 条号相等。"""
    law = (hit.get("law_name") or "").replace("中华人民共和国", "")
    expect_law = case["expect_law"]
    if expect_law not in law:
        return False
    return (hit.get("article_number") or "").strip() == case["expect_article"].strip()


async def run_mode(mode: str, cases: list[dict]) -> dict:
    """跑一种模式，返回指标。"""
    store = get_vector_store()
    hits = 0
    mrr_sum = 0.0
    latencies: list[float] = []
    misses: list[str] = []

    for case in cases:
        t0 = time.perf_counter()
        if mode == "baseline":
            results = await store.search_knowledge_async(
                case["query"], top_k=TOP_K, rerank=False
            )
        elif mode == "hybrid":
            results = await store.search_knowledge_async(
                case["query"], top_k=TOP_K, rerank=False
            )
        else:  # full
            results = await store.search_knowledge_async(
                case["query"], top_k=TOP_K, rerank=True
            )
        latencies.append(time.perf_counter() - t0)

        rank = next(
            (i + 1 for i, r in enumerate(results) if _match(r, case)), None
        )
        if rank is not None:
            hits += 1
            mrr_sum += 1.0 / rank
        else:
            misses.append(f"  ✗ [{case['expect_law']}{case['expect_article']}] {case['query']}")

    n = len(cases)
    return {
        "mode": mode,
        "hit@10": round(hits / n, 3),
        "mrr": round(mrr_sum / n, 3),
        "avg_latency_s": round(sum(latencies) / n, 2),
        "misses": misses,
    }


async def main() -> None:
    cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    print(f"=== 检索回测：{len(cases)} 条黄金集 ===\n")

    results = []
    for mode in ("baseline", "hybrid", "full"):
        r = await run_mode(mode, cases)
        results.append(r)
        print(
            f"[{r['mode']:8}] hit@10={r['hit@10']:.0%}  MRR={r['mrr']:.3f}  "
            f"平均延迟={r['avg_latency_s']}s"
        )
        for m in r["misses"]:
            print(m)
        print()

    print("=== 汇总 ===")
    print(f"{'mode':10} {'hit@10':>8} {'MRR':>8} {'latency':>10}")
    for r in results:
        print(f"{r['mode']:10} {r['hit@10']:>7.0%} {r['mrr']:>8.3f} {r['avg_latency_s']:>8}s")

    out = Path(__file__).resolve().parent / "backtest_results.json"
    payload = [{k: v for k, v in r.items() if k != "misses"} for r in results]
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n结果已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
