"""repair empty monitor_keywords_json from monitor_keyword

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-06-30 20:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            update geo_brand_keyword_group
            set monitor_keywords_json = json_array(trim(monitor_keyword))
            where json_length(monitor_keywords_json) = 0
              and monitor_keyword is not null
              and trim(monitor_keyword) <> ''
            """
        )
    )


def downgrade() -> None:
    pass
