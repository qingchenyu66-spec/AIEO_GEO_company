"""replace single region_code with region_codes_json on brand and lead diagnosis

Revision ID: o3p4q5r789
Revises: n2o3p4q678
Create Date: 2026-07-07 11:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o3p4q5r789"
down_revision: Union[str, Sequence[str], None] = "n2o3p4q678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_brand_asset",
        sa.Column("region_codes_json", sa.JSON(), nullable=True, comment="监测地区编码列表，空数组代表全部区域"),
    )
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column("region_codes_json", sa.JSON(), nullable=True, comment="监测地区编码列表，空数组代表全部区域"),
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE geo_brand_asset
            SET region_codes_json = JSON_ARRAY(region_code)
            WHERE region_code IS NOT NULL AND region_code <> ''
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE geo_lead_diagnosis
            SET region_codes_json = JSON_ARRAY(region_code)
            WHERE region_code IS NOT NULL AND region_code <> ''
            """
        )
    )
    bind.execute(sa.text("UPDATE geo_brand_asset SET region_codes_json = JSON_ARRAY() WHERE region_codes_json IS NULL"))
    bind.execute(sa.text("UPDATE geo_lead_diagnosis SET region_codes_json = JSON_ARRAY() WHERE region_codes_json IS NULL"))
    op.alter_column("geo_brand_asset", "region_codes_json", existing_type=sa.JSON(), nullable=False)
    op.alter_column("geo_lead_diagnosis", "region_codes_json", existing_type=sa.JSON(), nullable=False)
    op.drop_column("geo_brand_asset", "region_code")
    op.drop_column("geo_lead_diagnosis", "region_code")


def downgrade() -> None:
    op.add_column(
        "geo_brand_asset",
        sa.Column("region_code", sa.String(length=20), nullable=True, comment="监测地区编码，空值代表全部区域"),
    )
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column("region_code", sa.String(length=20), nullable=True, comment="监测地区编码，空值代表全部区域"),
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE geo_brand_asset
            SET region_code = JSON_UNQUOTE(JSON_EXTRACT(region_codes_json, '$[0]'))
            WHERE JSON_LENGTH(region_codes_json) > 0
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE geo_lead_diagnosis
            SET region_code = JSON_UNQUOTE(JSON_EXTRACT(region_codes_json, '$[0]'))
            WHERE JSON_LENGTH(region_codes_json) > 0
            """
        )
    )
    op.drop_column("geo_brand_asset", "region_codes_json")
    op.drop_column("geo_lead_diagnosis", "region_codes_json")
