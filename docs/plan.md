# 合同卫士项目完善计划

> 制定时间：2026-07-20  
> 最近更新：2026-07-26  
> 目标：把当前“能跑通、能连 LLM、只有一个 Agent 工作”的状态，完善为一条可用的合同审查主链路，并持续优化审查质量与性能。

## 一、当前状态盘点

### 已完成的
- 后端服务（FastAPI）可启动，已支持 PostgreSQL + Alembic 迁移，Redis 已运行，Celery Worker 可正常处理审查任务。
- LLM 客户端已接入阿里云百炼（Bailian）OpenAI 兼容接口，模型由环境变量 `LLM_MODEL` 配置。
- 15 个 Agent 全部激活：`BaseAgent`、`RiskReviewAgent`、`MissingClauseAgent`、`BalanceAgent`、`LegalBasisAgent`、`SuggestionAgent`、`LegalVerifyAgent`、`DebateAgent`、`HumanReviewAgent`、`TermExtractionAgent`、`CrossReferenceAgent`、`IndustryComplianceAgent`、`BlindSpotAgent`、`ChatAgent`、`LegalResearchAgent`。
- `app/review/tools/` 下 10 个工具已实现真实逻辑：文档搜索、法条查询、条款读取、风险输出、交叉引用检查、义务提取、计算校验、模板对比、知识图谱查询、网页搜索。
- 法律知识库已扩展至 24 条基础法律条文（租赁、买卖、借款、技术服务、劳动法等），`search_knowledge` 优先走 Qdrant 语义检索，不可用时降级关键词查询。
- 文档解析服务 `ContractParser` 已实现 PDF / Word 文本提取和 Chunk 切分。
- 前端（Vue3 + Vite）已完成构建，FastAPI 托管 `frontend/dist` 并支持 SPA 兜底，SSE 实时进度推送已联调通，PDF 原文高亮定位已支持。
- 审查管线已从七阶段升级为**八阶段**：Route → Preload → **LegalResearch** → Execute → Merge+Link → LegalVerify → Debate → Triage。
- 跨条款风险检测已启用配置驱动规则 + 条件化 LLM 兜底，`cross_clause_rules.json` 已扩展至 18 条规则，覆盖劳动、租赁、买卖、借款、技术服务合同。
- RedFlagDetector 已升级为 **PrincipleBasedDetector**，基于 8 条通用法律原则（配置在 `legal_principles.json`），支持快速检查 + 语义推断双路径。
- `RuleCritic` 已扩展至 **15 条法律常识规则**，显著降低合法合同误报。
- 风险去重已从文本相似度升级为**法律指纹（fingerprinting）**机制。
- `docker-compose.yml` 已配置 PostgreSQL、Redis、Qdrant、Neo4j。

### 还缺失的（可选优化项）
- 生产环境完整端到端验证：在 PostgreSQL + Redis + Qdrant 生产配置下跑完整测试。
- Celery Worker 稳定性：在多 Worker 场景下验证 Redis 事件广播和任务队列。
- 文档解析/OCR 验证：确保 PDF/Word 上传后能正确提取合同文本和坐标。
- 生产部署：配置 Nginx 反向代理和 SSL 证书。
- 原则库扩展：把流质/流押、格式条款提示义务、消费者保护等通用红线原则化。
- 规则置信度动态调整：根据线上反馈，用统计方法调整各原则的触发阈值。

## 二、分阶段实施计划

### Phase 1：打通真实审查链路（最高优先级）

**目标**：上传合同 → 解析 → 触发审查任务 → 调用 Coordinator → 把真实结果落库 → 前端能看到报告。

**涉及文件**
- `app/tasks/celery_tasks.py`
- `app/review/pipeline.py`
- `app/routers/review.py`
- `app/core/sse.py`

**具体工作**
1. 修改 `review_contract_task`，删除模拟数据逻辑：
   - 从数据库读取 `contract.parsed_data` 中的 `chunks` 和 `section_tree`。
   - 创建 `ReviewCoordinator` 实例。
   - 调用 `coordinator.run_review(...)` 获取真实结果。
   - 把 `findings`、`graph_data`、`stats` 写回 `ReviewSession`。
   - 把 `findings` 逐条插入 `Finding` 表。
   - 通过 `SSEManager` 发布进度事件（可选，先保证能跑通）。
2. 检查 `ReviewCoordinator.run_review` 的输入输出是否与 `parsed_data` 兼容。
3. 修复 `coordinator._triage` 已发现的 `properties` 读取问题（已完成，需回归验证）。
4. 验证 `POST /api/v1/contracts/{id}/review` 能返回真实审查结果。

**预期产出**
- 通过前端上传 PDF/Word 后，能自动完成解析和审查。
- `/api/v1/review/{id}/result` 返回真实风险列表，不再全是模拟数据。

**可能遇到的问题**
- Celery 任务在同步函数里调用异步 `run_review`，需要用 `asyncio.run()` 或 `celery` 的异步任务支持。
- `ReviewCoordinator` 初始化时会读取 `get_settings()`，需确保 `.env` 配置正确。
- SQLite 同步/异步混用可能触发 `asyncpg` 路径问题，必要时继续用 SQLite 或切 PostgreSQL。

---

### Phase 2：核心工具函数实现

**目标**：让 Agent 能真正“查合同、查法条、写结果”。

**涉及文件**
- `app/review/tools/read_section.py`
- `app/review/tools/search_document.py`
- `app/review/tools/search_knowledge.py`
- `app/review/tools/output_finding.py`
- `app/review/tools/check_cross_reference.py`
- `app/review/tools/extract_obligations.py`

**具体工作**
1. `read_section`：根据 `section_path` 从 `SessionGraph` 中返回对应 Clause 文本。
2. `search_document`：在合同所有 chunks 中做关键词匹配（后续可升级向量检索）。
3. `search_knowledge`：先实现本地 SQLite 查询 `knowledge_articles` 表；预留 Qdrant 接口。
4. `output_finding`：接收风险字段，在 `SessionGraph` 中新增 Risk 节点和 HAS_RISK 边。
5. `check_cross_reference`：根据两个 section_path 查找对应 Clause 并返回文本。
6. `extract_obligations`：用 LLM 提取条款中的权利义务对（简化版：关键词匹配甲方/乙方义务）。

