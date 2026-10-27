"""
脚本：scripts/rebuild_index.py
作用：M1 检索底座 v2 —— 全量重建 Qdrant 向量索引（幂等，可反复执行）。

做什么：
1. 从 PG 拉取全部法条 → 父子切块 + LLM 定位句 + 双路向量 → knowledge_articles_v2；
2. 从 UPLOAD_DIR 找到历史合同的原文文件重新解析 → 合同条款切块 → contract_clauses_v2
   （contracts 表里存的是解析结果 JSON 或原文件，取决于合同来源）；
3. 打印两侧 collection 的最终点数。

用法（backend 目录下）：
    .venv\\Scripts\\python.exe scripts/rebuild_index.py            # 全量重建（含 LLM 定位句）
    .venv\\Scripts\\python.exe scripts/rebuild_index.py --no-enhance  # 机械定位句，快速验证链路
    .venv\\Scripts\\python.exe scripts/rebuild_index.py --skip-contracts  # 只重建知识库
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 保证以模块方式导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.models.knowledge import KnowledgeArticle  # noqa: E402
from app.rag.vector_store import (  # noqa: E402
    CONTRACT_COLLECTION,
    KNOWLEDGE_COLLECTION,
    get_vector_store,
)


async def rebuild_knowledge(enhance: bool) -> int:
    """重建法条知识库索引。"""
    store = get_vector_store()
    async for session in get_db():
        result = await session.execute(select(KnowledgeArticle))
        articles = result.scalars().all()

        items = [
            {
                "id": a.id,
                "law_name": a.law_name,
                "article_number": a.article_number,
                "article_title": a.article_title or "",
                "article_text": a.article_text,
                "category": a.category,
            }
            for a in articles
        ]

        print(f"[knowledge] 从 PG 读取 {len(items)} 条法条，开始向量化...")
        count = await store.upsert_knowledge_async(items, enhance=enhance)
        print(f"[knowledge] knowledge_articles_v2 写入 {count} 个子块")
        return count
    return 0


async def _collect_contract_clauses() -> list[tuple[int, str, list[dict]]]:
    """从已有合同产物中收集 (contract_id, title, clauses)。

    解析结果可能存于 contracts.parse_result（JSON 字段），也可能需要重解析原文件。
    这里两种都尝试：优先 parse_result，缺失则用原文件调用 parser。
    """
    from app.contracts.parser import ContractParser

    out: list[tuple[int, str, list[dict]]] = []
    async for session in get_db():
        from app.models.contract import Contract

        result = await session.execute(select(Contract))
        contracts = result.scalars().all()
        for c in contracts:
            title = c.filename or f"合同#{c.id}"
            parsed = c.parsed_data if isinstance(c.parsed_data, dict) else None
            if parsed and parsed.get("clauses"):
                out.append((c.id, title, parsed["clauses"]))
                continue

            # 无解析结果时重解析原文件（取最新版本文件路径）
            file_path = None
            if c.files:
                file_path = sorted(c.files, key=lambda f: f.version)[-1].storage_path
            if file_path and Path(file_path).exists():
                try:
                    parsed = ContractParser().parse(file_path, c.file_type or "pdf")
                    if parsed.get("clauses"):
                        out.append((c.id, title, parsed["clauses"]))
                except Exception as exc:
                    print(f"[contract] 合同#{c.id} 解析失败，跳过: {exc}")
            else:
                print(f"[contract] 合同#{c.id}《{title}》无 parsed_data 且原文件缺失，跳过")
    return out


async def rebuild_contracts(enhance: bool) -> int:
    """重建合同条款索引。"""
    store = get_vector_store()
    contracts = await _collect_contract_clauses()
    print(f"[contract] 找到 {len(contracts)} 份待重建合同")

    total = 0
    for contract_id, title, clauses in contracts:
        try:
            n = await store.upsert_clauses_async(
                contract_id, clauses, doc_title=title, enhance=enhance
            )
            total += n
            print(f"[contract] 合同#{contract_id}《{title}》写入 {n} 个子块")
        except Exception as exc:
            print(f"[contract] 合同#{contract_id}《{title}》写入失败: {exc}")
    print(f"[contract] contract_clauses_v2 共写入 {total} 个子块")
    return total


async def main_async(
    skip_contracts: bool, skip_knowledge: bool, enhance: bool
) -> None:
    settings = get_settings()
    mode = "LLM 定位句增强" if enhance else "机械定位句（快速模式）"
    print(f"=== 合同卫士 索引重建 v2（{mode}）===")
    print(f"Qdrant: {settings.QDRANT_URL}")

    if not skip_knowledge:
        await rebuild_knowledge(enhance)
    if not skip_contracts:
        await rebuild_contracts(enhance)

    # 汇总点数
    store = get_vector_store()
    client = store._get_client()
    for name in (KNOWLEDGE_COLLECTION, CONTRACT_COLLECTION):
        try:
            info = client.get_collection(collection_name=name)
            print(f"[done] {name}: {info.points_count} points")
        except Exception as exc:
            print(f"[warn] {name} 查询失败: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重建 v2 向量索引")
    parser.add_argument("--no-enhance", action="store_true", help="禁用 LLM 定位句")
    parser.add_argument("--skip-contracts", action="store_true", help="只重建知识库")
    parser.add_argument("--skip-knowledge", action="store_true", help="只重建合同")
    args = parser.parse_args()

    asyncio.run(
        main_async(
            skip_contracts=args.skip_contracts,
            skip_knowledge=args.skip_knowledge,
            enhance=not args.no_enhance,
        )
    )
