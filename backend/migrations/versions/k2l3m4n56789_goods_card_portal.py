"""tenant goods_card_enabled + customer.goods_cards menu

Revision ID: k2l3m4n56789
Revises: j1k2l3m45678
Create Date: 2026-09-01 17:35:00.000000

2026-09-01 - 商品卡进客户门户一期：企业开关 + 菜单（默认不批量授权）
（只挂 H5 线 j1k2，勿强并 credit head，避免本地半套 credit 库卡 upgrade）
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k2l3m4n56789"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m45678"
branch_labels = None
depends_on = None

MENU_CODE = "customer.goods_cards"


def upgrade() -> None:
    conn = op.get_bind()
    cols = {
        row[0]
        for row in conn.exec_driver_sql("SHOW COLUMNS FROM sys_tenant").fetchall()
    }
    if "goods_card_enabled" not in cols:
        op.add_column(
            "sys_tenant",
            sa.Column(
                "goods_card_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
                comment="是否开通客户门户商品卡分析",
            ),
        )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{MENU_CODE}', '商品卡', 'CUSTOMER', '/customer/goods-cards', 'Layers3', 25, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = '{MENU_CODE}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{MENU_CODE}', '商品卡', 'CUSTOMER', 25, 1, 'Layers3', '/customer/goods-cards',
            '日常监测词商品卡分析（企业开通后可见）', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{MENU_CODE}' AND deleted = 0
        )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = '{MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code = '{MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE cpm FROM sys_customer_position_menu cpm
        JOIN sys_menu m ON m.id = cpm.menu_id
        WHERE m.menu_code = '{MENU_CODE}'
        """
    )
    conn.exec_driver_sql(f"UPDATE sys_menu_config SET deleted = 1 WHERE menu_code = '{MENU_CODE}'")
    conn.exec_driver_sql(f"UPDATE sys_menu SET deleted = 1 WHERE menu_code = '{MENU_CODE}'")
    cols = {
        row[0]
        for row in conn.exec_driver_sql("SHOW COLUMNS FROM sys_tenant").fetchall()
    }
    if "goods_card_enabled" in cols:
        op.drop_column("sys_tenant", "goods_card_enabled")
