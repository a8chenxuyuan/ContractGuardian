"""Alembic 环境配置。

负责从 .env 读取数据库 URL，并配置 SQLAlchemy 元数据，
让 Alembic 能够根据 app.models 自动生成迁移脚本。
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 加载项目配置，获取 SYNC_DATABASE_URL
from app.core.config import get_settings
from app.core.database import Base
from app.models import *  # noqa: F403  导入所有模型，让 Base.metadata 包含它们

settings = get_settings()

# Alembic 配置对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据：包含所有 SQLAlchemy 模型
target_metadata = Base.metadata

# 使用同步 PostgreSQL URL 进行迁移
config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本，不直接连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
