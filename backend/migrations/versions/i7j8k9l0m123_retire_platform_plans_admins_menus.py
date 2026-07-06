"""retire platform.plans platform.admins platform.diagnosis menus

Revision ID: i7j8k9l0m123
Revises: h6i7j8k9l012
Create Date: 2026-07-06 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "i7j8k9l0m123"
down_revision: Union[str, Sequence[str], None] = "h6i7j8k9l012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETIRED_MENUS = (
    "platform.plans",
    "platform.admins",
    "platform.diagnosis",
)


def _menu_codes_sql(codes: tuple[str, ...]) -> str:
    return ", ".join(f"'{code}'" for code in codes)


def upgrade() -> None:
    conn = op.get_bind()
    codes = _menu_codes_sql(RETIRED_MENUS)

    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu
        SET is_visible = 0
        WHERE menu_code IN ({codes}) AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config
        SET is_visible = 0,
            remark = CASE menu_code
                WHEN 'platform.plans' THEN '已下线'
                WHEN 'platform.admins' THEN '已下线'
                WHEN 'platform.diagnosis' THEN '已下线，请使用售前诊断'
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
        SET is_visible = 1
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