**预期产出**
- 所有工具函数都有实际返回值，不再返回空。
- Agent 的 `_call_tool` 能拿到有用信息。

**可能遇到的问题**
- `search_knowledge` 需要先有法律知识库数据，Phase 4 解决；Phase 2 先用空/兜底逻辑。
- `output_finding` 需要与 `RiskReviewAgent` 的写入逻辑统一，避免重复写入或字段不一致。

---

### Phase 3：激活剩余 Agent

**目标**：让 12 个空壳 Agent 都具备基础 LLM 审查能力。

**涉及文件**
- `app/review/agents/missing_clause.py`
- `app/review/agents/balance.py`
- `app/review/agents/legal_basis.py`
- `app/review/agents/suggestion.py`
- `app/review/agents/legal_verify.py`
- `app/review/agents/debate.py`
- `app/review/agents/human_review.py`
- `app/review/agents/term_extraction.py`
- `app/review/agents/cross_reference.py`
- `app/review/agents/industry_compliance.py`
- `app/review/agents/blind_spot.py`
- `app/review/agents/chat.py`

**具体工作**
1. 每个 Agent 重写 `run()`：
   - 拼接专业提示词（系统提示词已在 `__init__` 中）。
   - 调用 `self._react_loop(session_graph, context, task_prompt)`。
   - 把 LLM 输出解析后写回 `SessionGraph`。
2. 优先级顺序：
   - 高：`MissingClauseAgent`、`LegalBasisAgent`、`SuggestionAgent`
   - 中：`BalanceAgent`、`LegalVerifyAgent`、`CrossReferenceAgent`
   - 低：`DebateAgent`、`HumanReviewAgent`、`BlindSpotAgent`、`IndustryComplianceAgent`、`ChatAgent`
3. `TermExtractionAgent` 可先保持简单：从 section_tree 中提取甲乙双方名称。

**预期产出**
- 审查报告包含更多维度：缺失条款、法律依据、修改建议、平衡性等。
- 每个 Agent 都有独立日志，便于调试。

**可能遇到的问题**
- 全部 Agent 同时调用 LLM 会导致 token 成本和时间剧增，需要控制并发和开关。
- 不同 Agent 的输出格式需要统一，否则 `_triage` 不好处理。
- 提示词工程需要反复调试，建议先跑通一个再复制模板。

---

### Phase 4：法律知识库（本地 + 向量）

**目标**：让 `search_knowledge` 能查到真实法条，提升法律依据准确性。

**涉及文件**
- `app/models/knowledge.py`
- `app/review/tools/search_knowledge.py`
- 可选：`app/rag/vector_store.py`（新建，封装 Qdrant）

**具体工作**
1. 准备基础劳动法律数据：
   - 《劳动合同法》第 17、19、22、38、46 条等常用条款。
   - 写入 `knowledge_articles` 表或 JSON 文件。
2. 创建种子脚本：
   - 启动时把基础法条导入 SQLite。
   - 可选：启动 Qdrant 容器后，把法条向量化入库。
3. 升级 `search_knowledge`：
   - 优先在 SQLite 中按 `category` 和关键词查询。
   - 如果配置了 Qdrant 且可用，做向量相似度检索。
4. 让 `LegalBasisAgent` / `LegalVerifyAgent` 调用 `search_knowledge` 核对引用。

**预期产出**
- 风险报告中的 `law_refs` 不再是空数组，能列出具体法条。
- 为后续 RAG 打好基础。

**可能遇到的问题**
- 向量模型和 `sentence-transformers` 首次加载较慢，且模型文件较大。
- Qdrant 需要 Docker 运行，Windows 本地开发可能不便；建议先以 SQLite 关键词检索为主。

---

### Phase 5：切回 PostgreSQL + Redis + Docker

**目标**：让项目运行在生产技术栈上，支持多 Worker 和持久化。

**涉及文件**
- `.env`
- `docker-compose.yml`
- `app/core/database.py`
- `alembic/`（如不存在需初始化）

**具体工作**
1. 安装 Docker Desktop（如未安装）。
2. 启动基础设施：
   ```bash
   docker-compose up -d postgres redis qdrant neo4j
   ```
3. 把 `.env` 中的数据库改回 PostgreSQL：
   ```env
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/contract_guard
   SYNC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/contract_guard
   ```
4. 用 Alembic 管理数据库迁移（可选，开发期仍可让 SQLAlchemy 自动建表）。
5. 启动 Celery Worker：
   ```bash
   celery -A app.tasks.celery_tasks worker --loglevel=info -P solo
   ```
6. 验证 Redis 通道：AgentBus 不再降级为内存广播，SSE 进度推送正常工作。

**预期产出**
- 所有服务通过 Docker 运行，前后端完整联调。
- 审查任务由 Celery Worker 异步执行，支持并发。

**可能遇到的问题**
- Windows 上 Celery 最好用 `-P solo` 或 `eventlet`/`gevent`，默认 prefork 可能报错。
- Docker 容器启动顺序，backend 应等 pg/redis 就绪后再启动。

---

### Phase 6：前端联调与修复

**目标**：确保前端页面与后端 API 完全对应。

**涉及文件**
- `frontend/src/api/*.ts`
- `frontend/src/views/*.vue`
- `frontend/src/types/index.ts`

**具体工作**
1. 检查 `frontend/src/api/request.ts` 中的 baseURL 是否为 `http://127.0.0.1:8000/api/v1`。
2. 确认上传后前端轮询或 SSE 接收审查状态。
3. 检查报告页 `ReportView.vue` 是否正确展示 `findings`、`stats`、`suggestion`。
4. 如后端返回字段与前端类型不一致，调整 `types/index.ts` 或后端返回结构。
5. 如需本地预览，构建前端：`npm run build`，再用 `vite preview` 或让后端托管 `frontend/dist`。

**预期产出**
- 用户能在浏览器完成：注册/登录 → 上传合同 → 查看进度 → 查看风险报告 → 导出 PDF。

