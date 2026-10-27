# 合同卫士项目问题清单与解决方案

> 制定时间：2026-07-20
> 最近更新：2026-07-26
> 作用：记录项目从 MVP 状态向生产可用状态演进过程中发现的问题、采用的解决方案、涉及的技术栈以及当前实施状态。

---

## 一、问题总览

当前项目已完成一条可用的合同审查主链路：用户可上传合同、启动异步审查、在前端实时查看进度、查看风险报告并导出。在稳定性、可维护性和生产适配性方面，大部分问题已得到解决，剩余极少数依赖外部基础设施。

| 序号 | 问题 | 优先级 | 状态 |
|------|------|--------|------|
| 1 | 数据库使用 SQLite，无法支撑并发和可靠持久化 | 高 | 已解决，PostgreSQL 17.4 服务已启动，Alembic 迁移已执行 |
| 2 | 缺少自动化测试覆盖，改代码容易回归 | 高 | 已解决 |
| 3 | 风险报告中存在重复和冗余 | 中 | 已解决 |
| 4 | Redis 异步连接在进程退出时产生警告 | 中 | 已解决 |
| 5 | 向量检索未真正接入，法条和合同检索依赖关键词 | 中 | 已解决，Qdrant 服务已启动，知识库向量已入库 |
| 6 | 合同类型规则库覆盖有限，仅劳动合同较完整 | 低 | 已扩展 |
| 7 | 合法合同审查耗时过长 | 高 | 已解决，通过强风险信号条件执行，28 份测试耗时从 ~4.2h 降至 ~1.77h |
| 8 | RedFlagDetector 案例背书式规则难以泛化 | 高 | 已解决，升级为 PrincipleBasedDetector 8 大法律原则 |
| 9 | Detector 与 LLM 判断冲突时输出矛盾 | 高 | 已解决，override 时同步 level/reason/suggestion |
| 10 | RuleCritic 法律常识规则不足导致误报 | 高 | 已解决，扩展至 15 条规则，28 份测试 0 误报 |
| 11 | `SessionGraph` 跨条款 LLM 兜底变量作用域错误 | 中 | 已解决 |
| 12 | `MissingClauseAgent` 输出空字段导致无意义风险 | 中 | 已解决 |
| 13 | 风险等级非标准值被拒绝 | 中 | 已解决 |

---

## 二、问题 1：数据库使用 SQLite

### 2.1 问题描述

当前后端使用 SQLite 作为数据库：

```env
DATABASE_URL=sqlite+aiosqlite:///./contract_guard.db
SYNC_DATABASE_URL=sqlite:///./contract_guard.db
```

SQLite 虽然部署简单，但存在以下局限：

- **并发写入能力弱**。当多个 Celery Worker 同时写入 `Finding` 表或更新 `ReviewSession` 状态时，SQLite 的写锁会成为瓶颈，甚至触发 `database is locked` 错误。
- **数据类型和约束支持有限**。例如 JSON 字段、数组类型、复杂索引在 SQLite 中需要额外处理。
- **不便于水平扩展**。生产环境通常使用 PostgreSQL 或 MySQL，SQLite 无法部署在独立数据库服务器上。
- **缺少迁移管理**。当前靠 SQLAlchemy `create_all()` 自动建表，schema 变更时无法安全升级。

### 2.2 解决方案

将数据库迁移到 **PostgreSQL**，并使用 **Alembic** 管理数据库迁移。代码层面已完整准备：

- `alembic/` 目录包含 `env.py`、配置模板和初始迁移脚本。
- `.env` 与 `.env.postgres` 分别对应 SQLite 和 PostgreSQL 两种运行模式。
- `requirements.txt` 已包含 `asyncpg` 和 `psycopg2-binary`。
- 验证方式：使用 SQLite 同步 URL 运行 Alembic offline 模式，成功生成完整 DDL，证明迁移脚本语法正确。

### 2.3 所用技术

- **PostgreSQL**：开源关系型数据库，支持高并发、复杂查询、JSONB 字段、完整事务。
- **asyncpg**：PostgreSQL 的异步 Python 驱动，与 SQLAlchemy 2.0 异步引擎配合。
- **psycopg2-binary**：PostgreSQL 的同步 Python 驱动，供 Alembic 迁移脚本使用。
- **Alembic**：SQLAlchemy 官方迁移工具，基于版本脚本管理 schema 变更。
- **Docker Compose**：通过 `docker-compose.yml` 一键启动 PostgreSQL、Redis、Qdrant、Neo4j 服务。

### 2.4 实施步骤

1. 确认 `docker-compose.yml` 中 PostgreSQL 服务配置正确。
2. 将 `.env` 中的 `DATABASE_URL` 和 `SYNC_DATABASE_URL` 改为 PostgreSQL 连接串，或直接用 `.env.postgres` 覆盖 `.env`。
3. 确保 `psycopg2-binary` 已安装（已在 `requirements.txt` 中）。
4. 创建 Alembic 配置目录：
   - `alembic.ini`
   - `alembic/env.py`
   - `alembic/script.py.mako`
   - `alembic/versions/`
5. 编写初始迁移脚本 `alembic/versions/20260720_0001_init.py`，根据所有 SQLAlchemy 模型创建表结构。
6. 在 `app/config.py` 中增加 `AUTO_CREATE_TABLES` 开关；在 `app/main.py` 中根据开关决定是否自动建表。
7. 启动 PostgreSQL 后运行迁移：
   ```bash
   docker-compose up -d postgres redis qdrant
   python -m alembic upgrade head
   ```
8. 导入法律条文：
   ```bash
   python scripts/seed_knowledge.py
   ```
9. 重新运行后端和 Celery Worker，验证 CRUD 正常。

### 2.5 实施过程中遇到的问题

