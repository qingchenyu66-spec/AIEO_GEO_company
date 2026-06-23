"""add brand assets

Revision ID: a4f2c6d8e901
Revises: 9b8c2d7e4f10
Create Date: 2026-06-23 12:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4f2c6d8e901"
down_revision: Union[str, Sequence[str], None] = "9b8c2d7e4f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建企业品牌资产和竞品库表。"""
    op.create_table(
        "geo_brand_asset",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="品牌资产ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("company_full_name", sa.String(length=150), nullable=False, comment="企业全称"),
        sa.Column("brand_name", sa.String(length=100), nullable=False, comment="品牌主词"),
        sa.Column("brand_short_name", sa.String(length=100), nullable=True, comment="企业或品牌简称"),
        sa.Column("monitor_keywords_json", sa.JSON(), nullable=False, comment="监控词列表JSON"),
        sa.Column("aliases_json", sa.JSON(), nullable=False, comment="品牌别名和简称JSON"),
        sa.Column("product_keywords_json", sa.JSON(), nullable=False, comment="产品词或业务词JSON"),
        sa.Column("official_url", sa.String(length=500), nullable=True, comment="官网或主站URL"),
        sa.Column("description", sa.Text(), nullable=True, comment="品牌说明"),
        sa.Column("status", sa.Boolean(), nullable=False, comment="是否启用"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uk_geo_brand_asset_tenant"),
        comment="企业品牌资产表",
    )
    op.create_index(op.f("ix_geo_brand_asset_deleted"), "geo_brand_asset", ["deleted"], unique=False)
    op.create_index(op.f("ix_geo_brand_asset_tenant_id"), "geo_brand_asset", ["tenant_id"], unique=False)

    op.create_table(
        "geo_brand_competitor",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="竞品ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("name", sa.String(length=100), nullable=False, comment="竞品名称"),
        sa.Column("short_name", sa.String(length=100), nullable=True, comment="竞品简称"),
        sa.Column("aliases_json", sa.JSON(), nullable=False, comment="竞品别名JSON"),
        sa.Column("website_url", sa.String(length=500), nullable=True, comment="竞品官网或主链接"),
        sa.Column("category", sa.String(length=50), nullable=True, comment="竞品类型"),
        sa.Column("status", sa.Boolean(), nullable=False, comment="是否启用"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="企业竞品库表",
    )
    op.create_index(op.f("ix_geo_brand_competitor_deleted"), "geo_brand_competitor", ["deleted"], unique=False)
    op.create_index(op.f("ix_geo_brand_competitor_tenant_id"), "geo_brand_competitor", ["tenant_id"], unique=False)


def downgrade() -> None:
    """回滚企业品牌资产和竞品库表。"""
    op.drop_index(op.f("ix_geo_brand_competitor_tenant_id"), table_name="geo_brand_competitor")
    op.drop_index(op.f("ix_geo_brand_competitor_deleted"), table_name="geo_brand_competitor")
    op.drop_table("geo_brand_competitor")
    op.drop_index(op.f("ix_geo_brand_asset_tenant_id"), table_name="geo_brand_asset")
    op.drop_index(op.f("ix_geo_brand_asset_deleted"), table_name="geo_brand_asset")
    op.drop_table("geo_brand_asset")