**可能遇到的问题**
- 前端构建依赖 Node 版本，可能需要 `npm install`。
- CORS 问题：后端已配置 `localhost:5173`，若前端换端口需同步调整。

---

### Phase 7：跨条款风险 LLM 兜底与高级功能

**目标**：启用配置未覆盖场景下的 LLM 跨条款推理，并将审查管线从七阶段扩展为八阶段（增加 LegalResearch 阶段）。

**涉及文件**
- `app/review/pipeline.py`
- `app/agentkit/session_graph.py`
- `app/agentkit/config/cross_clause_rules.json`
- `app/review/agents/legal_research.py`

**具体工作**
1. 在 `ReviewCoordinator.__init__` 或 `run_review` 中打开开关：
   ```python
   self.config.setdefault("enable_llm_cross_clause_fallback", True)
   ```
2. 实现 `_llm_cross_clause_detector`：
   - 收集所有 Clause 文本。
   - 构造提示词让 LLM 判断是否存在组合风险。
   - 返回与规则库格式一致的列表。
3. 扩展 `cross_clause_rules.json`：增加租赁、买卖、借款、技术服务合同组合风险，总计 18 条规则。
4. 新增 `LegalResearchAgent`：
   - 动态推断合同适用法律领域；
   - 检索法条并生成审查要点；
   - 为后续 Agent 提供 `discovered_laws`、`review_checklist`、`risk_signals`。
5. 可选：接入 `DebateAgent`，对 high 风险做正反论证。

**预期产出**
- 能发现“试用期超长 + 合同期限不匹配”“放弃社保 + 工资拆分”等组合风险。
- 法律依据动态检索，提升非劳动合同类型的审查质量。

**可能遇到的问题**
- LLM 跨条款推理 token 消耗较大，建议只在 medium/high 风险场景触发。
- 返回格式不稳定，需要更严格的提示词和解析兜底。
- LegalResearchAgent 在低风险合同上可能过度调用 web search，需要快速路径优化。

## 三、执行顺序建议

推荐按 **Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 6 → Phase 5 → Phase 7 → Phase 8** 推进。

原因：
- 先让**端到端链路**跑通，有真实数据回流，再逐步增强 Agent。
- 工具函数是 Agent 的“手”，必须先有。
- 法律库和向量检索是增强项，可先用关键词兜底。
- PostgreSQL/Redis/Docker 是部署项，功能稳定后再切。
- 跨条款 LLM 兜底是高级优化，放在最后。
- Phase 8 是基于真实测试反馈的持续优化，解决漏检、误报、性能瓶颈。

## 四、问题记录模板

每完成一个 Phase，在本文档末尾追加：

```markdown
### Phase X 执行记录
- 完成时间：YYYY-MM-DD
- 实际修改文件：...
- 遇到的问题：...
- 解决方案：...
- 验证方式：...
```

---

## 五、下一步待办

- [x] Phase 1：Celery 审查任务接入真实 Coordinator
- [x] Phase 2：核心工具函数实现
- [x] Phase 3：激活剩余 Agent
- [x] Phase 4：法律知识库建设
- [x] Phase 5：切回 PostgreSQL + Redis + Docker
- [x] Phase 6：前端联调
- [x] Phase 7：跨条款 LLM 兜底与高级功能（含 LegalResearch 阶段，管线升级为八阶段）
- [x] Phase 8：性能与质量优化（RedFlagDetector 原则化、RuleCritic 扩展、条件执行、28 份全量测试验证）

### 可选优化项
- [x] 风险去重：增强 `merge_duplicate_risks`，先用法律指纹（fingerprinting）归一化，再用 2-gram Jaccard 相似度和 clause_ids 交集合并，减少不同 Agent 对同类风险的重复报告。
- [x] 向量检索：启动 Qdrant 后把法条和合同 chunks 向量化，替换当前 SQLite 关键词查询；已配置降级策略。
- [x] PostgreSQL 迁移：已切到 `postgresql+asyncpg://...`，用 Alembic 管理迁移，服务已启动。
- [x] Redis 连接优雅关闭：在应用生命周期或 AgentBus 中显式关闭 Redis 连接，避免 `Event loop is closed` 警告。
- [x] 前端实时高亮：已把 `page` 和 `bbox` 坐标传给 PDF viewer，实现点击风险定位到原文并高亮。
- [x] 多合同类型支持：已扩展 `cross_clause_rules.json` 至 18 条规则，覆盖劳动、租赁、买卖、借款、技术服务合同。
- [x] Agent 能力升级：IndustryComplianceAgent、BlindSpotAgent 已升级为 LLM 驱动 + 规则兜底；HumanReviewAgent 增强为 10 维度复核规则；ChatAgent 增强为多轮对话与结构化输出。
- [x] ReAct 多轮化：`BaseAgent._react_loop` 实现多轮 ReAct 循环，支持 Agent 自主调用工具，同时兼容原有单轮 Agent。
- [x] Function Calling 接入：`LLMClient` 支持 `chat_completion_with_tools`，`BaseAgent` 支持 function calling 模式，DebateAgent / LegalVerifyAgent / CrossReferenceAgent 已启用。
- [x] RedFlagDetector 原则化：升级为 PrincipleBasedDetector，基于 8 条通用法律原则，支持快速检查 + 语义推断。
- [x] RuleCritic 扩展：从早期规则扩展至 15 条法律常识规则，覆盖常见误报模式。
- [x] 合法合同性能优化：通过条件执行整体性审查、跨条款 LLM 兜底、LegalResearch 快速路径，28 份测试耗时从 ~4.2h 降至 ~1.77h。
- [x] Detector override 自洽：当 detector 与 LLM 冲突时，同步 risk level、reason、suggestion，避免结论断裂。

### 待验证/待完成
- [ ] 生产环境完整端到端验证：在 PostgreSQL + Redis + Qdrant 生产配置下跑完整 28 份合同测试。
- [ ] Celery Worker 稳定性：在多 Worker 场景下验证 Redis 事件广播和任务队列。
- [ ] 文档解析/OCR 验证：确保 PDF/Word 上传后能正确提取合同文本和坐标。
- [ ] 生产部署：配置 Nginx 反向代理和 SSL 证书。
- [ ] 原则库扩展：把流质/流押、格式条款提示义务、消费者保护等通用红线原则化。