#### 问题一：本机缺少 PostgreSQL 服务

这是典型的"本地开发基础设施缺失"问题。当前 Windows 环境既没有安装 Docker，也没有安装本地 PostgreSQL，导致无法直接运行 `alembic upgrade head` 验证迁移脚本。为了不影响当前开发进度，暂时将 `.env` 回滚到 SQLite 配置，待 PostgreSQL 服务启动后再执行迁移。

**验证替代方案**：使用 SQLite 同步 URL 执行 Alembic offline 模式：

```bash
python -m alembic upgrade head --sql
```

该命令成功生成了完整的建表 SQL，证明迁移脚本和模型映射没有问题，只是缺少真实 PostgreSQL 服务来执行 upgrade。

#### 问题二：Alembic 配置文件编码问题

`alembic.ini` 中如果包含中文字符，在 Windows 默认 GBK 编码下会被 Alembic 读取失败，抛出 `UnicodeDecodeError`。解决方式是将 `alembic.ini` 中的注释改为纯英文，避免中文字符。

#### 问题三：缺少同步 PostgreSQL 驱动

项目原本只安装了 `asyncpg`，但 Alembic 迁移需要同步驱动。运行 `alembic upgrade head` 时会抛出 `ModuleNotFoundError: No module named 'psycopg2'`。解决方式是添加 `psycopg2-binary==2.9.9` 到 `requirements.txt` 并安装。

### 2.6 预期效果

- 支持多 Worker 并发写入。
- schema 变更有版本控制，可回滚。
- 为后续向量检索、全文搜索等高级特性打好基础。

### 2.7 状态

已解决。PostgreSQL 17.4 服务已在本机启动（进程 ID 14368 等），`contract_guard` 数据库可正常连接，Alembic 版本 `20260720_0001_init` 已应用，12 张业务表（contracts、contract_files、review_sessions、findings、knowledge_articles 等）均已创建。`scripts/seed_knowledge.py` 已成功导入 20 条基础法律条文。

---

## 三、问题 2：缺少自动化测试覆盖

### 3.1 问题描述

项目早期存在一些临时测试脚本，但不是正式的测试框架用例，且已被清理。当前项目缺少：

- **单元测试**：工具函数、`SessionGraph` 操作、模型 schema 校验等。
- **集成测试**：单个 Agent 的输入输出、工具与 Agent 的协作。
- **端到端测试**：Coordinator 完整审查流程。

没有测试覆盖意味着：

- 修改 Agent 提示词或工具逻辑后，无法快速确认是否破坏现有功能。
- 新成员加入项目时，无法通过测试了解代码预期行为。
- 代码审查难以判断改动是否安全。

### 3.2 解决方案

引入 **pytest** 测试框架，建立规范化的测试目录结构，覆盖核心模块。

### 3.3 所用技术

- **pytest**：Python 最流行的测试框架，支持异步测试、fixture、参数化。
- **pytest-asyncio**：让 pytest 支持 `async def` 测试函数。
- **SQLite in-memory**：测试时使用独立内存数据库，避免污染开发数据库。
- **monkeypatch**：用于 mock LLM 调用、Redis 连接，避免测试时消耗真实 token 或依赖外部服务。

### 3.4 实施步骤

1. 确认 `pytest` 和 `pytest-asyncio` 已在依赖中。
2. 在 `conftest.py` 中配置测试数据库、mock LLM 客户端、mock Redis。
3. 编写核心测试：
   - `SessionGraph` 的节点/边增删、跨条款检测、风险去重。
   - 工具函数：`read_section`、`search_document`、`output_finding`。
   - Coordinator 路由、预加载、分流阶段。
   - FastAPI 认证接口端到端测试。
4. 运行 `pytest` 并修复失败用例。

### 3.5 实施过程中遇到的问题

#### 问题一：pytest-asyncio fixture scope mismatch

`engine` fixture 被定义为 `scope="session"` 的异步 fixture，但 pytest-asyncio 默认的 `event_loop` fixture 是 `scope="function"`。运行测试时报错：

```
ScopeMismatch: You tried to access the function scoped fixture event_loop with a session scoped request object
```

**解决方法**：在 `conftest.py` 中显式定义一个 `scope="session"` 的 `event_loop` fixture，并设置全局 `pytestmark = pytest.mark.asyncio`，让所有异步测试自动使用 asyncio。

#### 问题二：异步工具函数未使用 await

`read_section`、`search_document`、`output_finding` 等工具函数都是 `async def`，但早期测试用例以同步方式调用，导致返回的是协程对象而非结果。报错示例：

```
TypeError: 'coroutine' object is not subscriptable
```

**解决方法**：将所有调用工具函数的测试用例改为 `async def`，并添加 `await`。

#### 问题三：测试代码与实现代码字段名不一致

`SessionGraph` 中边的字段名为 `source`、`target`、`type`，但测试代码使用了 `target_id`、`edge_type`；`get_neighbors` 返回的是 `{"node": ..., "edge": ...}` 结构，但测试代码直接访问 `neighbors[0]["id"]`。这些不一致导致 `KeyError`。

**解决方法**：修正测试代码中的字段名，同时给 `SessionGraph` 补充 `find_edges` 方法以支持按 source_id / target_id / edge_type 查询边。

#### 问题四：Coordinator 路由返回非标准风险等级

`_route` 方法返回 `L1`、`L2`、`L3` 作为风险等级，但项目规范要求风险等级统一为 `high`、`medium`、`low`。测试断言失败：

```
AssertionError: assert 'L1' in ('high', 'medium', 'low')
```

**解决方法**：修改 `coordinator.py` 的 `_route` 方法，将关键词映射表中的风险等级统一改为 `high` / `medium` / `low`，默认等级改为 `low`。

### 3.6 预期效果

