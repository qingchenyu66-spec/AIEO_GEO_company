"""add name to brand keyword groups

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-06-30 16:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("geo_brand_keyword_group")}
    if "name" not in columns:
        op.add_column(
            "geo_brand_keyword_group",
            sa.Column(
                "name",
                sa.String(length=100),
                nullable=True,
                comment="词组名称",
            ),
        )

    bind.execute(
        sa.text(
            """
            update geo_brand_keyword_group
            set name = concat('词组 ', sort_order + 1)
            where name is null or trim(name) = ''
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
        "name",
        existing_type=sa.String(length=100),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("geo_brand_keyword_group", "name")