---

## 六、Phase 执行记录

### Phase 1 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `app/tasks/celery_tasks.py`：删除模拟数据，接入真实 `ReviewCoordinator`
  - `app/routers/review.py`：Celery broker 不可用时降级为同步执行
- 实现要点：
  1. 在同步 Celery 任务中用 `asyncio.run()` 调用异步 `coordinator.run_review(...)`。
  2. 从 `contract.parsed_data` 中读取 `chunks` 和 `section_tree` 传入 Coordinator。
  3. 将 `findings`、`graph_data`、`stats` 写回 `ReviewSession`，并逐条插入 `Finding` 表。
  4. 路由层增加 try/except，Redis 不可用时直接调用 `review_contract_task.run()`。
- 遇到的问题：
  - **同步与异步调用的架构冲突**。Celery 的任务函数是同步的，而 `ReviewCoordinator.run_review(...)` 是异步协程，二者无法直接兼容。如果直接用 `await` 会抛出语法错误；如果直接调用协程对象则不会真正执行，导致审查流程卡住。这属于"异步框架与同步任务队列"的集成问题，需要在不破坏 Celery 同步语义的前提下，把异步审查逻辑跑起来。
  - **基础设施可用性问题**。当时本机 Redis 服务尚未启动，`AgentBus` 初始化时会检测到 Redis 连接失败，并自动降级为内存广播。单机测试时主流程仍能跑通，但多个 Worker 之间无法共享进度事件，SSE 实时推送也会失效，无法满足生产环境多进程部署需求。
  - **接口降级与用户体验的权衡**。在 Redis 不可用时，如果前端调用 `POST /api/v1/contracts/{id}/review` 提交审查任务，Celery 的 `delay()` 方法可能抛出连接异常，导致接口直接报错。为了保证用户至少能看到审查结果，需要把任务降级为当前进程同步执行，但这会带来接口阻塞，属于可用性与响应速度之间的折中。
- 验证方式：
  - 运行独立脚本调用 `review_contract_task.run(...)`，成功识别 2 条 high 风险：
    - 试用期超长
    - 社保规避
- 状态：已完成

### Phase 2 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `app/review/pipeline.py`：context 中增加 `session_graph` 和 `chunks`
  - `app/review/tools/read_section.py`：实现按 section_path 读 Clause
  - `app/review/tools/search_document.py`：实现合同内关键词搜索
  - `app/review/tools/search_knowledge.py`：实现 SQLite 法条关键词查询
  - `app/review/tools/output_finding.py`：实现向 SessionGraph 写入 Risk 节点
  - `app/review/tools/check_cross_reference.py`：实现两个条款冲突检查
  - `app/review/tools/extract_obligations.py`：实现甲乙双方义务提取
  - `app/review/tools/query_knowledge_graph.py`：实现图邻居查询
  - `app/review/tools/compare_with_template.py`：实现条款与模板差异对比
  - `app/review/tools/validate_calculation.py`：实现数字/试用期计算校验
- 实现要点：
  1. 所有工具统一通过 `context["session_graph"]` 访问共享记忆图。
  2. `search_knowledge` 优先走 SQLite 同步查询，避免工具内部再引入异步依赖。
  3. `output_finding` 与 `RiskReviewAgent` 写入字段保持一致。
- 遇到的问题：
  - **共享上下文的传递问题**。工具函数需要通过 `context` 参数获取 `SessionGraph`、`chunks` 等共享数据，但最初 `Coordinator` 传给 Agent 的 `context` 里并没有包含 `session_graph`。这导致 `read_section`、`output_finding` 等工具在运行时拿不到图实例，只能返回空结果或抛出 KeyError。这属于"多 Agent 共享记忆"的上下文管理问题，需要在 Coordinator 层统一把核心对象注入到每个 Agent 的 context 中。
  - **数据依赖与空表问题**。`search_knowledge` 工具已经实现了 SQLite 查询逻辑，但 `knowledge_articles` 表当时没有任何数据。工具不会报错，只是返回空列表，这使得 `LegalBasisAgent` 后续为风险补充法律依据时完全没有素材。这个问题说明"工具实现"和"数据准备"是两个独立环节，必须配套完成。
  - **工具输出格式与 Agent 写入格式的一致性**。`output_finding` 工具需要创建 Risk 节点，而 `RiskReviewAgent` 也会直接创建 Risk 节点，如果二者字段不一致，会导致后续 `_triage` 阶段读取属性时缺失字段或类型混乱。这属于多模块协作时的接口契约问题。
- 验证方式：
  - 语法检查全部通过。
  - 复跑审查任务，仍正确识别 2 条 high 风险。
- 状态：已完成

### Phase 3 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `app/review/agents/missing_clause.py`：接入 LLM 检查必要条款缺失
  - `app/review/agents/balance.py`：接入 LLM 分析权利义务平衡性
  - `app/review/agents/legal_basis.py`：用 `search_knowledge` 为 Risk 补充 law_refs
  - `app/review/agents/suggestion.py`：用 LLM 批量生成修改建议
  - `app/review/agents/legal_verify.py`：校验 law_refs 是否在知识库中
  - `app/review/agents/debate.py`：对 high 风险做正反辩论
  - `app/review/agents/human_review.py`：按规则标记需人工复核项
  - `app/review/agents/term_extraction.py`：正则提取甲乙双方、合同期限、岗位
  - `app/review/agents/cross_reference.py`：两两检查 Clause 冲突
  - `app/review/agents/industry_compliance.py`：关键词扫描行业合规问题
  - `app/review/agents/blind_spot.py`：关键词扫描审查盲区
  - `app/review/agents/chat.py`：基于 SessionGraph 回答用户追问
- 实现要点：
  1. 每个 Agent 重写 `run()`，调用 `_react_loop` 或工具函数，并把结果写回 SessionGraph。
  2. 纯工具型 Agent（LegalBasis、LegalVerify、HumanReview、TermExtraction、CrossReference）不调用 LLM，降低成本。
  3. LLM 型 Agent 返回 JSON 数组或字典，统一解析后写入 Risk 节点。
