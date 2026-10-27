from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

# 异步引擎，供 FastAPI 使用
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    poolclass=NullPool,
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ORM 基类
Base = declarative_base()


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：每次请求获取一个异步数据库会话。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
