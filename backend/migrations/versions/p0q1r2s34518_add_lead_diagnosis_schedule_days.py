"""add geo_lead_diagnosis.schedule_days for configurable diagnosis span

Revision ID: p0q1r2s34518
Revises: o9p0q1r23417
Create Date: 2026-08-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p0q1r2s34518"
down_revision: Union[str, Sequence[str], None] = "o9p0q1r23417"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 2026-08-04 - 诊断天数写死 3 - 落库可配，默认 3（范围 3–7）
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column(
            "schedule_days",
            sa.Integer(),
            nullable=False,
            server_default="3",
            comment="诊断抓取计划天数，默认3，范围3-7",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_lead_diagnosis", "schedule_days")
