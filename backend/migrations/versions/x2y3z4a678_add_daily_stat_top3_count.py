"""add top3_count to geo_monitor_daily_stat

Revision ID: x2y3z4a678
Revises: w1x2y3z567
Create Date: 2026-07-16

历史行需跑 rebuild_monitor_daily_stats_keys.py --apply 回填 top3_count。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "x2y3z4a678"
down_revision = "w1x2y3z567"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_monitor_daily_stat",
        sa.Column("top3_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("geo_monitor_daily_stat", "top3_count")
