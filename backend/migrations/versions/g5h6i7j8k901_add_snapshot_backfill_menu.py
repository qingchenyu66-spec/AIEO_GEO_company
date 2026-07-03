"""add platform snapshot backfill menu

Revision ID: g5h6i7j8k901
Revises: f3c4d5e6f708
Create Date: 2026-07-03 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "g5h6i7j8k901"
down_revision: Union[str, Sequence[str], None] = "f3c4d5e6f708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLATFORM_POSITIONS = ("PLATFORM_ADMIN", "PLATFORM_OPERATION", "PLATFORM_SALES")


def upgrade() -> None:
    conn = op.get_bind()

    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT 'platform.snapshot_backfill', '快照补录', 'PLATFORM', '/platform/snapshot-backfill', 'Upload', 37, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = 'platform.snapshot_backfill' AND deleted = 0
        )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            'platform.snapshot_backfill', '快照补录', 'PLATFORM', 37, 1, 'Upload', '/platform/snapshot-backfill',
            '抓取失败时粘贴分享链接与回答正文，重算排名与健康分', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = 'platform.snapshot_backfill' AND deleted = 0
        )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code = 'platform.snapshot_backfill' AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_role_menu rm
              WHERE rm.role_id = r.id AND rm.menu_id = m.id
          )
        """
    )

    positions_sql = ", ".join(f"'{code}'" for code in PLATFORM_POSITIONS)
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, m.id, 0, 1, 0, 1
        FROM sys_user_identity ui
        JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0
        JOIN sys_menu m ON m.menu_code = 'platform.snapshot_backfill' AND m.deleted = 0
        WHERE ui.deleted = 0
          AND p.position_code IN ({positions_sql})
          AND NOT EXISTS (
              SELECT 1 FROM sys_user_identity_menu uim
              WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
          )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = 'platform.snapshot_backfill'
        """
    )
    conn.exec_driver_sql(
        """
        DELETE rm FROM sys_role_menu rm
        JOIN sys_menu m ON m.id = rm.menu_id
        WHERE m.menu_code = 'platform.snapshot_backfill'
        """
    )
    conn.exec_driver_sql("DELETE FROM sys_menu_config WHERE menu_code = 'platform.snapshot_backfill'")
    conn.exec_driver_sql("DELETE FROM sys_menu WHERE menu_code = 'platform.snapshot_backfill'")