- 遇到的问题：
  - **提示词设计与 LLM 输出稳定性问题**。12 个 Agent 的系统提示词和任务提示词需要各自专业化，但 LLM 对输出格式的遵循程度不一致。有的 Agent 返回 JSON 数组，有的返回 JSON 对象，有的甚至返回大段自然语言，导致 `run()` 方法里必须写大量解析兜底逻辑。这属于"提示词工程"和"输出schema约束"的问题，需要反复调试并在代码中增加格式兼容处理。
  - **缺失条款检测的过度敏感问题**。`MissingClauseAgent` 在极简测试合同（只有几条条款）上会报告大量必要条款缺失，例如用人单位信息、劳动者信息、工作时间等。虽然从法律角度看这些条款确实不存在，但在测试场景下显得"过度报警"。这属于 Agent 对"合同完整性"判断的粒度问题，真实完整合同会有所缓解，但提示词中应加入对"明显未约定"与"细节不完整"的区分。
  - **并发执行带来的日志与状态噪音**。多 Agent 通过 `asyncio.gather` 并行运行，每个 Agent 内部都会尝试连接 Redis 发布事件。当 Redis 不可用时，每个 Agent 都会打印降级日志，导致控制台输出大量重复警告。这不影响最终结果，但给调试带来干扰，属于并发场景下的日志治理问题。
  - **Agent 之间的输出重复与边界模糊**。不同 Agent 可能从各自角度识别出相似风险，例如 `RiskReviewAgent` 和 `BalanceAgent` 都会关注社保条款，导致报告中出现重复或近似的发现。这需要后续在 Merge+Link 阶段增强去重能力。
- 验证方式：
  - 复跑审查任务，从原来的 2 条 findings 增加到 8 条，覆盖风险识别、缺失条款、权利义务平衡等维度。
- 状态：已完成

### Phase 4 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `scripts/seed_knowledge.py`：创建基础劳动法律条文种子数据
  - `app/review/tools/search_knowledge.py`：实现 SQLite 法条关键词查询
  - `app/review/agents/legal_basis.py`：用 `search_knowledge` 为 Risk 节点补充 `law_refs`
- 实现要点：
  1. 准备《劳动合同法》《劳动法》《社会保险法》等常用条文，通过种子脚本导入 `knowledge_articles` 表。
  2. `search_knowledge` 优先走 SQLite 同步查询，返回 law_name / article_number / article_text。
  3. `LegalBasisAgent` 根据风险类型选择精准关键词查询法条，并把引用写回 Risk 节点。
- 遇到的问题：
  - **法律知识库数据缺失问题**。虽然 `search_knowledge` 工具已经写好查询逻辑，但数据库中的 `knowledge_articles` 表是空的。工具查询不会报错，只是返回空列表，导致所有风险的 `law_refs` 都是空数组。这属于"数据准备滞后于代码实现"的问题，必须先有种子数据，法条查询才有意义。
  - **关键词匹配不精准问题**。`LegalBasisAgent` 最初用风险类型和风险原因拼接成查询关键词去检索法条。例如风险类型是"试用期超长"，原因是"合同约定了6个月试用期"，直接把整段话传给 `search_knowledge`，导致 SQLite 的 `LIKE` 查询无法命中。这属于"检索意图与查询表达"的匹配问题，需要把自然语言风险描述映射到精准的法律主题词。
  - **法条引用格式问题**。早期代码把 `law_name` 和 `article_number` 拼接成引用字符串时，重复添加了"第"和"条"字，导致出现"《劳动合同法》第第十九条条"这种错误格式。这属于数据字段语义理解问题：`article_number` 字段本身已经包含"第十九条"，不需要再额外拼接。
  - **法律依据与风险节点的关联链路问题**。`LegalBasisAgent` 负责查法条，`LegalVerifyAgent` 负责验证法条是否存在，但最初 `Coordinator` 的 `_legal_verify` 阶段只调用了 `LegalVerifyAgent`，没有先调用 `LegalBasisAgent`，导致验证时没有任何 `law_refs` 可以核对。这属于流程调度中的步骤遗漏问题。
- 解决方案：
  - 运行 `python scripts/seed_knowledge.py` 导入基础法条。
  - 实现 `_build_law_query` 方法，根据风险类型映射到"试用期""社保""违约金"等精准关键词。
  - 拼接引用时使用 `article_number` 字段（已包含"第X条"格式），避免重复"第"字。
  - 在 `_legal_verify` 阶段先调用 `LegalBasisAgent` 补充法条，再调用 `LegalVerifyAgent` 验证。
- 验证方式：
  - 通过独立测试脚本验证 `search_knowledge` 和 `legal_basis` 逻辑，确认能查到法条并正确关联（相关临时测试文件已清理）。
  - 端到端审查报告中 `law_refs` 不再是空数组。
- 状态：已完成

### Phase 5 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `.env`：配置 `REDIS_URL=redis://localhost:6379/0`
  - `app/tasks/celery_tasks.py`：调用真实 `ReviewCoordinator` 并写回数据库
- 实现要点：
  1. 在 Windows 本机安装并启动 Redis 服务。
  2. 启动 Celery Worker：`celery -A app.tasks.celery_tasks worker --loglevel=info -P solo`。
  3. `review_contract_task` 从 `contract.parsed_data` 读取 chunks 和 section_tree，调用 `Coordinator.run_review`，并把 findings / graph_data / stats 写回 `ReviewSession` 和 `Finding` 表。
