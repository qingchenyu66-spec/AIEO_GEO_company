"""add H5 paid diagnosis order table and runtime config seeds"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g8h9i0j12345"
down_revision: Union[str, Sequence[str], None] = "f6a7b89014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_h5_diagnosis_order",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("out_trade_no", sa.String(length=32), nullable=False),
        sa.Column("openid", sa.String(length=64), nullable=False),
        sa.Column("wechat_id", sa.String(length=64), nullable=False, comment="用户填写的微信号，供销售跟进"),
        sa.Column("contact_phone", sa.String(length=30), nullable=False),
        sa.Column("brand_name", sa.String(length=100), nullable=False),
        sa.Column("form_json", sa.JSON(), server_default=sa.text("(JSON_OBJECT())"), nullable=False),
        sa.Column("prompts_json", sa.JSON(), nullable=False),
        sa.Column("platforms_json", sa.JSON(), nullable=False),
        sa.Column("schedule_days", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("amount_fen", sa.Integer(), server_default=sa.text("990"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("prepay_id", sa.String(length=64), nullable=True),
        sa.Column("wx_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("lead_diagnosis_id", sa.Integer(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["lead_diagnosis_id"], ["geo_lead_diagnosis.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("out_trade_no"),
    )
    op.create_index("ix_geo_h5_diagnosis_order_openid", "geo_h5_diagnosis_order", ["openid"])
    op.create_index("ix_geo_h5_diagnosis_order_status", "geo_h5_diagnosis_order", ["status"])
    op.create_index("ix_geo_h5_diagnosis_order_wx_transaction_id", "geo_h5_diagnosis_order", ["wx_transaction_id"])
    op.create_index("ix_geo_h5_diagnosis_order_lead_diagnosis_id", "geo_h5_diagnosis_order", ["lead_diagnosis_id"])

    op.execute(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'h5_diagnosis_enabled', 'H5 付费诊断开关', 'true', 'global', 1, '9.9 H5', 0
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'h5_diagnosis_enabled' AND deleted = 0)
        """
    )
    op.execute(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'h5_diagnosis_price_fen', 'H5 诊断价格（分）', '990', 'global', 1, '9.9 元', 0
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'h5_diagnosis_price_fen' AND deleted = 0)
        """
    )
    op.execute(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'h5_diagnosis_schedule_days', 'H5 诊断天数', '3', 'global', 1, '默认 3 天', 0
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'h5_diagnosis_schedule_days' AND deleted = 0)
        """
    )
    op.execute(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'h5_diagnosis_platforms', 'H5 诊断平台', '["doubao","deepseek"]', 'global', 1, 'JSON 数组', 0
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'h5_diagnosis_platforms' AND deleted = 0)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE sys_system_config SET deleted = 1
        WHERE config_key IN (
            'h5_diagnosis_enabled',
            'h5_diagnosis_price_fen',
            'h5_diagnosis_schedule_days',
            'h5_diagnosis_platforms'
        )
        """
    )
    op.drop_index("ix_geo_h5_diagnosis_order_lead_diagnosis_id", table_name="geo_h5_diagnosis_order")
    op.drop_index("ix_geo_h5_diagnosis_order_wx_transaction_id", table_name="geo_h5_diagnosis_order")
    op.drop_index("ix_geo_h5_diagnosis_order_status", table_name="geo_h5_diagnosis_order")
    op.drop_index("ix_geo_h5_diagnosis_order_openid", table_name="geo_h5_diagnosis_order")
    op.drop_table("geo_h5_diagnosis_order")
