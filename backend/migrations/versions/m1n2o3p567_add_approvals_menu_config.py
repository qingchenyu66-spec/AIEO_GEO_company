"""add platform.approvals to menu config for assignment UI

Revision ID: m1n2o3p567
Revises: l0m1n2o456
Create Date: 2026-07-07 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "m1n2o3p567"
down_revision: Union[str, Sequence[str], None] = "l0m1n2o456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            'platform.approvals', '操作审批', 'PLATFORM', 15, 1, 'ClipboardCheck', '/platform/approvals',
            '销售提交的操作需运营或管理员审批后生效；销售可查看自己的申请', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = 'platform.approvals' AND deleted = 0
        )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE sys_menu_config
        SET deleted = 1
        WHERE menu_code = 'platform.approvals' AND deleted = 0
        """
    )
