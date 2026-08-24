"""add geo_monitor_window_snapshot for 7d/30d workspace preagg

Revision ID: t5u6v7w89012
Revises: r2s3t4u56720
Create Date: 2026-08-21

2026-08-21 - 稳定性⑤：常用窗口快照表
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t5u6v7w89012"
down_revision = "r2s3t4u56720"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("geo_monitor_window_snapshot"):
        return
    op.create_table(
        "geo_monitor_window_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("filter_fp", sa.String(length=40), nullable=False, server_default="default"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "kind",
            "window_days",
            "as_of_date",
            "filter_fp",
            name="uk_geo_monitor_window_snapshot",
        ),
    )
    op.create_index(
        "ix_geo_monitor_window_snapshot_tenant_id",
        "geo_monitor_window_snapshot",
        ["tenant_id"],
    )
    op.create_index(
        "ix_geo_monitor_window_snapshot_as_of_date",
        "geo_monitor_window_snapshot",
        ["as_of_date"],
    )


def downgrade() -> None:
    op.drop_table("geo_monitor_window_snapshot")
