"""add geo_brand_word_group for brand word config

Revision ID: a5b6c7d9012
Revises: z4a5b6c890
Create Date: 2026-07-21 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a5b6c7d9012"
down_revision: Union[str, Sequence[str], None] = "z4a5b6c890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_brand_word_group",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="品牌词组ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("brand_asset_id", sa.Integer(), nullable=False, comment="品牌资产ID"),
        sa.Column("name", sa.String(length=100), server_default="品牌词组", nullable=False, comment="词组名称"),
        sa.Column("monitor_keyword", sa.String(length=150), nullable=False, comment="监测关键词"),
        sa.Column(
            "monitor_keywords_json",
            sa.JSON(),
            server_default=sa.text("(JSON_ARRAY())"),
            nullable=False,
            comment="监测关键词列表JSON",
        ),
        sa.Column(
            "exposure_terms_json",
            sa.JSON(),
            server_default=sa.text("(JSON_ARRAY())"),
            nullable=False,
            comment="露出词JSON",
        ),
        sa.Column(
            "platforms_json",
            sa.JSON(),
            server_default=sa.text("(JSON_ARRAY())"),
            nullable=False,
            comment="监测平台编码JSON",
        ),
        sa.Column(
            "run_mode",
            sa.String(length=20),
            server_default="once",
            nullable=False,
            comment="运行时间：once仅本次 / weekly每周一",
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False, comment="排序"),
        sa.Column("status", sa.Boolean(), server_default=sa.text("1"), nullable=False, comment="是否启用"),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(["brand_asset_id"], ["geo_brand_asset.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_brand_word_group_tenant_id", "geo_brand_word_group", ["tenant_id"])
    op.create_index("ix_geo_brand_word_group_brand_asset_id", "geo_brand_word_group", ["brand_asset_id"])
    op.create_index("ix_geo_brand_word_group_deleted", "geo_brand_word_group", ["deleted"])


def downgrade() -> None:
    op.drop_index("ix_geo_brand_word_group_deleted", table_name="geo_brand_word_group")
    op.drop_index("ix_geo_brand_word_group_brand_asset_id", table_name="geo_brand_word_group")
    op.drop_index("ix_geo_brand_word_group_tenant_id", table_name="geo_brand_word_group")
    op.drop_table("geo_brand_word_group")