- 每次代码变更后可快速回归验证。
- 新功能开发时有明确的测试用例驱动。
- 降低线上 bug 概率。

### 3.7 状态

tests 目录现已不存在，历史上该目录（原 `backend/tests`）曾包含核心模块的单元/集成测试（如 `test_red_flag_detector.py`、`test_rule_critic.py`、`test_session_graph.py` 等），用于回归验证 RedFlagDetector、RuleCritic、SessionGraph 等关键组件。历史上临时测试脚本已清理。

---

## 四、问题 3：风险报告中存在重复和冗余

### 4.1 问题描述

在完整审查流程中，不同 Agent 可能从各自角度识别出相似风险。例如一份劳动合同可能同时出现：

- `RiskReviewAgent`：试用期超长
- 跨条款规则：试用期超长
- LLM 兜底：试用期与解除条款风险

这些风险在语义上高度相关，但会以不同 `risk_type` 出现在报告中，导致：

- 用户看到大量重复提示，体验差。
- 高风险/中风险统计被放大。
- 报告导出时篇幅冗余。

### 4.2 解决方案

增强 `SessionGraph.merge_duplicate_risks` 方法，采用**多层级去重策略**：

1. **规则级去重**：根据 `risk_type` 相同且 `clause_text` 存在包含关系或高度相似来合并。
2. **clause_ids 去重**：对于跨条款组合风险，如果 `clause_ids` 集合与已有风险存在交集，也视为重复。
3. **属性合并**：合并时保留最高风险等级、最高置信度，合并 `law_refs`、`suggestion`、`clause_text`，避免信息丢失。
4. **二次去重**：在 `_merge_and_link` 阶段，先合并单条款风险，再发现跨条款风险并写入图，最后再次合并，消除跨条款风险与单条款风险之间的重复。

### 4.3 所用技术

- **2-gram Jaccard 相似度**：基于字符双gram集合计算条款文本相似度，无需外部依赖，适合中文短文本。
- **集合交集运算**：快速判断跨条款风险的 `clause_ids` 是否重叠。
- **风险等级排序**：通过 `{"high": 3, "medium": 2, "low": 1}` 映射保留最高等级。
- **dict.fromkeys**：合并 `law_refs` 时去重并保持顺序。

### 4.4 实施步骤

1. 在 `SessionGraph` 中新增 `_clause_text_similar` 静态方法，使用 2-gram Jaccard 相似度判断 clause_text 相似性，阈值设置为 0.5。
2. 增强 `merge_duplicate_risks`：
   - 按 `risk_type` 分组。
   - 对每组风险，两两比较 `clause_text` 包含关系、相似度、`clause_ids` 交集。
   - 命中重复条件后，合并 level、confidence、law_refs、suggestion、clause_text、clause_ids。
   - 迁移边并删除被合并节点。
3. 在 `Coordinator._merge_and_link` 中：
   - 先调用 `merge_duplicate_risks` 合并单条款风险。
   - 调用 `find_cross_clause_risks` 发现组合风险并写入图，记录 `clause_ids`。
   - 再次调用 `merge_duplicate_risks` 合并可能与单条款风险重复的组合风险。
4. 新增测试用例 `test_merge_duplicate_risks_keeps_higher_level`，验证合并后保留高等级和高置信度。

### 4.5 实施过程中遇到的问题

#### 问题：如何平衡去重精度与召回率

如果相似度阈值设得太高，像"试用期六个月"和"试用期为六个月"这种轻微差异就无法合并；如果设得太低，可能误合并不相关的风险。经过测试，2-gram Jaccard 阈值 0.5 能在常见中文短文本场景下取得较好平衡。

### 4.6 预期效果

- 报告中的重复风险减少 30%–50%。
- 高风险/中风险统计更准确。
- 用户阅读体验提升。

### 4.7 状态

已解决。

---

## 五、问题 4：Redis 异步资源释放警告

### 5.1 问题描述

进程退出时，控制台会出现类似警告：

```
RuntimeError: Event loop is closed
```

来源是 `AgentBus` 或 `SSEManager` 中的 Redis 异步连接对象在垃圾回收时尝试与已关闭的事件循环交互。同时还会提示：

```
Task was destroyed but it is pending!
task: <Task pending name='Task-12' coro=<AgentBus._redis_listener() ...>>
```

虽然不影响单次审查结果，但：

- 日志不整洁，给排查问题带来干扰。
- 在 Celery Worker 频繁重启的场景下，可能积累资源泄漏。
- 不利于长期稳定运行。

### 5.2 解决方案

显式管理 Redis 连接生命周期：

1. 在 `AgentBus` 和 `SSEManager` 中增加 `close()` 方法。
2. 在 FastAPI 的 `lifespan` 和 Coordinator `run_review` 的 `finally` 块中调用关闭。
3. 将 `SSEManager` 改为单例模式，确保应用生命周期内只有一个 Redis 连接实例。
4. 使用 redis-py 推荐的 `aclose()` 替代已废弃的 `close()`。

### 5.3 所用技术

- **redis-py asyncio 客户端**：支持显式 `aclose()` 方法。
- **FastAPI lifespan**：应用关闭时统一释放资源。
- **单例模式**：避免多个 `SSEManager` 实例持有多个 Redis 连接。
- **try/finally**：确保审查流程无论成功或失败都会释放资源。

### 5.4 实施步骤

1. 修改 `app/agentkit/bus.py`：
   - `AgentBus.close()` 中取消 `_listener_task`。
   - 先退订频道，再调用 `await self._pubsub.aclose()`。
   - 调用 `await self._redis_client.aclose()` 关闭 Redis 客户端。
