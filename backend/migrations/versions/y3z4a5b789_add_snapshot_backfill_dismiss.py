"""add snapshot backfill dismiss columns on geo_monitor_subtask

Revision ID: y3z4a5b789
Revises: x2y3z4a678
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "y3z4a5b789"
down_revision = "x2y3z4a678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_monitor_subtask",
        sa.Column("backfill_dismissed_at", sa.DateTime(), nullable=True, comment="快照补录忽略时间"),
    )
    op.add_column(
        "geo_monitor_subtask",
        sa.Column("backfill_dismissed_by", sa.Integer(), nullable=True, comment="快照补录忽略操作人"),
    )
    op.create_index(
        "ix_geo_monitor_subtask_backfill_dismissed_by",
        "geo_monitor_subtask",
        ["backfill_dismissed_by"],
    )
    op.create_foreign_key(
        "fk_geo_monitor_subtask_backfill_dismissed_by",
        "geo_monitor_subtask",
        "sys_user",
        ["backfill_dismissed_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_geo_monitor_subtask_backfill_dismissed_by", "geo_monitor_subtask", type_="foreignkey")
    op.drop_index("ix_geo_monitor_subtask_backfill_dismissed_by", table_name="geo_monitor_subtask")
    op.drop_column("geo_monitor_subtask", "backfill_dismissed_by")
    op.drop_column("geo_monitor_subtask", "backfill_dismissed_at")
