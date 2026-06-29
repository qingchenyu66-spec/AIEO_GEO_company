"""add brand monitored platforms

Revision ID: e9f4b7c2a901
Revises: d21b9a4f6c30
Create Date: 2026-06-24 15:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e9f4b7c2a901"
down_revision: Union[str, Sequence[str], None] = "d21b9a4f6c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为每家企业保存已购买或允许监测的模型平台。"""
    op.add_column(
        "geo_brand_asset",
        sa.Column(
            "monitored_platforms_json",
            sa.JSON(),
            nullable=True,
            comment="企业已购买或允许监测的模型平台编码JSON",
        ),
    )
    op.execute(
        """
        UPDATE geo_brand_asset
        SET monitored_platforms_json = JSON_ARRAY('doubao_mobile','deepseek_mobile','yuanbao','kimi','baiduai')
        WHERE monitored_platforms_json IS NULL
        """
    )
    op.alter_column("geo_brand_asset", "monitored_platforms_json", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """回滚企业模型平台配置字段。"""
    op.drop_column("geo_brand_asset", "monitored_platforms_json")