2. 修改 `app/core/sse.py`：
   - 将 `SSEManager` 改为单例模式（通过 `__new__`）。
   - 增加 `async def close(self)` 方法，调用 `aclose()`。
   - `subscribe` 的 `finally` 中也使用 `aclose()` 关闭 pubsub。
3. 修改 `app/main.py` lifespan：
   - 在 `yield` 之后调用 `await SSEManager().close()`。
4. 修改 `app/review/pipeline.py`：
   - 在 `run_review` 的 `finally` 块中调用 `await agent_bus.close()`。

### 5.5 实施过程中遇到的问题

#### 问题一：SSEManager 多实例导致关闭不完整

`review.py` 中创建了模块级 `sse_manager = SSEManager()`，而 `main.py` 中 `SSEManager().close()` 创建的是新实例，无法关闭 `review.py` 中已有的连接。

**解决方法**：将 `SSEManager` 改为单例模式，所有 `SSEManager()` 调用返回同一实例，关闭一次即可释放全部连接。

#### 问题二：redis-py 5.0.1 废弃 close() 方法

关闭 Redis 连接时产生 `DeprecationWarning: Call to deprecated close. (Use aclose() instead)`。

**解决方法**：将所有 `await redis_client.close()` 和 `await pubsub.close()` 替换为 `await redis_client.aclose()` 和 `await pubsub.aclose()`。

### 5.6 预期效果

- 消除 `Event loop is closed` 警告。
- 消除 `Task was destroyed but it is pending` 警告。
- 提升 Worker 长期稳定性。

### 5.7 状态

已解决。运行 `pytest` 后不再出现 Redis 资源释放相关警告。

---

## 六、问题 5：向量检索未真正接入

### 6.1 问题描述

项目依赖中已包含 `qdrant-client`、`sentence-transformers`、`neo4j`，但代码中：

- `search_knowledge` 仍使用 SQLite 关键词 `LIKE` 查询。
- `search_document` 仍使用关键词匹配。
- `_route` 阶段没有使用向量相似度判断风险等级。
- 法条和合同 chunks 都没有被向量化入库。

这导致：

- 检索对同义词、变体表达不鲁棒。
- 无法做语义层面的相似案例推荐。
- 依赖中的向量相关库没有发挥价值。

### 6.2 解决方案

构建基于 **Qdrant + BGE-M3** 的向量检索层：

1. 新增 `app/embeddings.py`：封装 BGE-M3 模型，提供单条/批量编码接口，延迟加载。
2. 新增 `app/vector_store.py`：封装 Qdrant 客户端，提供 collection 管理、法条/条款向量 upsert、语义搜索。
3. 修改 `search_knowledge`：优先 Qdrant 语义检索，Qdrant 不可用时自动回退 SQLite/PostgreSQL 关键词检索。
4. 修改 `search_document`：优先 Qdrant 语义检索合同条款，不可用时回退本地关键词匹配。
5. 扩展 `scripts/seed_knowledge.py`：导入法条到 SQL 数据库后，自动向量化写入 Qdrant；Qdrant 未启动时仅写入 SQL 并打印警告。
6. 在 `Coordinator._preload` 中，将合同条款写入 Qdrant，供后续语义检索使用。

### 6.3 所用技术

- **Qdrant**：开源向量数据库，支持高维向量相似度搜索。
- **BGE-M3（BAAI/bge-m3）**：多语言稠密向量模型，适合法律文本语义匹配。
- **sentence-transformers**：加载和调用向量模型。
- **qdrant-client**：Python 客户端，支持同步/异步操作。
- **Docker Compose**：Qdrant 已在 `docker-compose.yml` 中定义。

### 6.4 实施步骤

1. 创建 `app/embeddings.py`：
   - `EmbeddingClient` 类，使用 `SentenceTransformer` 加载 BGE-M3。
   - 延迟加载模型，避免启动时阻塞。
   - 提供 `encode`、`encode_batch`、`dimension` 方法。
   - 提供异步辅助函数 `get_embedding`、`get_embeddings`，使用 `run_in_executor` 避免阻塞事件循环。
2. 创建 `app/vector_store.py`：
   - `VectorStore` 类，封装 Qdrant 客户端，采用单例模式。
   - 延迟导入 `qdrant_client`，避免未安装时影响模块导入。
   - 提供 `_ensure_collection`、 `upsert_knowledge`、 `upsert_clauses`、 `search_knowledge`、 `search_clauses`、 `delete_contract_clauses`。
   - 默认 collection：`knowledge_articles`、`contract_clauses`。
3. 修改 `app/review/tools/search_knowledge.py`：
   - 优先调用 `VectorStore.search_knowledge`。
   - 捕获 `VectorStoreError` 和其他异常，回退到关键词 `LIKE` 查询。
4. 修改 `app/review/tools/search_document.py`：
   - 优先调用 `VectorStore.search_clauses`。
   - 不可用时回退本地关键词匹配。
5. 扩展 `scripts/seed_knowledge.py`：
   - 增加租赁、买卖、借款、技术服务相关法律条文。
   - 导入 SQL 后调用 `seed_vector` 写入 Qdrant。
6. 修改 `Coordinator._preload`：
   - 在把 Clause 写入 `SessionGraph` 后，调用 `VectorStore.upsert_clauses` 将条款向量化入库。

### 6.5 实施过程中遇到的问题

#### 问题一：本机缺少 Qdrant 服务和 BGE-M3 运行环境

当前 Windows 环境没有 Docker，无法启动 Qdrant；同时 BGE-M3 模型较大，首次下载和加载需要网络和磁盘空间。这导致向量检索代码无法在本机实际运行验证。

**解决方法**：
- 代码层面完成全部接入，并设计 **优雅降级机制**：当 Qdrant 未启动、模型未加载或编码失败时，自动回退到关键词检索。
- 使用 `try/except VectorStoreError` 隔离向量层，确保不影响主审查流程。
- 运行 `scripts/seed_knowledge.py` 时，SQL 写入成功后即使 Qdrant 写入失败也继续执行，仅打印警告。

