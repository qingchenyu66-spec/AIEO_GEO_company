"""hide credit sidebar menus merged into credit ops board

Revision ID: b2c3d4e67890
Revises: a2b3c4d56789
Create Date: 2026-08-27 15:00:00.000000

2026-08-27 - 方案B：提交拦截/企业算力侧栏隐藏，保留菜单码做权限
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b2c3d4e67890"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d56789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HIDE_CODES = ("platform.tenant_credit_blocks", "platform.tenant_credit")


def upgrade() -> None:
    conn = op.get_bind()
    codes = ", ".join(f"'{c}'" for c in HIDE_CODES)
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu SET is_visible = 0
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config SET is_visible = 0
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE sys_menu SET is_visible = 1
        WHERE menu_code = 'platform.tenant_credit_blocks' AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_menu_config SET is_visible = 1
        WHERE menu_code = 'platform.tenant_credit_blocks' AND deleted = 0
        """
    )
