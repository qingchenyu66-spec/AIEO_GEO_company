"""add brand keyword groups and region

Revision ID: 2c9d7f1a4b80
Revises: 0f4d6c2a8b91
Create Date: 2026-06-26 10:00:00.000000
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "2c9d7f1a4b80"
down_revision = "0f4d6c2a8b91"
branch_labels = None
depends_on = None


def _loads(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except Exception:
        return []


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def upgrade() -> None:
    op.add_column(
        "geo_brand_asset",
        sa.Column("region_code", sa.String(length=20), nullable=True, comment="监测地区编码，空值代表全部区域"),
    )
    op.create_table(
        "geo_brand_keyword_group",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="词组ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("brand_asset_id", sa.Integer(), nullable=False, comment="品牌资产ID"),
        sa.Column("monitor_keyword", sa.String(length=150), nullable=False, comment="监测关键词"),
        sa.Column("exposure_terms_json", sa.JSON(), nullable=False, comment="露出词JSON"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序"),
        sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="是否启用"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["brand_asset_id"], ["geo_brand_asset.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_brand_keyword_group_tenant_id", "geo_brand_keyword_group", ["tenant_id"])
    op.create_index("ix_geo_brand_keyword_group_brand_asset_id", "geo_brand_keyword_group", ["brand_asset_id"])
    op.create_index("ix_geo_brand_keyword_group_deleted", "geo_brand_keyword_group", ["deleted"])

    bind = op.get_bind()
    assets = bind.execute(
        sa.text(
            "select id, tenant_id, company_full_name, brand_name, brand_short_name, "
            "monitor_keywords_json, aliases_json from geo_brand_asset where deleted = 0"
        )
    ).mappings().all()
    for asset in assets:
        monitor_keywords = _dedupe(
            [
                asset["company_full_name"],
                asset["brand_name"],
                asset["brand_short_name"],
                *_loads(asset["monitor_keywords_json"]),
            ]
        )
        aliases = _dedupe([asset["brand_short_name"], *_loads(asset["aliases_json"])])
        if not monitor_keywords:
            continue
        for index, keyword in enumerate(monitor_keywords):
            terms = aliases if index == 0 else [keyword]
            bind.execute(
                sa.text(
                    "insert into geo_brand_keyword_group "
                    "(tenant_id, brand_asset_id, monitor_keyword, exposure_terms_json, sort_order, status, deleted) "
                    "values (:tenant_id, :brand_asset_id, :monitor_keyword, :exposure_terms_json, :sort_order, 1, 0)"
                ),
                {
                    "tenant_id": asset["tenant_id"],
                    "brand_asset_id": asset["id"],
                    "monitor_keyword": keyword,
                    "exposure_terms_json": json.dumps(_dedupe(terms), ensure_ascii=False),
                    "sort_order": index,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_geo_brand_keyword_group_deleted", table_name="geo_brand_keyword_group")
    op.drop_index("ix_geo_brand_keyword_group_brand_asset_id", table_name="geo_brand_keyword_group")
    op.drop_index("ix_geo_brand_keyword_group_tenant_id", table_name="geo_brand_keyword_group")
    op.drop_table("geo_brand_keyword_group")
    op.drop_column("geo_brand_asset", "region_code")
