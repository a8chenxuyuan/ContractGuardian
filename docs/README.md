# 合同卫士（ContractGuard）

基于 FastAPI + Vue3 的 AI 合同审查系统，支持劳动合同、租赁合同、买卖合同、借款合同、技术服务合同、股权转让等多类型合同的智能化风险审查。

> 文档更新时间：2026-07-26

---

## 项目结构

```
contract-guard/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── main.py              # 应用入口
│   │   ├── core/                # 核心框架（配置、数据库、SSE、存储）
│   │   ├── contracts/           # 合同解析与红线规则
│   │   ├── rag/                 # 向量检索（Qdrant、法规缓存）
│   │   ├── llm/                 # LLM 客户端与向量编码
│   │   ├── review/              # 审查管线、Agent、工具、报告
│   │   ├── agentkit/            # Agent 框架（基类、总线、记忆图）
│   │   ├── evaluation/          # 评估指标
│   │   ├── models/              # SQLAlchemy 数据模型
│   │   ├── routers/             # API 路由
│   │   ├── schemas/             # Pydantic 数据校验
│   │   └── tasks/               # Celery 异步任务
│   ├── alembic/                 # 数据库迁移脚本
│   ├── scripts/                 # 数据初始化脚本
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml
├── frontend/         # Vue3 前端
│   ├── src/
│   │   ├── views/               # 页面
│   │   ├── components/          # 组件
│   │   ├── api/                 # API 请求
│   │   ├── stores/              # Pinia 状态
│   │   ├── router/              # Vue Router
│   │   └── types/               # TypeScript 类型
│   ├── package.json
│   └── vite.config.ts
├── docs/             # 项目文档
├── pg/               # PostgreSQL 本地运行目录（运行时生成）
├── qdrant/           # Qdrant 本地运行目录（运行时生成）
└── storage/          # Qdrant 向量数据（运行时生成）
```

---

## 文件与目录详解

### 后端根目录

| 文件 | 作用 |
|------|------|
| `backend/requirements.txt` | Python 依赖清单。 |
| `backend/Dockerfile` | 后端服务的 Docker 构建文件。 |
| `backend/docker-compose.yml` | 一键启动 PostgreSQL、Redis、Qdrant、Neo4j 和后端服务。 |
| `backend/alembic.ini` | Alembic 迁移配置。 |

### backend/app/ 核心目录

| 文件 | 作用 |
|------|------|
| `app/__init__.py` | 包初始化文件。 |
| `app/main.py` | FastAPI 应用入口，注册路由、中间件、静态文件和生命周期事件。 |
| `app/core/config.py` | 全局配置管理，使用 Pydantic Settings 读取环境变量。 |
| `app/core/database.py` | 异步数据库引擎和会话管理，提供 `get_db()` 依赖注入。 |
| `app/llm/client.py` | LLM 客户端，封装 OpenAI 兼容接口（当前使用阿里云百炼 qwen 系列）。 |
| `app/llm/embeddings.py` | BGE-M3 向量编码封装，支持异步编码与国内镜像下载。 |
| `app/rag/vector_store.py` | Qdrant 向量库封装，提供法条/条款的写入与语义搜索。 |

### backend/app/models/ 数据模型

| 文件 | 作用 |
|------|------|
| `models/__init__.py` | 导出所有模型类。 |
| `models/user.py` | `User` 用户表。 |
| `models/contract.py` | `Contract` 合同表和 `ContractFile` 合同文件表。 |
| `models/review.py` | `ReviewSession` 审查会话表、`Finding` 风险发现表、`HumanReview` 人工复核表。 |
| `models/chat.py` | `ChatRecord` 对话记录表。 |
| `models/payment.py` | `Payment` 支付订单表和 `Membership` 会员信息表。 |
| `models/knowledge.py` | `KnowledgeArticle` 法律法规表和 `KnowledgeCase` 典型案例表。 |

### backend/app/routers/ API 路由

| 文件 | 作用 |
|------|------|
| `routers/auth.py` | 认证路由：注册、登录、JWT。 |
| `routers/contracts.py` | 合同路由：列表、上传、详情、删除。 |
| `routers/review.py` | 审查路由：启动审查、SSE 进度流、获取结果、风险列表、导出报告。 |
| `routers/chat.py` | 对话路由：同步对话、流式对话、历史记录。 |
| `routers/admin.py` | 管理后台路由。 |

