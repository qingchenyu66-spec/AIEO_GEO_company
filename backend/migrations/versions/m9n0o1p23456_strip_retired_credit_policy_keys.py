"""strip retired credit_policy quota keys from tenants

Revision ID: m9n0o1p23456
Revises: l8m9n0o12345
Create Date: 2026-09-09 13:40:00.000000

2026-09-09 - 方案 A：剥净历史/foundation 种子里的退役配额键，与 RETIRED_CREDIT_POLICY_KEYS 对齐
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "m9n0o1p23456"
down_revision: Union[str, Sequence[str], None] = "l8m9n0o12345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 与 app.services.credit_service.RETIRED_CREDIT_POLICY_KEYS 保持一致
_RETIRED_PATHS = (
    "$.keyword_limit",
    "$.schedule_slots_limit",
    "$.region_limit",
    "$.region_editable",
    "$.daily_credit_cap",
)


def upgrade() -> None:
    conn = op.get_bind()
    # MySQL JSON_REMOVE：缺键时忽略；COALESCE 避免 null 列
    conn.exec_driver_sql(
        """
        UPDATE sys_tenant
        SET credit_policy_json = JSON_REMOVE(
            COALESCE(credit_policy_json, JSON_OBJECT()),
            '$.keyword_limit',
            '$.schedule_slots_limit',
            '$.region_limit',
            '$.region_editable',
            '$.daily_credit_cap'
        )
        WHERE credit_policy_json IS NOT NULL
        """
    )


def downgrade() -> None:
    # 退役键不再回填
    del _RETIRED_PATHS
