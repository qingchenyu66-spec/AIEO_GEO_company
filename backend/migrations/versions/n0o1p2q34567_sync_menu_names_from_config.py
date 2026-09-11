"""sync sys_menu display fields from sys_menu_config

Revision ID: n0o1p2q34567
Revises: m9n0o1p23456
Create Date: 2026-09-11

2026-09-11 - 菜单配置为唯一展示口径，部署时把历史漂移的 sys_menu 名称/排序/图标/路由回写对齐
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n0o1p2q34567"
down_revision: Union[str, Sequence[str], None] = "m9n0o1p23456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT menu_code, identity_type, menu_name, sort_order, icon, route_path
            FROM sys_menu_config
            WHERE deleted = 0
            """
        )
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                """
                UPDATE sys_menu
                SET menu_name = :menu_name,
                    sort_order = :sort_order,
                    icon = COALESCE(:icon, icon),
                    route_path = COALESCE(:route_path, route_path)
                WHERE menu_code = :menu_code
                  AND identity_type = :identity_type
                  AND deleted = 0
                """
            ),
            {
                "menu_code": row.menu_code,
                "identity_type": row.identity_type,
                "menu_name": row.menu_name,
                "sort_order": int(row.sort_order or 0),
                "icon": row.icon,
                "route_path": row.route_path,
            },
        )


def downgrade() -> None:
    # 名称回写不可逆；保留空 downgrade
    pass
