"""add credit recharge order table and grant enterprise_admin can_create

Revision ID: r4s5t6u78901
Revises: q3r4s5t67890
Create Date: 2026-09-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r4s5t6u78901"
down_revision: Union[str, Sequence[str], None] = "q3r4s5t67890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_credit_recharge_order",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("out_trade_no", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("payer_user_id", sa.Integer(), nullable=False),
        sa.Column("yuan_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("credits_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("credits_per_yuan_locked", sa.Numeric(10, 4), nullable=False),
        sa.Column("amount_fen", sa.Integer(), nullable=False),
        sa.Column("pay_channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("code_url", sa.String(length=512), nullable=True),
        sa.Column("transaction_id", sa.String(length=64), nullable=True),
        sa.Column("ledger_id", sa.Integer(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.ForeignKeyConstraint(["payer_user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("out_trade_no"),
    )
    op.create_index("ix_geo_credit_recharge_order_out_trade_no", "geo_credit_recharge_order", ["out_trade_no"])
    op.create_index("ix_geo_credit_recharge_order_tenant_id", "geo_credit_recharge_order", ["tenant_id"])
    op.create_index("ix_geo_credit_recharge_order_payer_user_id", "geo_credit_recharge_order", ["payer_user_id"])
    op.create_index("ix_geo_credit_recharge_order_status", "geo_credit_recharge_order", ["status"])
    op.create_index("ix_geo_credit_recharge_order_transaction_id", "geo_credit_recharge_order", ["transaction_id"])

    # 企业管理员：开放算力中心 can_create，用于在线充值
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE sys_customer_position_menu cpm
        JOIN sys_customer_position p ON p.id = cpm.position_id AND p.deleted = 0
        JOIN sys_menu m ON m.id = cpm.menu_id AND m.deleted = 0
        SET cpm.can_create = 1
        WHERE p.position_code = 'enterprise_admin'
          AND p.tenant_id IS NULL
          AND m.menu_code = 'customer.enterprise_credit'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_user_identity_menu uim
        JOIN sys_user_identity ui ON ui.id = uim.identity_id AND ui.deleted = 0
        JOIN sys_menu m ON m.id = uim.menu_id AND m.deleted = 0
        JOIN sys_customer_position p ON p.id = ui.customer_position_id AND p.deleted = 0
        SET uim.can_create = 1
        WHERE ui.identity_type = 'CUSTOMER'
          AND p.position_code = 'enterprise_admin'
          AND m.menu_code = 'customer.enterprise_credit'
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE sys_user_identity_menu uim
        JOIN sys_user_identity ui ON ui.id = uim.identity_id AND ui.deleted = 0
        JOIN sys_menu m ON m.id = uim.menu_id AND m.deleted = 0
        JOIN sys_customer_position p ON p.id = ui.customer_position_id AND p.deleted = 0
        SET uim.can_create = 0
        WHERE ui.identity_type = 'CUSTOMER'
          AND p.position_code = 'enterprise_admin'
          AND m.menu_code = 'customer.enterprise_credit'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_customer_position_menu cpm
        JOIN sys_customer_position p ON p.id = cpm.position_id AND p.deleted = 0
        JOIN sys_menu m ON m.id = cpm.menu_id AND m.deleted = 0
        SET cpm.can_create = 0
        WHERE p.position_code = 'enterprise_admin'
          AND p.tenant_id IS NULL
          AND m.menu_code = 'customer.enterprise_credit'
        """
    )
    op.drop_index("ix_geo_credit_recharge_order_transaction_id", table_name="geo_credit_recharge_order")
    op.drop_index("ix_geo_credit_recharge_order_status", table_name="geo_credit_recharge_order")
    op.drop_index("ix_geo_credit_recharge_order_payer_user_id", table_name="geo_credit_recharge_order")
    op.drop_index("ix_geo_credit_recharge_order_tenant_id", table_name="geo_credit_recharge_order")
    op.drop_index("ix_geo_credit_recharge_order_out_trade_no", table_name="geo_credit_recharge_order")
    op.drop_table("geo_credit_recharge_order")
