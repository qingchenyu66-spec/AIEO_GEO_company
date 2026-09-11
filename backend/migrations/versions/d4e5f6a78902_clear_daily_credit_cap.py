"""clear deprecated daily_credit_cap on credit tenants

Revision ID: d4e5f6a78902
Revises: c3d4e5f67891
Create Date: 2026-08-28 11:20:00.000000

2026-08-28 - 日算力硬顶废弃 - 批量清 null，余额即单日上限
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a78902"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f67891"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # ponytail: 全量 credit 企业置 null，避免 JSON null/字符串混用导致 CAST 失败
    conn.exec_driver_sql(
        """
        UPDATE sys_tenant
        SET credit_policy_json = JSON_SET(
            COALESCE(credit_policy_json, JSON_OBJECT()),
            '$.daily_credit_cap',
            NULL
        )
        WHERE deleted = 0
          AND billing_mode = 'credit'
        """
    )


def downgrade() -> None:
    pass