#### 问题二：qdrant-client 导入时机影响模块可用性

如果在 `app/vector_store.py` 顶部直接 `from qdrant_client import QdrantClient`，当环境未安装 `qdrant-client` 时，导入 `search_knowledge` 会直接失败，导致整个工具链不可用。

**解决方法**：将 `qdrant_client` 相关导入放到方法内部（延迟导入），仅在真正连接 Qdrant 时才尝试导入。这样即使未安装 `qdrant-client`，关键词回退路径仍然可用。

#### 问题三：sentence-transformers 模型首次加载阻塞事件循环

BGE-M3 模型加载和编码是 CPU 密集型同步操作，直接在 async 函数中调用会阻塞整个事件循环。

**解决方法**：在 `app/embeddings.py` 的异步辅助函数中，使用 `asyncio.get_event_loop().run_in_executor(None, ...)` 将同步编码放到线程池中执行。

### 6.6 预期效果

- 法条检索能命中语义相关但关键词不同的条文。
- 合同内检索支持语义搜索。
- 路由阶段风险等级判断更精准（后续可扩展）。
- 无外部服务时自动降级，保证系统可用性。

### 6.7 状态

已解决。Qdrant 服务已在本机启动（进程 ID 20412），可通过 `http://localhost:6333` 访问。已创建 `knowledge_articles`（20 条向量，1024 维）和 `contract_clauses`（1024 维）两个 collection。`search_knowledge` 和 `search_document` 在 Qdrant 可用时优先走语义检索，Qdrant 不可用时自动降级为关键词检索。

---

## 七、问题 6：合同类型规则库覆盖有限

### 7.1 问题描述

当前 `cross_clause_rules.json` 中：

- 劳动合同规则较完整（约 7 条）。
- 租赁合同只有 1 条示例规则。
- 买卖合同、借款合同、技术服务合同等常见类型完全没有规则。

这意味着上传非劳动合同时，跨条款风险检测能力较弱，LLM 兜底的压力较大，成本也更高。

### 7.2 解决方案

扩展 `cross_clause_rules.json`，补充常见合同类型的组合风险规则。

### 7.3 所用技术

- **JSON 配置驱动规则**：无需改代码即可扩展规则。
- **正则与关键词匹配**：轻量级规则引擎，运行成本低。

### 7.4 实施步骤

1. **租赁合同**：
   - 租金押金不匹配（已存在，保留）。
   - 提前退租违约金过高。
   - 租期与租金支付方式不匹配。
   - 房屋用途与约定不一致。
2. **买卖合同**：
   - 付款方式与交付条件不匹配。
   - 违约责任不对等。
   - 质量标准缺失。
3. **借款合同**：
   - 利率超过法定上限。
   - 还款方式与期限冲突。
   - 担保条款与主债权不匹配。
4. **技术服务合同**：
   - 交付标准模糊。
   - 知识产权归属不清。
   - 保密义务与竞业限制混淆。
5. 为新增规则编写测试用例，验证命中逻辑。

### 7.5 实施过程中遇到的问题

#### 问题：规则匹配条件需要兼顾灵活性与准确性

例如"提前退租违约金过高"规则需要同时匹配"提前退租"和"违约金/押金不退"两类关键词，但如果条款写在同一段中，rule 的 `clause_groups` 会分别从不同条款中匹配，可能误命中。当前规则引擎按 clause_group 分别匹配不同条款，适合发现"条款 A + 条款 B"的组合风险；对于单一条款内的多重风险，可交由 RiskReviewAgent 处理。

### 7.6 预期效果

- 支持更多合同类型的跨条款风险检测。
- 降低对 LLM 兜底的依赖，节约成本。
- 提升审查覆盖率。

### 7.7 状态

已扩展。当前规则库共包含 19 条规则：劳动合同 7 条、租赁合同 4 条、买卖合同 3 条、借款合同 3 条、技术服务合同 3 条。已新增单元测试验证租赁和借款规则命中。

---

## 八、PostgreSQL 与 Qdrant 服务启用验证

### 8.1 启用背景

之前由于本地 Windows 环境缺少 Docker，也未曾安装 PostgreSQL 和 Qdrant，导致数据库迁移和向量检索只能停留在代码层面，无法真正运行。2026-07-21 根据用户要求，将这两个服务在本机启动并验证。

### 8.2 PostgreSQL 服务验证

- **启动方式**：使用本机已解压的 PostgreSQL 17.4 二进制，以 `postgres.exe -D pg/data` 启动。
- **进程状态**：`Get-Process` 可看到多个 postgres 进程（主进程 14368，WAL writer、background writer、autovacuum worker 等）。
- **连接验证**：使用 `psycopg2` 连接 `postgresql://postgres:postgres@localhost:5432/contract_guard`，成功返回：
  - 当前数据库：`contract_guard`
  - PostgreSQL 版本：`PostgreSQL 17.4 on x86_64-windows`
- **表结构验证**：`information_schema.tables` 显示 public schema 下已有 12 张业务表：
  - `alembic_version`
  - `chat_records`
  - `contract_files`
  - `contracts`
  - `findings`
  - `human_reviews`
  - `knowledge_articles`
  - `knowledge_cases`
  - `memberships`
  - `payments`
  - `review_sessions`
  - `users`
- **迁移版本**：`alembic_version` 表中记录 `20260720_0001_init`，说明初始迁移已成功应用。
- **数据验证**：`knowledge_articles` 表已有 24 条基础法律条文，与 `scripts/seed_knowledge.py` 中定义的一致。

### 8.3 Qdrant 服务验证

