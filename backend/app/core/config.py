from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """项目全局配置。

    所有敏感配置建议通过环境变量注入，开发时可以使用 .env 文件。
    """

    # 应用
    APP_NAME: str = "ContractGuard"
    DEBUG: bool = True

    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/contract_guard"
    SYNC_DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/contract_guard"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # 安全
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天
    ALGORITHM: str = "HS256"

    # 文件存储
    UPLOAD_DIR: str = "./uploads"
    REPORT_DIR: str = "./reports"
    MAX_UPLOAD_SIZE: int = 20 * 1024 * 1024  # 20MB

    # 会员与配额（免费用户限制，会员无限制）
    FREE_PAGE_LIMIT: int = 20  # 免费用户单合同页数上限
    FREE_MONTHLY_REVIEWS: int = 3  # 免费用户每月审查次数
    MEMBERSHIP_PRICE_MONTHLY: float = 29.9  # 月度会员价格（元）
    MEMBERSHIP_PRICE_YEARLY: float = 299.0  # 年度会员价格（元）

    # 数据库
    AUTO_CREATE_TABLES: bool = True  # 开发环境自动建表；生产环境建议用 Alembic 并设为 False

    # Embedding / 向量模型
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_MAX_LENGTH: int = 1024  # 双路编码最大 token 数（子块 ≤450 字足够）
    HF_ENDPOINT: str | None = "https://hf-mirror.com"

    # 检索底座（M1：父子切块 + 双路召回 + 重排）
    RETRIEVAL_SPARSE_ENABLED: bool = True  # sparse 词法召回；FlagEmbedding 缺失时自动降级
    RETRIEVAL_PREFETCH_LIMIT: int = 40  # 每路召回候选数
    RETRIEVAL_CANDIDATE_LIMIT: int = 20  # RRF 融合去重后参与重排的父块数
    RETRIEVAL_RERANK_ENABLED: bool = True
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_DEVICE: str = "cpu"
    CONTEXT_ENHANCE_ENABLED: bool = True  # 子块定位句 LLM 增强；关闭则机械拼接标题+章节

    # 上下文装配层（agentkit/context/，协议 docs/protocols/context_assembly.md）
    CONTEXT_MAX_TOKENS: int = 32000  # 单次装配总预算（换模型只改配置）
    CONTEXT_LAYER_LIMITS: dict[str, int] = {}  # 层配额覆盖（空字典=用代码默认），键见 budget.py

    # 工具权限三态（M3'，协议 docs/protocols/plugin_registry.md §2）：
    # 工具名 -> allow/approve/deny；空字典=全部默认 allow
    TOOL_PERMISSION_OVERRIDES: dict[str, str] = {}

    # 引擎门面状态存储：memory = 单进程内存；redis = 多实例共享（含 TTL 秒数）
    STATE_STORE: str = "memory"
    STATE_STORE_TTL: int = 7 * 86400

    # HITL 真审批（默认关 = approve 工具等同放行仅记审计事件，保持现网行为）
    HITL_ENABLED: bool = False
    APPROVAL_TIMEOUT: int = 300  # 秒，超时按拒绝处理（宁可拒绝不放行）

    # CRAG（M2：检索质量自纠错）
    CRAG_ENABLED: bool = True
    CRAG_SCORE_THRESHOLD: float = 0.45  # 检索最高分低于该值触发 query 改写重检索

    # LLM（Agent 模块使用，后端只做透传或兜底配置）
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str = "qwen-turbo"
    LLM_VL_MODEL: str = "qwen3.8-omni-flash"  # 视觉模型：图片合同 OCR 提取，与文本模型可不同端点
    LLM_TIMEOUT: int = 60  # 单次 LLM 调用超时（秒），防止模型服务无响应拖死审查任务

    # 任务治理（D4）：单次审查的时长/重试上限，可按环境调整
    REVIEW_SOFT_TIME_LIMIT: int = 600  # 单次审查软超时（秒）；Windows 本地不生效，Linux 生产生效
    REVIEW_MAX_RETRIES: int = 3  # 失败重试上限（仅超时/服务商类错误重试，指数退避）
    AGENT_MAX_TURNS: int = 5  # Agent ReAct 循环迭代上限，防止无限循环 token 爆掉

    # Tavily 联网搜索（法规原文检索与动态缓存）
    TAVILY_API_KEY: str | None = None
    TAVILY_MAX_RESULTS: int = 5
    TAVILY_SEARCH_DEPTH: str = "advanced"  # basic 或 advanced

    # SMTP 邮件（忘记密码验证码发信；未配置时 forgot-password 返回 503）
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 465
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None  # 邮箱授权码（非登录密码）
    SMTP_FROM: str | None = None  # 发件人显示地址，缺省用 SMTP_USER

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
