"""add geo_monitor_daily_stat table

Revision ID: h6i7j8k9l012
Revises: g5h6i7j8k901
Create Date: 2026-07-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h6i7j8k9l012"
down_revision: Union[str, None] = "g5h6i7j8k901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_monitor_daily_stat",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mentioned_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rank_sum", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rank_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("citation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stat_date", "platform", name="uk_geo_monitor_daily_stat"),
    )
    op.create_index("ix_geo_monitor_daily_stat_tenant_id", "geo_monitor_daily_stat", ["tenant_id"])
    op.create_index("ix_geo_monitor_daily_stat_stat_date", "geo_monitor_daily_stat", ["stat_date"])
    op.create_index("ix_geo_monitor_daily_stat_platform", "geo_monitor_daily_stat", ["platform"])


def downgrade() -> None:
    op.drop_index("ix_geo_monitor_daily_stat_platform", table_name="geo_monitor_daily_stat")
    op.drop_index("ix_geo_monitor_daily_stat_stat_date", table_name="geo_monitor_daily_stat")
    op.drop_index("ix_geo_monitor_daily_stat_tenant_id", table_name="geo_monitor_daily_stat")
    op.drop_table("geo_monitor_daily_stat")
