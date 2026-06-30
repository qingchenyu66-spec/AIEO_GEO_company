"""add defaults for keyword group json/name columns

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-06-30 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            update geo_brand_keyword_group
            set monitor_keywords_json = json_array(trim(monitor_keyword))
            where monitor_keywords_json is null
              and monitor_keyword is not null
              and trim(monitor_keyword) <> ''
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update geo_brand_keyword_group
            set monitor_keywords_json = json_array()
            where monitor_keywords_json is null
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update geo_brand_keyword_group
            set name = concat('词组 ', id)
            where name is null or trim(name) = ''
            """
        )
    )
    op.alter_column(
        "geo_brand_keyword_group",
        "monitor_keywords_json",
        existing_type=sa.JSON(),
        server_default=sa.text("(JSON_ARRAY())"),
        nullable=False,
    )
    op.alter_column(
        "geo_brand_keyword_group",
        "exposure_terms_json",
        existing_type=sa.JSON(),
        server_default=sa.text("(JSON_ARRAY())"),
        nullable=False,
    )
    op.alter_column(
        "geo_brand_keyword_group",
        "name",
        existing_type=sa.String(length=100),
        server_default="词组",
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "geo_brand_keyword_group",
        "name",
        existing_type=sa.String(length=100),
        server_default=None,
        nullable=False,
    )
    op.alter_column(
        "geo_brand_keyword_group",
        "exposure_terms_json",
        existing_type=sa.JSON(),
        server_default=None,
        nullable=False,
    )
    op.alter_column(
        "geo_brand_keyword_group",
        "monitor_keywords_json",
        existing_type=sa.JSON(),
        server_default=None,
        nullable=False,
    )