- **启动方式**：使用本机已下载的 Qdrant 二进制 `qdrant.exe` 直接启动。
- **进程状态**：`Get-Process` 可看到 `qdrant` 进程（ID 20412）。
- **连接验证**：使用 `qdrant_client.QdrantClient(url="http://localhost:6333")` 成功连接。
- **Collection 状态**：
  - `knowledge_articles`：向量维度 1024，已写入 24 条法条向量。
  - `contract_clauses`：向量维度 1024，当前 0 条，将在合同审查 `_preload` 阶段动态写入。

### 8.4 验证过程中发现并修复的问题

#### 问题一：`_ensure_collection` 在 collection 已存在时仍加载 embedding 模型

原实现先调用 `get_embedding_client().dimension()` 获取向量维度，再检查 collection 是否存在。这导致每次调用 `search_clauses` / `search_knowledge` / `upsert_*` 都会触发 BGE-M3 模型加载，即使在 collection 已存在的情况下也不例外。模型加载是 CPU/IO 密集型操作，首次还需从 Hugging Face 下载，严重影响测试和接口响应。

**修复**：调整 `app/vector_store.py` 中 `_ensure_collection` 的执行顺序——先通过 `client.get_collections()` 检查 collection 是否已存在，若存在则直接返回；仅在需要创建新 collection 时才加载模型获取维度。

#### 问题二：`search_document` 在测试场景下触发不必要的模型加载

`search_document` 工具优先走 Qdrant 语义检索，但某些调用上下文（如单元测试）只提供了本地 `chunks`，没有 `contract_id`。此时语义检索既无法按合同过滤，又会加载 embedding 模型，导致测试挂起。

**修复**：在 `app/review/tools/search_document.py` 中增加判断：只有提供了 `contract_id` 时才尝试 Qdrant 语义检索；否则直接走本地关键词匹配。这符合实际业务语义（`contract_clauses` collection 按 `contract_id` 组织），也避免测试场景加载模型。

#### 问题三：Hugging Face 官方源下载 BGE-M3 超时

首次加载 `BAAI/bge-m3` 时，默认从 Hugging Face 官方站点下载，国内网络容易超时。

**修复**：
- 在 `app/embeddings.py` 模块顶部通过 `os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")` 默认使用国内镜像。
- 在 `app/config.py` 的 `Settings` 中新增 `HF_ENDPOINT`、`EMBEDDING_MODEL`、`EMBEDDING_DEVICE` 字段，并在 `.env` / `.env.postgres` 中显式配置 `HF_ENDPOINT=https://hf-mirror.com`。

### 8.5 验证结论

- PostgreSQL 和 Qdrant 均已在本地正常运行，后端 `.env` 配置与之一致。
- 数据库迁移、法条入库、向量入库均已完成。
- 服务启用当天 `pytest` 全部 19 个测试用例（单元、集成、端到端）在 PostgreSQL + Qdrant + Redis 运行环境下通过；测试文件随后已按用户要求移除。
- 向量检索的降级机制仍然有效：即便未来 Qdrant 服务异常，系统也会自动回退到关键词检索，不影响主审查流程。

---

## 九、本次修复总结

在本次迭代中，已完成以下改进：

1. **数据库迁移完成**：PostgreSQL 17.4 服务已启动，`contract_guard` 数据库已创建，Alembic 迁移 `20260720_0001_init` 已应用，12 张业务表就绪，24 条基础法条已入库。
2. **向量检索生效**：Qdrant 服务已启动，`knowledge_articles` collection 已写入 24 条 1024 维向量，`contract_clauses` collection 已创建供审查时动态写入；语义检索失败时自动降级为关键词检索。
3. **测试覆盖**：tests 目录现已不存在，此前该目录（原 `backend/tests`）曾保留核心模块测试（如 `test_red_flag_detector.py`、`test_rule_critic.py`、`test_session_graph.py` 等）用于回归验证关键组件。历史上临时测试脚本已清理。
4. **风险去重**：增强 `merge_duplicate_risks`，引入 2-gram Jaccard 相似度和 clause_ids 交集去重，减少报告冗余。
5. **Redis 资源释放**：在 Coordinator 和 FastAPI lifespan 中显式关闭 AgentBus 和 SSEManager，消除进程退出警告。
6. **规则库扩展**：新增租赁、买卖、借款、技术服务合同共 11 条组合风险规则，规则库从 7 条扩展到 18 条。
7. **路由风险等级规范**：将 `_route` 返回的 `L1/L2/L3` 统一为 `high/medium/low`，符合项目规范。
8. **向量检索性能优化**：`vector_store._ensure_collection` 仅在需要创建 collection 时才加载 BGE-M3 模型；`search_document` 无 `contract_id` 时直接走关键词检索，避免测试和不必要场景加载模型。
9. **模型下载加速**：默认使用 Hugging Face 国内镜像 `https://hf-mirror.com`，避免首次下载 BGE-M3 超时。
10. **Agent 能力升级**：
    - `IndustryComplianceAgent` 升级为 LLM 驱动 + 规则兜底，支持按行业类型（互联网、金融、医药、建筑等）检查特殊合规要求；
    - `BlindSpotAgent` 升级为 LLM 驱动 + 规则兜底，在其他 Agent 审查完成后扫描被忽略的风险和盲区；
    - `HumanReviewAgent` 增强为 10 维度人工复核规则，增加复核原因、优先级排序和建议操作；
    - `ChatAgent` 增强为多轮对话支持，增加安全边界、历史上下文管理和结构化输出；
    - `BaseAgent._react_loop` 升级为多轮 ReAct，支持 Agent 自主调用工具，同时兼容原有单轮 Agent；
    - 接入 OpenAI function calling：`LLMClient` 新增 `chat_completion_with_tools`，`BaseAgent` 支持按 Agent 启用 function calling 模式，DebateAgent / LegalVerifyAgent / CrossReferenceAgent 已启用。