### backend/app/ 业务服务（core / contracts / review / rag）

| 文件 | 作用 |
|------|------|
| `core/storage.py` | `StorageService` 本地文件存储。 |
| `contracts/parser.py` | `ContractParser` 文档解析，PDF / Word 文本提取和 Chunk 切分。 |
| `review/report.py` | `ReportService` 报告生成，支持 PDF（WeasyPrint）和 Word（python-docx）。 |
| `core/sse.py` | `SSEManager` SSE 进度推送，基于 Redis Pub/Sub 实现多 Worker 广播。 |
| `rag/knowledge_cache.py` | 外部法条检索与缓存（Tavily 兜底）。 |
| `review/learning.py` | Critic 反例收集与持久化。 |

### backend/app/ Agent 模块（review / agentkit / contracts/rules）

| 文件 | 作用 |
|------|------|
| `review/pipeline.py` | `ReviewCoordinator` 调度中心，控制八阶段审查管线。 |
| `agentkit/session_graph.py` | `SessionGraph` 共享记忆图，管理节点/边、去重、跨条款组合风险发现。 |
| `agentkit/bus.py` | `AgentBus` 实时消息总线，基于 Redis Pub/Sub。 |
| `contracts/rules/red_flag_detector.py` | 原则驱动的红线检测器（`PrincipleBasedDetector`），含快速检查与语义检查。 |
| `contracts/rules/config/legal_principles.json` | 通用法律原则配置。 |
| `agentkit/config/cross_clause_rules.json` | 跨条款组合风险规则库。 |
| `review/config/review_few_shot_cases.json` | RiskReviewAgent few-shot 案例库。 |

### backend/app/review/agents/ 内置 Agent

| 文件 | Agent | 职责 |
|------|-------|------|
| `agentkit/base.py` | `BaseAgent` | 抽象基类，ReAct 循环、工具调用、进度发布。 |
| `review/agents/term_extraction.py` | `TermExtractionAgent` | 提取甲乙双方、合同期限、岗位等。 |
| `review/agents/legal_research.py` | `LegalResearchAgent` | 动态推断适用法律并检索法条（本地+联网缓存）。 |
| `review/agents/risk_review.py` | `RiskReviewAgent` | 识别不公平/高风险条款，集成 RedFlagDetector + CriticAgent。 |
| `review/agents/missing_clause.py` | `MissingClauseAgent` | 检查必要条款缺失。 |
| `review/agents/balance.py` | `BalanceAgent` | 分析双方权利义务对等性。 |
| `review/agents/cross_reference.py` | `CrossReferenceAgent` | 检查条款间引用一致性（已启用 function calling）。 |
| `review/agents/legal_basis.py` | `LegalBasisAgent` | 为风险补充法律依据。 |
| `review/agents/suggestion.py` | `SuggestionAgent` | 生成具体修改建议。 |
| `review/agents/industry_compliance.py` | `IndustryComplianceAgent` | 行业特殊合规检查。 |
| `review/agents/legal_verify.py` | `LegalVerifyAgent` | 验证法条引用准确性（已启用 function calling）。 |
| `review/agents/debate.py` | `DebateAgent` | 对高风险项正反辩论（已启用 function calling）。 |
| `review/agents/blind_spot.py` | `BlindSpotAgent` | 盲区扫描。 |
| `review/agents/human_review.py` | `HumanReviewAgent` | 人工复核兜底。 |
| `review/agents/chat.py` | `ChatAgent` | 基于 SessionGraph 回答用户追问。 |

### backend/app/review/tools/ 工具函数

| 文件 | 工具 | 作用 |
|------|------|------|
| `review/tools/web_search.py` | `web_search` | 联网搜索法规和案例。 |
| `review/tools/search_document.py` | `search_document` | 在合同内部语义/关键词搜索。 |
| `review/tools/search_knowledge.py` | `search_knowledge` | 在本地法律知识库检索（Qdrant 优先，降级 SQLite/关键词）。 |
| `review/tools/read_section.py` | `read_section` | 读取指定章节或条款全文。 |
| `review/tools/output_finding.py` | `output_finding` | 把风险发现写入 SessionGraph。 |
| `review/tools/check_cross_reference.py` | `check_cross_reference` | 检查条款引用是否准确。 |
| `review/tools/extract_obligations.py` | `extract_obligations` | 提取甲乙双方权利义务。 |
| `review/tools/validate_calculation.py` | `validate_calculation` | 验证金额、日期、比例计算。 |
| `review/tools/compare_with_template.py` | `compare_with_template` | 与标准范本对比。 |
| `review/tools/query_knowledge_graph.py` | `query_knowledge_graph` | 在 Neo4j 图库中做关系查询。 |

