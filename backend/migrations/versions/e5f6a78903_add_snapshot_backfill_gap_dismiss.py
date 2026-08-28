"""add geo_snapshot_backfill_gap_dismiss for fast batch gap ignore

Revision ID: e5f6a78903
Revises: d4e5f6a78902
Create Date: 2026-08-28 13:30:00.000000

2026-08-28 - 一键忽略慢 - 缺口批量登记，免逐条占位子任务
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a78903"
down_revision: Union[str, Sequence[str], None] = "v7w8x9y01234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_snapshot_backfill_gap_dismiss",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="企业ID"),
        sa.Column("platform", sa.String(length=50), nullable=False, comment="平台编码"),
        sa.Column("prompt", sa.String(length=500), nullable=False, comment="监测词"),
        sa.Column("schedule_window_key", sa.String(length=32), nullable=False, comment="场次键"),
        sa.Column("dismissed_at", sa.DateTime(), nullable=False, comment="忽略时间"),
        sa.Column("dismissed_by", sa.Integer(), nullable=True, comment="操作人"),
        sa.ForeignKeyConstraint(["dismissed_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "platform",
            "prompt",
            "schedule_window_key",
            name="uk_geo_snapshot_backfill_gap_dismiss",
        ),
        comment="快照补录漏跑缺口批量忽略登记",
    )
    op.create_index(
        "ix_geo_snapshot_backfill_gap_dismiss_tenant_window",
        "geo_snapshot_backfill_gap_dismiss",
        ["tenant_id", "schedule_window_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_geo_snapshot_backfill_gap_dismiss_tenant_window", table_name="geo_snapshot_backfill_gap_dismiss")
    op.drop_table("geo_snapshot_backfill_gap_dismiss")