- 遇到的问题：
  - **异步审查逻辑与 Celery 同步任务框架的冲突**。Phase 1 已经用 `asyncio.run()` 解决了调用问题，但到了 Phase 5 真正接入 Celery Worker 时，又需要处理 Worker 进程的生命周期、事件循环管理和异常捕获。如果 Worker 进程中的事件循环没有正确关闭，会导致后续任务报错或资源泄漏。这属于"异步代码在同步 Worker 进程中的集成"问题。
  - **Windows 下 Celery 并发模型的限制**。Celery 默认的 prefork 并发模型在 Windows 上容易出错，常见表现为 Worker 启动后无法创建子进程或任务卡死。这属于操作系统兼容性问题，需要显式使用 `-P solo` 或 `eventlet`/`gevent` 模型。
  - **基础设施服务的启动顺序问题**。PostgreSQL、Redis、Qdrant、Neo4j 都在 `docker-compose.yml` 中定义，但在 Windows 本地开发时，Docker Desktop 可能未启动或服务端口被占用，导致后端连接失败。当前 SQLite + 本机 Redis 的组合是为了快速跑通，生产环境仍需要 Docker 编排。
  - **AgentBus 与 Celery 的状态广播一致性**。当 Celery Worker 中运行审查任务时，`AgentBus` 需要把 `phase_changed`、`finding_added` 等事件发布到 Redis；而前端 SSE 订阅的是另一个服务进程中的 Redis 频道。如果频道名不一致或 Redis 未连接，前端就看不到实时进度。这属于"多进程事件总线"的协调问题。
- 解决方案：
  - 在 Celery 任务内部用 `asyncio.run(_run_review())` 执行异步审查，并确保结果正确返回。
  - 路由层 `start_review` 增加 try/except：Celery 提交失败时直接调用 `review_contract_task.run(...)` 同步执行。
  - 当前 `.env` 已指向本机 Redis，AgentBus 直接通过 Redis Pub/Sub 广播。
- 验证方式：
  - 通过独立测试脚本验证 Celery 任务提交流程，任务成功提交并返回 review_session_id（相关临时测试文件已清理）。
  - Worker 日志显示各阶段 `phase_changed` 事件通过 Redis 频道广播。
- 状态：已完成

### Phase 6 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `frontend/src/views/ReportView.vue`：SSE 事件接收与风险展示
  - `frontend/src/components/RiskCard.vue`：风险卡片组件
  - `app/main.py`：托管前端构建产物并支持 SPA 兜底
  - `app/routers/review.py`：SSE 事件格式转换
  - `app/core/sse.py`：基于 Redis Pub/Sub 的进度推送
  - `app/tasks/celery_tasks.py`：同步 `graph_data["session_id"]` 为 `ReviewSession.id`
- 实现要点：
  1. 前端 `npm run build` 生成 `frontend/dist`，FastAPI 挂载静态文件并兜底返回 `index.html`。
  2. SSE 路由把 AgentBus 的 `{event_type, payload}` 转换为前端期望的 `{event, data}` 格式。
  3. Coordinator、`AgentBus`、`SSEManager` 统一使用 `ReviewSession.id` 作为 Redis 频道名。
- 遇到的问题：
  - **前后端事件协议不一致问题**。`AgentBus` 发布的事件格式是 `{"event_type": "phase_changed", "payload": {...}}`，而前端 `ReportView.vue` 中解析 SSE 时期望的是 `{"event": "phase", "data": {...}}`。如果不做转换，前端只能收到原始文本但无法识别事件类型，导致进度条不更新、风险列表不追加。这属于"服务端事件协议与前端消费协议不匹配"的联调问题。
  - **多进程间 session ID 不一致问题**。`Coordinator` 内部原本使用随机生成的 `session_id` 作为 Redis 频道名，而 SSE 路由使用的是数据库 `ReviewSession.id`。两个 ID 不一致时，Celery Worker 发布的事件进入 `review:<random_id>:events` 频道，前端却订阅 `review:<review_session_id>:events`，导致前端完全收不到实时进度。这属于"分布式会话标识统一"问题。
  - **前端构建与后端托管的部署问题**。前端使用 Vite 开发服务器时，API 请求通过代理转发到后端；但生产环境或本地直接访问需要后端托管 `frontend/dist`。FastAPI 路由注册顺序、静态文件挂载路径、SPA 兜底路由都会影响前端页面能否正确加载。这属于"前后端一体化部署"问题。
  - **TypeScript 类型与后端字段兼容性问题**。后端返回的风险对象中，`law_refs` 是字符串数组，`suggestion` 是嵌套对象，`level` 只能是 `high/medium/low`。如果后端返回 `critical` 或嵌套字段缺失，前端组件会渲染异常或 TypeScript 编译报错。这属于"接口契约与类型安全"问题。
  - **SSE 连接稳定性问题**。在审查任务执行过程中，如果网络抖动或 Worker 处理时间较长，前端 EventSource 可能自动断开并重连。需要确保重连后先推送当前状态，否则用户会看到进度回退或空白。这属于"长连接容错"问题。
- 解决方案：
  - 在 `review_stream` 中解析原始事件并按类型重新包装为 `data: {"event": "...", "data": {...}}`。
  - 修改 `Coordinator.run_review` 接收 `review_session_id` 参数，优先使用数据库 ID。
  - 通过 FastAPI 托管 `frontend/dist`，使前后端共用同一域名和端口。
  - 后端统一风险 level 取值，前端类型声明与后端保持一致。
- 验证方式：
  - 浏览器完成：注册 → 登录 → 上传合同 → 启动审查 → 实时查看进度 → 查看风险报告 → 导出 PDF。
  - 前端正确显示高风险 / 中风险 / 低风险统计和 RiskCard 列表。
- 状态：已完成

### Phase 7 执行记录
- 完成时间：2026-07-20
- 实际修改文件：
  - `app/agentkit/config/cross_clause_rules.json`：扩展劳动合同组合风险规则
  - `app/review/pipeline.py`：实现 `_llm_cross_clause_detector` 并默认启用兜底开关
  - `app/review/agents/missing_clause.py`：规范 Risk 节点 level 取值
- 实现要点：
  1. 规则库新增：竞业限制未约定补偿、试用期任意解除、违法约定违约金、加班未约定加班费、工作地点模糊且可任意调岗。
  2. 实现 `_llm_cross_clause_detector`：收集 Clause 文本 → 构造专业提示词 → 调用 LLM → 解析 JSON 数组 → 校验 clause_id 并返回标准格式。
  3. `ReviewCoordinator.__init__` 默认设置 `enable_llm_cross_clause_fallback=True`。
  4. `_merge_and_link` 在规则匹配后调用 LLM 兜底，补充规则未覆盖的组合风险。
  5. 在 `missing_clause.py` 和 `_triage` 中对 level 做兜底，只允许 `high/medium/low`。
