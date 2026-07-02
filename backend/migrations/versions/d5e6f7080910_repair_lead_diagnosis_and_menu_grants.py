"""repair lead diagnosis grants and normalize menu action flags

Revision ID: d5e6f7080910
Revises: c4d5e6f70809
Create Date: 2026-07-01 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d5e6f7080910"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f70809"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 仅「查看」：不应有新建/编辑/删除
VIEW_ONLY_MENUS = (
    "platform.dashboard",
    "platform.audit.list",
    "platform.audit.files",
    "platform.competitor",
    "platform.sources",
    "platform.diagnosis",
    "platform.models",
    "platform.plans",
    "platform.admins",
    "platform.logs",
    "customer.workspace",
    "customer.realtime",
    "customer.links",
    "customer.diagnosis",
    "customer.competitor",
    "customer.sources",
)

LEAD_DIAGNOSIS_POSITIONS = ("PLATFORM_ADMIN", "PLATFORM_OPERATION", "PLATFORM_SALES")


def _menu_codes_sql(codes: tuple[str, ...]) -> str:
    return ", ".join(f"'{code}'" for code in codes)


def upgrade() -> None:
    conn = op.get_bind()

    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT 'platform.lead_diagnosis', '售前诊断', 'PLATFORM', '/platform/lead-diagnosis', 'Stethoscope', 36, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = 'platform.lead_diagnosis' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            'platform.lead_diagnosis', '售前诊断', 'PLATFORM', 36, 1, 'Stethoscope', '/platform/lead-diagnosis',
            '销售/运营内用：三时段抓取、汇总诊断、导出 PDF', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = 'platform.lead_diagnosis' AND deleted = 0
        )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_role_menu rm
              WHERE rm.role_id = r.id AND rm.menu_id = m.id
          )
        """
    )

    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
        SELECT p.id, m.id, 1, 0, 0, 1
        FROM sys_position p
        JOIN sys_menu m ON m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        WHERE p.position_code IN ({_menu_codes_sql(LEAD_DIAGNOSIS_POSITIONS)})
          AND p.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_position_menu pm
              WHERE pm.position_id = p.id AND pm.menu_id = m.id
          )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_user_identity_menu (identity_id, menu_id, can_create, can_update, can_delete, can_export)
        SELECT ui.id, m.id, 1, 0, 0, 1
        FROM sys_user_identity ui
        JOIN sys_menu m ON m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        WHERE ui.identity_type = 'PLATFORM' AND ui.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_user_identity_menu uim
              WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
          )
        """
    )

    view_only = _menu_codes_sql(VIEW_ONLY_MENUS)
    conn.exec_driver_sql(
        f"""
        UPDATE sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        SET pm.can_create = 0, pm.can_update = 0, pm.can_delete = 0
        WHERE m.menu_code IN ({view_only}) AND m.deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        SET uim.can_create = 0, uim.can_update = 0, uim.can_delete = 0
        WHERE m.menu_code IN ({view_only}) AND m.deleted = 0
        """
    )

    conn.exec_driver_sql(
        """
        UPDATE sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        SET pm.can_create = 0, pm.can_update = 0, pm.can_delete = 0
        WHERE m.menu_code = 'customer.reports' AND m.deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        SET uim.can_create = 0, uim.can_update = 0, uim.can_delete = 0, uim.can_export = 1
        WHERE m.menu_code = 'customer.reports' AND m.deleted = 0
        """
    )

    conn.exec_driver_sql(
        """
        UPDATE sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        SET pm.can_update = 0, pm.can_delete = 0
        WHERE m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        SET uim.can_update = 0, uim.can_delete = 0
        WHERE m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        """
    )


def downgrade() -> None:
    pass
