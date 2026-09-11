"""retire customer.links customer.diagnosis shell menus

Revision ID: y0z1a2b34567
Revises: x9y0z1a23456
Create Date: 2026-08-27 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "y0z1a2b34567"
down_revision: Union[str, Sequence[str], None] = "x9y0z1a23456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 2026-08-27 - 下线客户空壳菜单 links/diagnosis，勿误伤 platform.lead_diagnosis
RETIRED_MENUS = (
    "customer.links",
    "customer.diagnosis",
)


def _menu_codes_sql(codes: tuple[str, ...]) -> str:
    return ", ".join(f"'{code}'" for code in codes)


def upgrade() -> None:
    conn = op.get_bind()
    codes = _menu_codes_sql(RETIRED_MENUS)
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu
        SET is_visible = 0, status = 0
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config
        SET is_visible = 0,
            remark = CASE menu_code
                WHEN 'customer.links' THEN '已下线空壳菜单'
                WHEN 'customer.diagnosis' THEN '已下线空壳菜单'
                ELSE remark
            END
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        INNER JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code IN ({codes}) AND m.deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE cpm FROM sys_customer_position_menu cpm
        INNER JOIN sys_menu m ON m.id = cpm.menu_id
        WHERE m.menu_code IN ({codes}) AND m.deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        INNER JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code IN ({codes}) AND m.deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE rm FROM sys_role_menu rm
        INNER JOIN sys_menu m ON m.id = rm.menu_id
        WHERE m.menu_code IN ({codes}) AND m.deleted = 0
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    codes = _menu_codes_sql(RETIRED_MENUS)
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu
        SET is_visible = 1, status = 1
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config
        SET is_visible = 1
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )
