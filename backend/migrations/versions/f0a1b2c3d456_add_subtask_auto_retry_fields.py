"""add geo_monitor_subtask auto retry fields

Revision ID: f0a1b2c3d456
Revises: e9f0a1b2c345
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f0a1b2c3d456"
down_revision = "e9f0a1b2c345"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_monitor_subtask",
        sa.Column("auto_retry_count", sa.Integer(), server_default="0", nullable=False, comment="自动重试已发起次数"),
    )
    op.add_column(
        "geo_monitor_subtask",
        sa.Column("auto_retry_task_id", sa.String(length=64), nullable=True, comment="自动重试产生的模力主任务ID"),
    )
    op.add_column(
        "geo_monitor_subtask",
        sa.Column("auto_retry_status", sa.String(length=32), nullable=True, comment="自动重试状态 pending/succeeded/failed"),
    )
    op.create_index("ix_geo_monitor_subtask_auto_retry_task_id", "geo_monitor_subtask", ["auto_retry_task_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_monitor_subtask_auto_retry_task_id", table_name="geo_monitor_subtask")
    op.drop_column("geo_monitor_subtask", "auto_retry_status")
    op.drop_column("geo_monitor_subtask", "auto_retry_task_id")
    op.drop_column("geo_monitor_subtask", "auto_retry_count")
