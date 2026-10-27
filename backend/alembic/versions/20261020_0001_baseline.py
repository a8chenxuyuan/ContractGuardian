"""全量基线：按当前 SQLAlchemy 元数据建全部 17 张表。

Revision ID: 20261020_0001_baseline
Revises:
Create Date: 2026-10-20

对全新数据库执行 upgrade 即得完整可运行结构；
现有数据库（结构已就位）用 `alembic stamp head` 标记，不重复建表。
后续结构性变更一律新增 revision（autogenerate 优先），不再回改本文件。
"""
from typing import Sequence, Union

from alembic import op
from app.core.database import Base
from app.models import *  # noqa: F401,F403  导入全部模型注册 metadata

# revision identifiers, used by Alembic.
revision: str = "20261020_0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """按 metadata 全量建表（幂等性由调用方保证：仅在空库执行）。"""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """回滚删除全部业务表（含数据，谨慎执行）。"""
    Base.metadata.drop_all(bind=op.get_bind())
