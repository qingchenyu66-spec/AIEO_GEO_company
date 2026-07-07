"""repair created_by for users created via approval replay

Revision ID: n2o3p4q678
Revises: m1n2o3p567
Create Date: 2026-07-07 10:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "n2o3p4q678"
down_revision: Union[str, Sequence[str], None] = "m1n2o3p567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE sys_user u
        JOIN sys_operation_approval a
          ON a.operation_key = 'management.user.create'
         AND a.status = 'approved'
         AND a.executed_result_json IS NOT NULL
         AND CAST(JSON_UNQUOTE(JSON_EXTRACT(a.executed_result_json, '$.id')) AS UNSIGNED) = u.id
        SET u.created_by = a.requester_user_id
        WHERE u.created_by <> a.requester_user_id
        """
    )


def downgrade() -> None:
    pass
