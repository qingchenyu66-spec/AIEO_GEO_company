"""add platform.audit.regions; revive platform.audit.models for assignable grants

Revision ID: j4k5l6m79012
Revises: i3j4k5l6m789
Create Date: 2026-07-30

不改企业已有 region/platform 业务数据；仅菜单可见与授权拷贝，保持原编辑能力。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "j4k5l6m79012"
down_revision: Union[str, Sequence[str], None] = "i3j4k5l6m789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REGIONS = "platform.audit.regions"
MODELS = "platform.audit.models"
PROFILE = "platform.audit.profile"
KEYWORDS = "platform.audit.keywords"


def upgrade() -> None:
    conn = op.get_bind()

    # 2026-07-30 - 企业资料地区/平台拆权 - 新菜单 + 恢复平台范围，授权从旧菜单拷贝以免原编辑能力断裂
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{REGIONS}', '服务地区', 'PLATFORM', '/platform/audit/regions', 'MapPin', 221, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = '{REGIONS}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{REGIONS}', '服务地区', 'PLATFORM', 221, 1, 'MapPin', '/platform/audit/regions',
            '企业资料中的服务地区勾选', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{REGIONS}' AND deleted = 0
        )
        """
    )

    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu
        SET is_visible = 1, status = 1, deleted = 0,
            menu_name = '平台范围配置',
            route_path = '/platform/audit/models',
            icon = COALESCE(NULLIF(icon, ''), 'Database'),
            sort_order = 24
        WHERE menu_code = '{MODELS}'
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{MODELS}', '平台范围配置', 'PLATFORM', '/platform/audit/models', 'Database', 24, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = '{MODELS}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config
        SET is_visible = 1, deleted = 0,
            menu_name = '平台范围配置',
            remark = '监测词组/品牌词组上的监测平台勾选',
            sort_order = 24,
            icon = COALESCE(NULLIF(icon, ''), 'Database'),
            route_path = '/platform/audit/models'
        WHERE menu_code = '{MODELS}'
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{MODELS}', '平台范围配置', 'PLATFORM', 24, 1, 'Database', '/platform/audit/models',
            '监测词组/品牌词组上的监测平台勾选', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{MODELS}' AND deleted = 0
        )
        """
    )

    # 职位：有资料编辑 → 地区；有监测词编辑 → 平台（不覆盖已有授权）
    for source, target in ((PROFILE, REGIONS), (KEYWORDS, MODELS)):
        conn.exec_driver_sql(
            f"""
            INSERT INTO sys_position_menu (
                position_id, menu_id, can_create, can_update, can_delete, can_export
            )
            SELECT pm.position_id, tm.id, 0, pm.can_update, 0, pm.can_export
            FROM sys_position_menu pm
            JOIN sys_menu sm ON sm.id = pm.menu_id AND sm.menu_code = '{source}' AND sm.deleted = 0
            JOIN sys_menu tm ON tm.menu_code = '{target}' AND tm.deleted = 0
            WHERE NOT EXISTS (
                SELECT 1 FROM sys_position_menu x
                WHERE x.position_id = pm.position_id AND x.menu_id = tm.id
            )
            """
        )
        conn.exec_driver_sql(
            f"""
            INSERT INTO sys_user_identity_menu (
                identity_id, menu_id, can_create, can_update, can_delete, can_export
            )
            SELECT uim.identity_id, tm.id, 0, uim.can_update, 0, uim.can_export
            FROM sys_user_identity_menu uim
            JOIN sys_menu sm ON sm.id = uim.menu_id AND sm.menu_code = '{source}' AND sm.deleted = 0
            JOIN sys_menu tm ON tm.menu_code = '{target}' AND tm.deleted = 0
            WHERE NOT EXISTS (
                SELECT 1 FROM sys_user_identity_menu x
                WHERE x.identity_id = uim.identity_id AND x.menu_id = tm.id
            )
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = '{REGIONS}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code = '{REGIONS}'
        """
    )
    conn.exec_driver_sql(f"UPDATE sys_menu SET deleted = 1, is_visible = 0 WHERE menu_code = '{REGIONS}'")
    conn.exec_driver_sql(f"UPDATE sys_menu_config SET deleted = 1, is_visible = 0 WHERE menu_code = '{REGIONS}'")
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu SET is_visible = 0
        WHERE menu_code = '{MODELS}' AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config
        SET is_visible = 0, remark = '已合并至监测词组配置'
        WHERE menu_code = '{MODELS}' AND deleted = 0
        """
    )
