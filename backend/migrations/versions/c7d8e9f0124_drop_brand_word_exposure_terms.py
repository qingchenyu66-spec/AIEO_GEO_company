"""drop exposure_terms from geo_brand_word_group

Revision ID: c7d8e9f0124
Revises: b6c7d8e0123
Create Date: 2026-07-21 13:50:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0124"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e0123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("geo_brand_word_group", "exposure_terms_json")


def downgrade() -> None:
    op.add_column(
        "geo_brand_word_group",
        sa.Column(
            "exposure_terms_json",
            sa.JSON(),
            server_default=sa.text("(JSON_ARRAY())"),
            nullable=False,
            comment="露出词JSON",
        ),
    )
