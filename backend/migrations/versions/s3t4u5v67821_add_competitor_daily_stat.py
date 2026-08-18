"""add geo_monitor_competitor_daily_stat for B3+ competitor KPI daily rollup

Revision ID: s3t4u5v67821
Revises: p0q1r2s34518
Create Date: 2026-08-17

2026-08-17 - 生产 head 仍停在 p0；本迁移只上 B3+，不挂未进 git 的 q1/r2
2026-08-18 - 生产已 stamp 本 revision 且表可能已在；upgrade 按表存在跳过，勿改 down_revision
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "s3t4u5v67821"
# 2026-08-17 - 生产仅 p0；勿依赖本地未上线的 q1→r2 链
down_revision = "p0q1r2s34518"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("geo_monitor_competitor_daily_stat"):
        return
    op.create_table(
        "geo_monitor_competitor_daily_stat",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("competitor_name", sa.String(length=100), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column(
            "platform",
            sa.String(length=50, collation="utf8mb4_0900_ai_ci"),
            nullable=False,
        ),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mentioned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top3_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_version", sa.String(length=32), nullable=False, server_default="b3plus-a2-v1"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["competitor_id"], ["geo_brand_competitor.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "competitor_id",
            "stat_date",
            "platform",
            name="uk_geo_monitor_competitor_daily_stat",
        ),
    )
    op.create_index(
        "ix_geo_monitor_competitor_daily_stat_tenant_id",
        "geo_monitor_competitor_daily_stat",
        ["tenant_id"],
    )
    op.create_index(
        "ix_geo_monitor_competitor_daily_stat_competitor_id",
        "geo_monitor_competitor_daily_stat",
        ["competitor_id"],
    )
    op.create_index(
        "ix_geo_monitor_competitor_daily_stat_stat_date",
        "geo_monitor_competitor_daily_stat",
        ["stat_date"],
    )
    op.create_index(
        "ix_geo_monitor_competitor_daily_stat_platform",
        "geo_monitor_competitor_daily_stat",
        ["platform"],
    )


def downgrade() -> None:
    op.drop_table("geo_monitor_competitor_daily_stat")
