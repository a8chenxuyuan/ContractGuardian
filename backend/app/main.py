import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jose import jwt
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.sse import SSEManager
from app.models import ContractTemplate  # noqa: F401  注册进 Base.metadata 供 create_all 建表
from app.models.audit import AuditLog
from app.models.user import User
from app.routers import (
    admin,
    approvals,
    auth,
    calendar,
    chat,
    contracts,
    dashboard,
    knowledge,
    membership,
    notifications,
    review,
    skills,
    templates,
)
from app.seed_templates import seed_preset_templates

settings = get_settings()

# 登录/注册的审计由 auth 路由单独记录，中间件跳过
_AUDIT_SKIP_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register"}

logger = logging.getLogger("contract_guard")

# 启动自检结果（/health 读取），启动后在 lifespan 中填充
health_state: dict = {"status": "ok", "checks": {}}


async def _startup_checks() -> dict[str, bool]:
    """启动自检：必填配置与依赖连通性。缺失只降级（/health 标记 degraded）不硬崩，便于本机开发。"""
    checks: dict[str, bool] = {}
    # 必填配置：LLM 审查与法规联网检索的 Key
    checks["llm_api_key"] = bool(settings.LLM_API_KEY)
    checks["tavily_api_key"] = bool(settings.TAVILY_API_KEY)
    # 数据库连通
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    # Redis 连通
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        try:
            await client.ping()
        finally:
            await (client.aclose() if hasattr(client, "aclose") else client.close())
        checks["redis"] = True
    except Exception:
        checks["redis"] = False
    # Qdrant 连通
    try:
        import httpx

        headers = {"api-key": settings.QDRANT_API_KEY} if settings.QDRANT_API_KEY else None
        async with httpx.AsyncClient(timeout=2.0, headers=headers) as client:
            resp = await client.get(f"{settings.QDRANT_URL.rstrip('/')}/collections")
        checks["qdrant"] = resp.status_code == 200
    except Exception:
        checks["qdrant"] = False
    return checks


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期事件：启动时建表+自检，关闭时释放资源。"""
    # 创建上传目录和报告目录
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.REPORT_DIR, exist_ok=True)

    # 开发环境下自动建表；生产环境或启用 Alembic 时可关闭自动建表
    if settings.AUTO_CREATE_TABLES:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # 幂等播种预置合同范本
    async with AsyncSessionLocal() as session:
        try:
            await seed_preset_templates(session)
        except Exception:
            logger.exception("预置范本播种失败（不影响启动）")

    # 配置缺失/依赖不可用提前拦截：记 ERROR 日志并在 /health 暴露 degraded
    checks = await _startup_checks()
    health_state["checks"] = checks
    health_state["status"] = "ok" if all(checks.values()) else "degraded"
    missing = [name for name, ok in checks.items() if not ok]
    if missing:
        logger.error("启动自检发现异常项: %s（详情见 /health）", ", ".join(missing))
    yield
    # 关闭数据库连接池
    await engine.dispose()
    # 关闭 SSEManager 持有的 Redis 连接，避免进程退出时事件循环已关闭的警告
    await SSEManager().close()


app = FastAPI(
    title=settings.APP_NAME,
    description="合同卫士后端 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：开发时允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全说明：/uploads 与 /reports 曾以公开静态目录挂载，任何人可枚举下载合同文件。
# 现已移除，改为受鉴权接口：
#   - 合同原文件：GET /api/v1/contracts/{id}/file（contracts.py，归属校验）
#   - 审查报告：POST /api/v1/review/{id}/export（review.py，归属校验）

# 注册路由
app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(contracts.router, prefix="/api/v1/contracts", tags=["合同"])
app.include_router(review.router, prefix="/api/v1/review", tags=["审查"])
app.include_router(chat.router, prefix="/api/v1/contracts", tags=["对话"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["管理后台"])
app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["HITL审批"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["通知"])
app.include_router(membership.router, prefix="/api/v1/membership", tags=["会员"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["看板"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["履约日历"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["知识库"])
app.include_router(templates.router, prefix="/api/v1/templates", tags=["模板库"])
app.include_router(skills.router, prefix="/api/v1/skills", tags=["Skills"])


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """审计中间件：记录 API 写操作（登录/注册由 auth 路由单独记录）。"""
    response = await call_next(request)
    path = request.url.path
    if (
        request.method in {"POST", "PUT", "DELETE", "PATCH"}
        and path.startswith("/api/v1")
        and path not in _AUDIT_SKIP_PATHS
        and response.status_code < 400
    ):
        try:
            user_id = None
            email = None
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                payload = jwt.decode(
                    auth_header[7:], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
                )
                sub = payload.get("sub")
                if sub:
                    user_id = int(sub)
            async with AsyncSessionLocal() as session:
                if user_id:
                    email = (
                        await session.execute(select(User.email).where(User.id == user_id))
                    ).scalar_one_or_none()
                session.add(
                    AuditLog(
                        user_id=user_id,
                        email=email,
                        action=request.method,
                        resource=path,
                        ip=request.client.host if request.client else None,
                    )
                )
                await session.commit()
        except Exception:
            # 审计失败不影响主请求
            pass
    return response


@app.get("/health")
async def health_check():
    return health_state


# 托管前端构建产物（如果存在）
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists() and (_frontend_dist / "index.html").exists():
    # 静态资源（JS/CSS/图片）由 StaticFiles 提供；index.html 走下方 SPA 兜底，避免浏览器缓存旧版本
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="frontend_assets")

    # SPA 兜底：未匹配到的路由返回 index.html，并强制禁用缓存
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # API 请求不应走到这里（路由已优先注册）
        index_file = _frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return {"detail": "Not Found"}
