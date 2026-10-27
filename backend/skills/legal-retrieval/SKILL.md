# Skill: legal-retrieval 法规检索与溯源

## 职责
为审查与问答提供法律依据检索，输出结构化引用。

## 数据与通道
- 本地库：`knowledge_articles`（当前 104 条，覆盖民法典/劳动法/公司法/社会保险法等），父子切块向量存 Qdrant。
- 联网兜底：Tavily 搜索法规原文（`legal_knowledge_cache.py` 带缓存）。
- 用户端查询接口：`GET /api/v1/knowledge/articles`（keyword 四字段 ilike / category / 分页）、`GET /api/v1/knowledge/categories`。

## 行为约定
- 引用必须携带：法名、条号、定位、父块原文；禁止无来源标注。
- 批量导入按「法名+条号」去重；导入后自动切块与双路向量入库；删除条目同步清理 Qdrant 向量。
- Tavily 仅在本地检索分数不足（CRAG 触发）时使用。
