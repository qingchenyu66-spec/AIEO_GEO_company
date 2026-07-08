"""add geo_report period_key for scheduled report idempotency

Revision ID: q5r6s7t901
Revises: p4q5r6s890
Create Date: 2026-07-08 09:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q5r6s7t901"
down_revision: Union[str, Sequence[str], None] = "p4q5r6s890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_report",
        sa.Column("period_key", sa.String(length=80), nullable=True, comment="周期报告幂等键"),
    )
    op.create_index("ix_geo_report_period_key", "geo_report", ["period_key"], unique=False)
    op.create_index(
        "uk_geo_report_tenant_type_period",
        "geo_report",
        ["tenant_id", "report_type", "period_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uk_geo_report_tenant_type_period", table_name="geo_report")
    op.drop_index("ix_geo_report_period_key", table_name="geo_report")
    op.drop_column("geo_report", "period_key")
