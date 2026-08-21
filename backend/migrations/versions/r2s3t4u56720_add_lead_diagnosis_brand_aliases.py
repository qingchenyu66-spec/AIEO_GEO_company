"""add geo_lead_diagnosis.brand_aliases_json for optional exposure aliases

Revision ID: r2s3t4u56720
Revises: q1r2s3t45619
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r2s3t4u56720"
down_revision: Union[str, Sequence[str], None] = "q1r2s3t45619"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 2026-08-13 - 售前可选露出词/别名，提交监测与聚合匹配用；空则自动从全称派生
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column(
            "brand_aliases_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
            comment="品牌别名/露出词列表，可选；空则自动从全称派生",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_lead_diagnosis", "brand_aliases_json")
