"""merge heads + credit price rule normalized unique keys

Revision ID: f6a7b89014
Revises: d4e5f6a78902, e5f6a78903
Create Date: 2026-08-28 13:45:00.000000

2026-08-28 - MySQL UNIQUE 对 NULL 无效 - tenant_key/platform_key 归一再约束
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b89014"
down_revision: Union[str, Sequence[str], None] = ("d4e5f6a78902", "e5f6a78903")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_PLATFORM_KEY = "__default__"


def upgrade() -> None:
    op.add_column(
        "geo_credit_price_rule",
        sa.Column("tenant_key", sa.Integer(), nullable=False, server_default="0", comment="global=0；tenant=tenant_id"),
    )
    op.add_column(
        "geo_credit_price_rule",
        sa.Column(
            "platform_key",
            sa.String(length=50),
            nullable=False,
            server_default=_DEFAULT_PLATFORM_KEY,
            comment="空平台归一为 __default__",
        ),
    )
    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        UPDATE geo_credit_price_rule
        SET tenant_key = COALESCE(tenant_id, 0),
            platform_key = CASE
                WHEN platform_code IS NULL OR TRIM(platform_code) = '' THEN '{_DEFAULT_PLATFORM_KEY}'
                ELSE TRIM(platform_code)
            END
        """
    )
    conn.exec_driver_sql(
        """
        DELETE older FROM geo_credit_price_rule older
        INNER JOIN geo_credit_price_rule newer
          ON older.scope = newer.scope
         AND older.tenant_key = newer.tenant_key
         AND older.platform_key = newer.platform_key
         AND older.id < newer.id
        """
    )
    op.drop_constraint("uk_credit_price_rule_scope", "geo_credit_price_rule", type_="unique")
    op.create_unique_constraint(
        "uk_credit_price_rule_scope",
        "geo_credit_price_rule",
        ["scope", "tenant_key", "platform_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uk_credit_price_rule_scope", "geo_credit_price_rule", type_="unique")
    op.create_unique_constraint(
        "uk_credit_price_rule_scope",
        "geo_credit_price_rule",
        ["scope", "tenant_id", "platform_code"],
    )
    op.drop_column("geo_credit_price_rule", "platform_key")
    op.drop_column("geo_credit_price_rule", "tenant_key")