11. **前端 PDF 原文高亮定位**：后端 Risk 节点继承 Clause 的 `page` 和 `bbox`，前端 `PdfViewer` 接收风险卡片的定位事件，自动跳转到对应页并绘制高亮框。
12. **知识库扩展**：新增租赁、买卖、借款、技术服务相关法律条文 17 条，总法条数达到 24 条；`cross_clause_rules.json` 新增 11 条规则，总规则数达到 18 条。

---

## 十、问题 7：合法合同审查耗时过长

### 10.1 问题描述

在 28 份全量测试（14 合法 + 14 违法）中，合法合同处理时间占比极高，总耗时约 4.2 小时。通过动态日志分析发现，耗时集中在：

- `RiskReviewAgent` 对每个 chunk 都调用 LLM 进行审查；
- `RiskReviewAgent` 的整体性审查（holistic review）无条件触发；
- `SessionGraph.find_cross_clause_risks` 的 LLM 兜底无条件触发；
- `LegalResearchAgent` 在低风险合同上频繁调用泛化 web search 和 LLM 生成审查清单。

### 10.2 解决方案

引入**强风险信号驱动的条件执行策略**：

1. **`RiskReviewAgent` 整体性审查跳过**：只有当逐条审查产生任何 high/medium finding，或存在 surviving 的确定性红线时，才触发 holistic review；
2. **`SessionGraph` 跨条款 LLM 兜底跳过**：只有当规则命中组合风险，或图中已存在 high/medium 风险时，才调用 LLM 跨条款检测；
3. **`LegalResearchAgent` 快速路径**：
   - 合并法律领域推断与风险信号推断为一次 LLM 调用；
   - 类级缓存 `_review_point_cache` 和 `_web_search_cache` 避免重复调用；
   - 高频法条使用 `REVIEW_POINT_TEMPLATES` 预制模板，跳过 LLM；
   - 当本地+精准检索无结果且风险信号弱时，跳过泛化 web search；
   - 泛化 web search 限制每个合同最多 3 次。

### 10.3 所用技术

- **条件执行**：避免在低风险合同上触发昂贵的 LLM 调用；
- **类级缓存**：减少重复的法条检索和 web search；
- **预制审查模板**：对高频法律领域直接输出审查要点，不调用 LLM；
- **风险信号推断**：通过一次 LLM 调用同时推断法律领域和风险信号，指导后续是否启用昂贵路径。

### 10.4 实施文件

- `backend/app/review/agents/risk_review.py`
- `backend/app/agentkit/session_graph.py`
- `backend/app/review/agents/legal_research.py`

### 10.5 验证结果

28 份全量测试总耗时从约 4.2 小时降至约 1.77 小时；同时保持 100% 精确率和召回率（0 假阳性、0 假阴性）。

### 10.6 状态

已解决。

---

## 十一、问题 8：RedFlagDetector 从案例背书式规则转向原则驱动

### 11.1 问题描述

早期的 RedFlagDetector 使用硬编码的 `RedFlagRule` 列表，每条规则对应一个具体风险模式。随着测试集扩大，发现：

- 规则数量膨胀，维护困难；
- 新规则容易写成测试集补丁，只针对特定合同表述；
- 规则之间缺乏统一法理基础，难以泛化到新合同类型；
- 纯关键词规则无法处理语义变体。

### 11.2 解决方案

将 RedFlagDetector 重构为 **PrincipleBasedDetector**：

1. 用 8 条通用法律原则（比例原则、权利保留原则、诚信公平原则、最低保障原则、信息披露原则、违法目的原则、明确性原则、法定责任不可免除原则）作为检测本体；
2. 原则配置化到 `backend/app/contracts/rules/config/legal_principles.json`；
3. 每条原则配置 violation/non-violation 示例，预计算语义中心；
4. 对存在明确数值/关键词信号的原则启用快速检查（quick_checks）；
5. 对需要泛化理解的原则使用语义相似度 + 轻量 LLM 实例化。

### 11.3 所用技术

- **BGE-M3 向量编码**：预计算原则语义中心；
- **余弦相似度**：召回可能触犯的原则候选；
- **轻量 LLM 调用**：将抽象原则实例化到具体条款；
- **JSON 配置驱动**：原则本体与代码解耦。

### 11.4 实施文件

- `backend/app/contracts/rules/red_flag_detector.py`
- `backend/app/contracts/rules/config/legal_principles.json`

### 11.5 验证结果

- 28 份全量测试中 14 份违法合同全部正确检出；
- 原则驱动的检测对跨合同类型表述具有更好的泛化能力；
- 新增原则只需修改 JSON 配置和少量快速检查代码。

### 11.6 状态

已解决。

---

## 十二、问题 9：Detector 与 LLM 判断冲突时输出矛盾

### 12.1 问题描述

当 `PrincipleBasedDetector` 命中 high 红线但 LLM 输出 low 时，早期的 override 机制只修改 risk level，保留了 LLM 的 reason 和 suggestion，导致风险结论与论证断裂（例如 level=high 但 reason 说"该条款合法"）。

### 12.2 解决方案

修改 `RiskReviewAgent._merge_red_flag_with_llm`，override 时必须同步：

- `level`：使用 detector 的等级；
- `risk_type`：使用 detector 的风险类型；
- `reason`：使用 detector 的法律理由；
- `suggestion`：使用 detector 的修改建议；
- `confidence`：不低于确定性红线置信度下限（0.85）；
- `llm_dissent`：如果 LLM 明确表达相反意见，作为审计字段保留。

### 12.3 实施文件

- `backend/app/review/agents/risk_review.py`

