"""add geo_monitor_source_daily table

Revision ID: g1h2i3j4k567
Revises: f0a1b2c3d456
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g1h2i3j4k567"
down_revision = "f0a1b2c3d456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_monitor_source_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("config_fp", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("branded_json", sa.JSON(), nullable=False),
        sa.Column("all_json", sa.JSON(), nullable=False),
        sa.Column("daily_branded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_by_platform_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stat_date", name="uk_geo_monitor_source_daily"),
    )
    op.create_index("ix_geo_monitor_source_daily_tenant_id", "geo_monitor_source_daily", ["tenant_id"])
    op.create_index("ix_geo_monitor_source_daily_stat_date", "geo_monitor_source_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_index("ix_geo_monitor_source_daily_stat_date", table_name="geo_monitor_source_daily")
    op.drop_index("ix_geo_monitor_source_daily_tenant_id", table_name="geo_monitor_source_daily")
    op.drop_table("geo_monitor_source_daily")
