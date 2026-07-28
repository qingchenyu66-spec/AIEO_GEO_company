"""announcement body_html to MEDIUMTEXT

Revision ID: h2i3j4k5l678
Revises: g1h2i3j4k567
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "h2i3j4k5l678"
down_revision = "g1h2i3j4k567"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 2026-07-28 - 公告粘贴图/长文超 TEXT 64KB - 升 MEDIUMTEXT，配合 schema 放宽
    op.alter_column(
        "geo_announcement",
        "body_html",
        existing_type=sa.Text(),
        type_=mysql.MEDIUMTEXT(),
        existing_nullable=False,
        existing_comment="富文本 HTML",
        comment="富文本 HTML",
    )


def downgrade() -> None:
    op.alter_column(
        "geo_announcement",
        "body_html",
        existing_type=mysql.MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=False,
        existing_comment="富文本 HTML",
        comment="富文本 HTML",
    )