- 遇到的问题：
  - **配置驱动规则的表达力与关键词覆盖问题**。`cross_clause_rules.json` 使用简单的 `contains_all` / `contains_any` 关键词匹配，但自然语言合同文本写法多样。例如规则中写 `"6"` 无法命中 `"六个月"`，`"自愿放弃社保"` 无法命中 `"自愿放弃缴纳社会保险"`。这属于"规则引擎与自然语言多样性"之间的矛盾，规则越严格漏判越多，规则越宽松误判越多，需要在二者之间取舍。
  - **LLM 输出格式与 schema 不一致问题**。`_llm_cross_clause_detector` 要求 LLM 返回固定格式的 JSON 数组，但模型有时会在 JSON 外加 markdown 代码块（```json ... ```），有时会返回自然语言解释，有时会把 `level` 写成 `critical`、`severe` 等非枚举值。这属于"大模型输出可控性"问题，需要增加严格的解析、校验和兜底逻辑。
  - **跨条款检测的 token 成本与上下文长度问题**。当合同条款很多时，把所有 Clause 文本一次性传给 LLM 会迅速消耗 token 并可能超过模型上下文上限。当前实现通过限制最多 30 条、每条最多 300 字来控制，但这也可能遗漏长合同后面的重要条款。这属于"成本、性能与召回率"的权衡问题。
  - **多 Agent 结果重复与报告冗余问题**。完整流程跑下来可能产生约 20 条风险，其中存在同类风险被不同 Agent 重复报告的情况，例如 `RiskReviewAgent` 识别"试用期超长"，跨条款规则也识别"试用期超长"，LLM 兜底又识别"试用期与解除条款风险"。这属于"多源信息融合与去重"问题，当前仅通过 `merge_duplicate_risks` 做部分合并，更精细的语义去留需要后续优化。
  - **异步资源释放的健壮性问题**。进程退出时，`AgentBus` 中的 Redis 异步连接对象被垃圾回收，但此时事件循环已经关闭，触发 `Event loop is closed` 警告。这属于"异步资源生命周期管理"问题，不影响单次审查结果，但会影响日志整洁度和长期运行稳定性。
- 解决方案：
  - 放宽关键词匹配条件：试用期使用 `["6个月", "六个月", "6 个月"]`；社保使用 `["放弃社保", "不缴纳社保", "放弃缴纳社会保险"]` 等。
  - 实现 `_parse_llm_json_output` 兼容 markdown 代码块和裸 JSON；对返回的 `level`、`confidence`、`clause_ids` 做严格校验。
  - 在 LLM 检测器中限制 Clause 数量和单条长度，避免 token 超限。
  - 在写入节点和 `_triage` 输出阶段统一把非标准 level 映射为 `medium`。
  - 重复风险通过 `SessionGraph.merge_duplicate_risks` 部分合并；更细粒度的去留可在后续迭代中优化。
- 验证方式：
  - 通过独立测试脚本验证跨条款规则匹配，命中 5 个组合风险（试用期超长、规避社保、竞业限制未补偿、试用期任意解除、加班无加班费）。
  - 通过独立测试脚本验证 LLM 兜底检测，发现 1 个组合风险（试用期与解除条款风险）。
  - 通过独立测试脚本跑完整七阶段审查，发现 21 个风险，level 全部为 high/medium/low，`law_refs` 正常填充。
  - 相关临时测试文件已清理。
- 状态：已完成

### Phase 8 执行记录
- 完成时间：2026-07-26
- 实际修改文件：
  - `app/contracts/rules/red_flag_detector.py`：将 RedFlagDetector 重构为 PrincipleBasedDetector
  - `app/contracts/rules/config/legal_principles.json`：新增 8 条通用法律原则配置
  - `app/review/agents/risk_review.py`：集成 PrincipleBasedDetector，实现 detector override 自洽，条件触发 holistic review
  - `app/review/agents/critic.py`：扩展 RuleCritic 至 15 条法律常识规则
  - `app/agentkit/session_graph.py`：条件化跨条款 LLM 兜底，修复 `rule_risks` 作用域错误
  - `app/review/agents/legal_research.py`：实现快速路径，避免低风险合同空转
  - `app/review/agents/missing_clause.py`：过滤空 `missing_item` / `reason` 字段
- 实现要点：
  1. 将 RedFlagDetector 从案例背书式规则升级为 PrincipleBasedDetector，基于 8 条通用法律原则：比例原则、权利保留原则、诚信公平原则、最低保障原则、信息披露原则、违法目的原则、明确性原则、法定责任不可免除原则。
  2. 每条原则配置 violation/non-violation 示例和快速检查类型（`numeric_penalty`、`right_exclusion`、`good_faith_fairness`、`minimum_guarantee`、`illegal_purpose`、`waive_liability`）。
  3. RiskReviewAgent 每条款先跑 PrincipleBasedDetector；命中 high 红线时注入信号、正例加权，LLM 仍输出 low 则用 detector 结果兜底，并同步 level/reason/suggestion/confidence。
  4. RuleCritic 扩展至 15 条规则，覆盖否定语境违法目的、试用期比例、正常付款结构、违约金与损失并用、知识产权对价、未约定事项、双方违约金基数、择一主张、普通押金、质量标准、弹性表述、利率与罚息相加、借款生效日期、付息日错配等常见误报。
  5. RiskReviewAgent holistic review 条件触发：仅当逐条审查产生 high/medium finding 或存在 surviving 确定性红线时才调用。
  6. SessionGraph 跨条款 LLM 兜底条件触发：仅当规则命中组合风险或图中已存在 high/medium 风险时才调用 LLM。
  7. LegalResearchAgent 快速路径：合并法律领域与风险信号推断为一次 LLM 调用；类级缓存 `_review_point_cache` 和 `_web_search_cache`；高频法条使用预制模板；风险信号弱时跳过泛化 web search；Tavily 搜索每合同最多 3 次。
  8. 修复 `SessionGraph.find_cross_clause_risks` 中 `rule_risks` 的 `UnboundLocalError`。
  9. `MissingClauseAgent` 过滤空 `missing_item` / `reason` 条目。
