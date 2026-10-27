# 合同卫士 Contract Guard

AI 驱动的合同审查系统：上传合同 → 多 Agent 风险审查（LangGraph 编排 13 个 Agent）→ 风险报告 / 双版本对比 / 修订版 Word 导出，配合法规知识库 RAG 问答、风险整改跟踪、履约日期管家与数据看板。

## 技术架构

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL |
| 审查编排 | LangGraph 状态机（13 Agent：解析/检测/检索/辩论/生成等） |
| 检索 | 父子切块 + BGE-M3 双路混合检索 + Qdrant 服务端 RRF 融合 + 交叉编码器重排 |
| 异步任务 | Celery（worker + beat，solo 池） |
| 前端 | Vue 3 + TypeScript + Element Plus + Vite + ECharts |
| LLM | 阿里百炼（qwen3.7-flash 文本 / qwen3.8-omni-flash 图片 OCR）+ Tavily 联网检索 |

## 目录结构

```
contract-guard/
├── backend/
│   ├── app/
│   │   ├── routers/      # API 接口层（contracts/review/auth/dashboard/calendar/notifications/admin...）
│   │   ├── core/         # 基础设施（config/database/storage/sse/mailer/quota）
│   │   ├── llm/          # LLM 客户端与 Embeddings（BGE-M3）
│   │   ├── rag/          # 检索底座（向量库/父子切块/重排/CRAG/法条联网缓存/上下文增强）
│   │   ├── agentkit/     # Agent 框架层（BaseAgent/AgentBus/SessionGraph），不含业务
│   │   ├── contracts/    # 合同解析域（parser/classifier/diff/日期提取/条款关联 + rules 红线检测）
│   │   ├── review/       # 审查业务层（Coordinator/13 Agent/ReAct 工具/prompts 收敛/报告/反例学习）
│   │   ├── tasks/        # Celery 任务（解析、审查、到期提醒）
│   │   ├── evaluation/   # 检索评测（召回回测）
│   │   ├── models/       # SQLAlchemy 模型（13 张表）
│   │   └── schemas/      # Pydantic 请求/响应模型
│   ├── scripts/          # 运维脚本（反馈分析、向量库重建等）
│   └── learning/         # 反例学习存储（误判模式回流）
├── frontend/             # Vue3 前端源码，构建产物 dist/ 由 FastAPI 托管
├── docs/                 # 设计与方案文档
├── pg/  qdrant/  redis/  # 本地化中间件（程序 + 数据目录）
├── storage/              # 上传合同与生成的报告文件
```

## 快速启动

环境要求：Python 3.11（backend/.venv 已配好）、Node.js（前端构建）、PostgreSQL/Qdrant/Redis 本地包已随仓库就位。

端口规划（与本机其他服务错峰）：**PG 5433 / Redis 6380 / Qdrant 16334(gRPC 16335) / 后端 8001**。

```powershell
# 1. PostgreSQL
contract-guard\pg\pgsql\bin\pg_ctl.exe -D contract-guard\pg\data -l contract-guard\pg\logfile start

# 2. Qdrant（必须在 qdrant 目录下运行，storage 路径相对 cwd）
cd contract-guard\qdrant
$env:QDRANT__SERVICE__HTTP_PORT="16334"; $env:QDRANT__SERVICE__GRPC_PORT="16335"
.\qdrant.exe

# 3. Redis
contract-guard\redis\redis-server.exe --port 6380

# 4. 后端 API（backend 目录下）
cd contract-guard\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 5. Celery worker + beat（backend 目录下）
.venv\Scripts\python.exe -m celery -A app.tasks.celery_tasks worker --loglevel=info -P solo
.venv\Scripts\python.exe -m celery -A app.tasks.celery_tasks beat --loglevel=info

# 6. 前端（修改源码后重新构建，dist 由后端托管）
cd contract-guard\frontend
npm.cmd install
npm.cmd run build
```

访问 http://localhost:8001 ，健康检查 `GET /health`（LLM Key / DB / Redis / Qdrant 连通性自检）。

`.env` 位于 backend/ 下（数据库连接、LLM 与 Tavily Key、端口等），**含真实密钥，勿提交勿泄露**。

## 已知限制

- PDF 导出在无 GTK 的 Windows 上自动降级为 xhtml2pdf（纯 Python，STSong-Light 内置中文字体）；Linux 装好 WeasyPrint 依赖后自动优先使用。
- `REVIEW_SOFT_TIME_LIMIT` 依赖 Celery soft time limit，仅 Linux 生效，Windows 上由 LLM_TIMEOUT 等上层超时兜底。
- 数据库结构管理已正式启用 Alembic：现有库已 `stamp` 到基线 `20261020_0001_baseline`（17 张业务表），全新空库执行 `alembic upgrade head` 即得完整结构；后续结构性变更用 `alembic revision --autogenerate -m "..."` 生成增量迁移。`AUTO_CREATE_TABLES` 仅作开发兜底（只建新表不加新列），生产环境建议关闭并依赖迁移。