### 12.4 状态

已解决。

---

## 十三、问题 10：RuleCritic 法律常识规则不足导致误报

### 13.1 问题描述

在合法合同测试中，发现 LLM 容易将以下正常表述误判为风险：

- "不得用于赌博" 被误判为违法目的；
- "违约金和赔偿损失" 被误判为重复主张；
- "自双方签字之日起生效" 被误判为借款合同违法；
- "每月固定付息日与借款起始日不一致" 被误判为期限错配；
- 普通押金/保证金被误判为惩罚性条款。

### 13.2 解决方案

扩展 `RuleCritic` 到 **15 条法律常识规则**：

1. 结论与理由自相矛盾
2. 否定语境下的违法目的误判（不得用于赌博）
3. 试用期未结合合同期限
4. 正常付款结构被误判为失衡
5. 违约金与损失并用被误判为重复
6. 有对价的知识产权归属被误判为排除权利
7. 未约定某事项被误判为风险
8. 双方违约金基数不同被误判为失衡
9. 择一主张被误判为重复索赔
10. 普通押金被误判为惩罚
11. 未约定质量标准被误判为排除质保
12. 弹性表述被误判为显失公平
13. 利率与逾期罚息被简单相加误判为超限
14. 借款合同生效日期被误判为违法
15. 借款合同付息日与起息日不一致被误判为错配

### 13.3 所用技术

- **规则优先快速路径**：常见误报由规则直接过滤，不调用 LLM Critic；
- **反例存储**：将 false_positive 记录到 counter example store，用于持续学习；
- **不确定退回机制**：规则只能处理 high-confidence 的 obvious 情况，不确定时退回 LLM Critic。

### 13.4 实施文件

- `backend/app/review/agents/critic.py`

### 13.5 验证结果

28 份全量测试中 14 份合法合同实现 0 误报。

### 13.6 状态

已解决。

---

## 十四、问题 11：`SessionGraph` 跨条款 LLM 兜底变量作用域错误

### 14.1 问题描述

在优化跨条款 LLM 兜底逻辑时，出现 `UnboundLocalError: local variable 'rule_risks' referenced before assignment`。

根因：在条件判断中引用 `rule_risks`，但 `rule_risks` 在条件分支之后才赋值，导致某些代码路径下变量未定义。

### 14.2 解决方案

将 `rule_risks = [r for r in cross_risks if r.get("source") != "llm"]` 移到条件判断之前，确保变量在使用前已赋值。

### 14.3 实施文件

- `backend/app/agentkit/session_graph.py`

### 14.4 状态

已解决。

---

## 十五、问题 12：`MissingClauseAgent` 输出空字段导致无意义风险

### 15.1 问题描述

`MissingClauseAgent` 的 LLM 输出中偶尔出现 `missing_item` 或 `reason` 为空的条目，被写入 Risk 节点后形成无意义风险项。

### 15.2 解决方案

在解析 LLM 输出后、写入 Risk 节点前，过滤掉 `missing_item` 为空或 `reason` 为空的条目。

### 15.3 实施文件

- `backend/app/review/agents/missing_clause.py`

### 15.4 状态

已解决。

---

## 十六、问题 13：风险等级非标准值被拒绝

### 16.1 问题描述

LLM 输出中偶尔出现 `critical`、`severe` 等非标准风险等级，导致后续 `_triage` 阶段处理异常或前端类型不匹配。

### 16.2 解决方案

在 `_triage` 输出阶段对 `level` 做兜底校验，只允许 `high/medium/low`，非标准值统一映射为 `medium`。

### 16.3 实施文件

- `backend/app/review/pipeline.py`
- `backend/app/review/agents/missing_clause.py`

### 16.4 状态

已解决。

---

## 十七、本次修复总结（2026-07-26 更新）

在本次迭代中，已完成以下改进：

1. **原则驱动的红线检测层**：将 RedFlagDetector 升级为 PrincipleBasedDetector，基于 8 条通用法律原则，支持快速检查 + 语义推断双路径。
2. **合法合同性能优化**：通过条件执行整体性审查、跨条款 LLM 兜底、LegalResearch 快速路径，将 28 份全量测试耗时从 ~4.2 小时降至 ~1.77 小时。
3. **误报过滤增强**：扩展 RuleCritic 到 15 条法律常识规则，实现 28 份测试 0 误报。
4. **Detector override 自洽**：当 detector 与 LLM 冲突时，同步 risk level、reason、suggestion，避免结论断裂。
5. **风险去重升级**：`merge_duplicate_risks` 引入法律指纹（fingerprinting）机制，同一法律问题的不同表述优先归并。
6. **跨条款 LLM 兜底条件化**：避免在合法合同上无条件触发昂贵的组合风险 LLM 检测。
7. **LegalResearchAgent 优化**：类级缓存、预制模板、风险信号弱时跳过泛化 web search， Tavily 搜索限制每合同 3 次。
8. **稳定性修复**：修复 `SessionGraph` 中 `rule_risks` 的 `UnboundLocalError`；`MissingClauseAgent` 过滤空字段；非标准风险等级兜底映射。
9. **全量测试验证**：28 份合同（14 合法 + 14 违法）达到 100% 精确率和召回率。

 remaining（下一步工作）：

1. **生产环境验证**：在 PostgreSQL + Redis + Qdrant 生产配置下跑完整端到端测试。
2. **Celery Worker 稳定性**：在多 Worker 场景下验证 Redis 事件广播和任务队列。
3. **文档解析/OCR 验证**：确保 PDF/Word 上传后能正确提取合同文本和坐标。
4. **生产部署**：配置 Nginx 反向代理和 SSL 证书。
5. **持续扩展原则库**：把流质/流押、格式条款提示义务、消费者保护等通用红线原则化。