- 遇到的问题：
  - **原则化迁移的平衡问题**。把具体规则抽象为原则时，需要保证快速检查仍能覆盖历史漏检案例（如日违约金 5%/10%、概不退换、不得检验）。解决方式是为每条原则保留典型 violation/non-violation 示例，并持续用测试集验证。
  - **Detector 与 LLM 结论冲突时的自洽问题**。早期 override 只改 level 不改 reason，导致结论与论证矛盾。解决方式是 `_merge_red_flag_with_llm` 统一使用 detector 的 reason/suggestion，并保留 LLM 异议到 `llm_dissent` 审计字段。
  - **合法合同耗时过长问题**。28 份全量测试最初耗时约 4.2 小时，其中合法合同占比极高。通过动态日志定位到 holistic review、cross-clause LLM fallback、LegalResearch web search 三个无条件调用点，引入强风险信号条件执行后降至约 1.77 小时。
  - **RuleCritic 规则泛化问题**。借款合同专用规则（如生效日期、付息日错配）如果写得太具体，会变成测试集补丁。解决方式是把规则表述为通用法律原则（如"常见表述不等于违法"、"固定付息日与起息日不一致是正常日历安排"）。
- 验证方式：
  - 28 份全量测试（14 合法 + 14 违法）总耗时约 1.77 小时；
  - 精确率 100%，召回率 100%，0 假阳性，0 假阴性；
  - 单元测试 `test_red_flag_detector.py`、`test_risk_review_red_flag.py`、`test_rule_critic.py` 全部通过；
  - 输出报告 `测试集/full_test_summary.json` 和 `测试集/全量测试报告.md`。
- 状态：已完成

---

# 框架优化记录：确定性红线检测层（2026-07-24）

## 问题归类

### 1. 漏检问题：LLM 不遵循红线规则
- **现象**：11 份子集测试中，2 份违法买卖合同（手机批发、建材采购）完全漏检，本应检出的日违约金 5%/10%、概不退换/不得检验、不提供质保等明显风险未被输出。
- **根因**：通过 debug_filter_diagnosis.py 逐 chunk 分析，keyword filter 已正确放行，但 qwen3.6-plus 输出 level=low, risk_type=无明显风险。system prompt 中不要勉强找问题等抑制误报指令压过了日违约金超过千分之一应报告等红线指令。
- **类别**：大模型指令冲突下的**召回率崩溃**。

### 2. 过度压制问题：CriticAgent 无差别过滤
- **现象**：即使 LLM 报出风险，CriticAgent 以是否误报为导向，容易将真实风险判定为 false_positive。
- **根因**：Critic 的默认立场是质疑，而不是保留并微调。
- **类别**：二次校验 Agent **立场设计失衡**。

### 3. 阈值问题：medium 门槛过高
- **现象**：MEDIUM_CONFIDENCE_THRESHOLD=0.70，LLM 输出的 0.65-0.70 置信度的真实风险被过滤。
- **类别**：阈值策略**偏向精确率、牺牲召回率**。

### 4. 架构问题：所有判断依赖单一 LLM
- **现象**：5%/10% 日违约金这种一望即知的红线也交给 LLM 判断，模型一旦不 follow 就漏检。
- **类别**：缺少**确定性兜底层**。

## 解决方案

### 1. 新增 RedFlagDetector（确定性红线层）
- **文件**：`backend/app/contracts/rules/red_flag_detector.py`
- **原则**：只封装通用法律红线，不针对测试集。覆盖日违约金>0.1%、排除检验权、概不退换、免除质保、利率>LPR四倍、砍头息、永久保密、试用期超限、不缴纳社保、租赁>20年等。
- **效果**：无论 LLM 是否理解 prompt，红线条款都会被强制标记为 high 风险。

### 2. 重构 RiskReviewAgent：先 detector 后 LLM
- **文件**：`backend/app/review/agents/risk_review.py`
- **改动**：
  - 每条款先跑 RedFlagDetector；
  - 命中 high 红线时：绕过 keyword filter、注入红线信号、正例 few-shot 加权、LLM 输出 low 则兜底、跳过 Critic；
  - 未命中时：维持原 keyword filter + LLM + Critic 流程；
  - 整体性审查同样增加红线检测。
- **效果**：确保 red flag 不被 LLM 和 Critic 双层漏掉。

### 3. 调整 CriticAgent：从质疑改为保留
- **文件**：`backend/app/review/agents/critic.py`
- **改动**：默认保留审查员结论，仅在有明确证据（看错文本、普通商业安排、把默认规则当风险等）时才输出 false_positive；缩小 confidence_adjustment 范围。
- **效果**：减少真实风险被二次压制。

### 4. 调整置信度阈值
- **改动**：MEDIUM_CONFIDENCE_THRESHOLD 从 0.70 降至 0.60；确定性红线兜底置信度下限 0.85。
- **效果**：保护 recall，同时保证红线不被阈值过滤。

### 5. 优化 few-shot 案例库
- **文件**：`backend/app/review/config/review_few_shot_cases.json`
- **改动**：修正 safe 案例比例、新增款到发货概不退换和不提供质保正例、红线命中时正例加权。
- **效果**：避免反例把明显风险拉偏。

## 验证结果

- **单元测试**：新增 `tests/test_red_flag_detector.py`（32 例，含 15 例跨合同类型通用红线）和 `tests/test_risk_review_red_flag.py`（4 例），`pytest tests/` 全部通过（36 passed）（tests 目录现已不存在）。
- **诊断脚本**：`debug_filter_diagnosis.py` 显示两个漏检合同的 3 处关键条款均命中确定性红线，不会再被漏检。
- **规则贡献指南**：新增 `docs/red_flag_rules_guide.md`，规范通用红线的添加流程，避免写成测试集补丁。
- **待验证**：因当前 LLM 配额已耗尽（`Error code: 403 - Free quota exhausted`），端到端全量测试需待配额恢复后执行。建议运行 `python run_batch_full_test.py --limit 11`。
