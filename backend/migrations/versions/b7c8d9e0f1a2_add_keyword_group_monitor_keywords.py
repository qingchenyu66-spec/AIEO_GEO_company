"""add monitor_keywords_json to brand keyword groups

Revision ID: b7c8d9e0f1a2
Revises: fc6da1cf9fa9
Create Date: 2026-06-30 14:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "fc6da1cf9fa9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("geo_brand_keyword_group")}
    if "monitor_keywords_json" not in columns:
        op.add_column(
            "geo_brand_keyword_group",
            sa.Column(
                "monitor_keywords_json",
                sa.JSON(),
                nullable=True,
                comment="监测关键词列表JSON",
            ),
        )

    bind.execute(
        sa.text(
            """
            update geo_brand_keyword_group
            set monitor_keywords_json = json_array(trim(monitor_keyword))
            where deleted = 0
              and monitor_keywords_json is null
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
    op.alter_column(
        "geo_brand_keyword_group",
        "monitor_keywords_json",
        existing_type=sa.JSON(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("geo_brand_keyword_group", "monitor_keywords_json")