---

## 快速启动

### 1. 启动基础设施

```bash
cd backend
docker-compose up -d postgres redis qdrant neo4j
```

> 当前 `.env` 已指向本地 PostgreSQL / Redis / Qdrant。Windows 本地开发也可直接运行 `pg/`、`qdrant/` 目录下的二进制。

### 2. 数据库迁移与法条入库

```bash
cd backend
python -m alembic upgrade head
python scripts/seed_knowledge.py
```

### 3. 安装并启动后端

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt

# 启动 FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 另起终端启动 Celery Worker
celery -A app.tasks.celery_tasks worker --loglevel=info -P eventlet
```

### 4. 安装并启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 http://localhost:5173

---

## 已实现能力

后端：
- 用户注册/登录/JWT 认证
- 合同上传、解析（PDF/Word）、状态管理
- Celery 异步审查任务，调用真实 `ReviewCoordinator`
- 八阶段审查管线：Route → Preload → LegalResearch → Execute → Merge+Link → LegalVerify → Debate → Triage
- 14 个内置 Agent + 1 个抽象基类 `BaseAgent`（含 LegalResearchAgent、ChatAgent、CriticAgent）协同审查
- `RedFlagDetector` 原则驱动红线检测 + `CriticAgent` 二次校验
- 动态法律依据检索（本地 Qdrant + Tavily 联网缓存兜底）
- SSE 实时进度推送
- 风险发现列表、报告导出（PDF/Word）
- ChatAgent 同步/流式对话接口
- 管理后台接口

前端：
- 登录/注册
- 合同列表、上传、合同类型选择
- 审查报告页：PDF 预览、风险卡片、SSE 进度、划词追问
- 管理后台占位页

---

## Agent 模块说明

Agent 相关代码分布于 `backend/app/review/`、`backend/app/agentkit/` 与 `backend/app/contracts/rules/`，均已完整实现：
- `review/pipeline.py`：八阶段审查管线（`ReviewCoordinator`）
- `agentkit/session_graph.py`：共享记忆图，支持法律指纹去重、跨条款组合风险
- `agentkit/bus.py`：基于 Redis Pub/Sub 的实时消息总线
- `contracts/rules/red_flag_detector.py`：原则驱动的红线检测层
- `review/agents/`：14 个内置 Agent + 1 个抽象基类 `BaseAgent`（基类位于 `agentkit/base.py`）完整实现
- `review/tools/`：10 个工具函数完整实现
- 配置：法律原则（`contracts/rules/config/`）、跨条款规则（`agentkit/config/`）、few-shot 案例（`review/config/`）

核心审查流程：
1. `LegalResearchAgent` 动态推断适用法律并检索法条；
2. `RiskReviewAgent` 逐条审查，先经 `RedFlagDetector` 红线扫描，再经 `CriticAgent` 二次校验；
3. 其他 Agent 并行审查缺失条款、平衡性、交叉引用、行业合规等；
4. `Merge+Link` 阶段去重并发现跨条款组合风险；
5. `LegalBasisAgent` / `LegalVerifyAgent` 补充并验证法律依据；
6. `DebateAgent` 对高风险项辩论；
7. `HumanReviewAgent` 标记需人工复核项；
8. `Triage` 输出最终风险列表与人工复核项。

---

## 注意

- `.env` 中的数据库、Redis、Qdrant、LLM API Key 等配置需与本地环境一致。
- 首次运行会自动从 Hugging Face 镜像下载 BGE-M3 模型，已通过 `HF_ENDPOINT=https://hf-mirror.com` 加速。
- 生产环境必须使用 PostgreSQL + Redis，不得使用 SQLite。
- Tavily 联网搜索有调用次数限制，当前 `LegalResearchAgent` 已限制每个合同最多 3 次泛化 web search。
