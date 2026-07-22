"""add ops_overview_rollup physical preagg table

Revision ID: d8e9f0a1235
Revises: c7d8e9f0124
Create Date: 2026-07-22 15:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1235"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0124"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_overview_rollup",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("scope_key", sa.String(length=64), nullable=False, comment="聚合作用域 platform / tenants:md5"),
        sa.Column("scope_kind", sa.String(length=20), server_default="platform", nullable=False, comment="platform|tenants"),
        sa.Column("payload_json", sa.JSON(), nullable=False, comment="重聚合 JSON 载荷"),
        sa.Column("platform_window_days", sa.Integer(), server_default="7", nullable=False, comment="平台统计窗口天数"),
        sa.Column("cost_window_days", sa.Integer(), server_default="30", nullable=False, comment="费用/累计窗口天数"),
        sa.Column("computed_at", sa.DateTime(), nullable=False, comment="最近计算时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", name="uk_ops_overview_rollup_scope"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("ops_overview_rollup")
