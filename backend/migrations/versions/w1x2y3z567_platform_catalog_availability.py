"""platform catalog listed/availability + notify config

Revision ID: w1x2y3z567
Revises: v0w1x2y456
Create Date: 2026-07-15
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "w1x2y3z567"
down_revision = "v0w1x2y456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_platform",
        sa.Column("catalog_listed", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="是否仍在模力官方目录"),
    )
    op.add_column(
        "geo_platform",
        sa.Column("service_available", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="周探测是否可用"),
    )
    op.add_column(
        "geo_platform",
        sa.Column("service_checked_at", sa.DateTime(), nullable=True, comment="最近可用性探测时间"),
    )

    conn = op.get_bind()
    # 默认通知职位：PLATFORM_SALES / PLATFORM_OPERATION / PLATFORM_ADMIN
    rows = conn.execute(
        sa.text(
            "SELECT id FROM sys_position WHERE deleted = 0 AND position_code IN "
            "('PLATFORM_SALES', 'PLATFORM_OPERATION', 'PLATFORM_ADMIN')"
        )
    ).fetchall()
    ids = [int(r[0]) for r in rows]
    raw = json.dumps(ids, ensure_ascii=False)
    existing = conn.execute(
        sa.text("SELECT id FROM sys_config WHERE config_key = 'platform_service_notify_position_ids' LIMIT 1")
    ).fetchone()
    if existing is None:
        conn.execute(
            sa.text(
                "INSERT INTO sys_config (config_key, config_value, scope, description, status, created_at, updated_at) "
                "VALUES ('platform_service_notify_position_ids', :val, 'notification', "
                "'平台可用性/上下架铃铛通知：职位 ID 列表 JSON，仅 PLATFORM', 1, NOW(), NOW())"
            ),
            {"val": raw},
        )
    else:
        conn.execute(
            sa.text(
                "UPDATE sys_config SET config_value = :val, updated_at = NOW() "
                "WHERE config_key = 'platform_service_notify_position_ids' "
                "AND (config_value IS NULL OR TRIM(config_value) = '' OR TRIM(config_value) = '[]')"
            ),
            {"val": raw},
        )


def downgrade() -> None:
    op.drop_column("geo_platform", "service_checked_at")
    op.drop_column("geo_platform", "service_available")
    op.drop_column("geo_platform", "catalog_listed")
