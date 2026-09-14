"""split menu feature vs sidebar, strip product grants from identity/position

Revision ID: q3r4s5t67890
Revises: p2q3r4s56789
Create Date: 2026-09-14

is_visible = 功能启用；show_in_sidebar = 侧栏露出。
页内权限项恢复功能启用，仅关侧栏。身份/平台职位不再落商品卡和企业配置授权。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "q3r4s5t67890"
down_revision: Union[str, Sequence[str], None] = "p2q3r4s56789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IN_PAGE_CODES = (
    "platform.settings.secrets",
    "platform.settings.schedule",
    "platform.settings.cache_queue",
    "platform.settings.notification",
    "platform.settings.menu",
    "platform.audit.purge",
    "platform.tenant_credit",
    "platform.tenant_credit_blocks",
    "customer.enterprise_monitor",
    "customer.enterprise_members",
    "customer.enterprise_credit",
    "customer.enterprise_audit",
)

PRODUCT_CODES = (
    "customer.goods_cards",
    "customer.enterprise_config",
    "customer.enterprise_monitor",
    "customer.enterprise_members",
    "customer.enterprise_credit",
    "customer.enterprise_audit",
)


def upgrade() -> None:
    conn = op.get_bind()
    in_page = ", ".join(f"'{code}'" for code in IN_PAGE_CODES)
    product = ", ".join(f"'{code}'" for code in PRODUCT_CODES)
    conn.execute(
        text(
            """
            ALTER TABLE sys_menu_config
            ADD COLUMN show_in_sidebar TINYINT(1) NOT NULL DEFAULT 1
            COMMENT '是否进侧栏' AFTER sort_order
            """
        )
    )
    conn.execute(text("UPDATE sys_menu_config SET show_in_sidebar = is_visible WHERE deleted = 0"))
    conn.execute(
        text(
            f"""
            UPDATE sys_menu_config
            SET is_visible = 1, show_in_sidebar = 0
            WHERE deleted = 0 AND menu_code IN ({in_page})
            """
        )
    )
    conn.execute(
        text(
            f"""
            DELETE pm FROM sys_position_menu pm
            JOIN sys_menu m ON m.id = pm.menu_id
            WHERE m.menu_code IN ({product})
            """
        )
    )
    conn.execute(
        text(
            f"""
            DELETE uim FROM sys_user_identity_menu uim
            JOIN sys_menu m ON m.id = uim.menu_id
            WHERE m.menu_code IN ({product})
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    in_page = ", ".join(f"'{code}'" for code in IN_PAGE_CODES)
    conn.execute(
        text(
            f"""
            UPDATE sys_menu_config
            SET is_visible = 0
            WHERE deleted = 0 AND show_in_sidebar = 0 AND menu_code IN ({in_page})
            """
        )
    )
    conn.execute(text("ALTER TABLE sys_menu_config DROP COLUMN show_in_sidebar"))
