"""add lead diagnosis platforms_json

Revision ID: i3j4k5l6m789
Revises: h2i3j4k5l678
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i3j4k5l6m789"
down_revision = "h2i3j4k5l678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column(
            "platforms_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
            comment="诊断平台码列表；空则提交时回退全量可提交目录（兼容旧单）",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_lead_diagnosis", "platforms_json")
