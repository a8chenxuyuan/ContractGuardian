# Skill: contract-review 合同全链路审查

## 职责
对单份合同执行完整风险审查，产出结构化风险发现（findings）与审查统计。

## 流程（LangGraph 13-Agent 编排）
1. **解析** `app/contracts/parser.py`：docx（python-docx）/ pdf（pdfplumber 文本层）/ 图片（视觉 OCR，qwen3.8-omni-flash base64）；解析产出 `parsed_data.clauses` 与章节树。
2. **切块** `app/rag/chunker.py`：父子切块——父块为完整条款，子块为定位句，禁止回退整条款单向量旧实现。
3. **检索**：BGE-M3 双路（稠密+稀疏）→ Qdrant 服务端 RRF 融合 → 交叉编码器重排。
4. **CRAG** `app/rag/crag.py`：检索分数低于阈值时触发最多 1 轮 query 变体重检索；仍不足必须降级并在报告中标注"依据不足"，禁止编造结论。
5. **产出**：每条 finding 携带结构化溯源（法名、条号、定位、父块原文），写入 `findings` 表 + `review_sessions.findings`。

## 触发与执行
- 上传合同后由 Celery 异步执行（`app/tasks/celery_tasks.py`）；SSE 推送阶段事件。
- 失败按 timeout/provider 等六类归类，timeout/provider 退避重试（30×2ⁿ，≤3 次）。
- 中途取消：`POST /review/{sid}/cancel`，节点边界检查 `ReviewCancelledError`。

## 边界
- 单次审查消耗会员配额，额度不足返回 402。
- 全链路约 2 分钟；LLM_TIMEOUT=60s 兜底。
