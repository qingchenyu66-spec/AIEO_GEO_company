"""add system notifications

Revision ID: f2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-02 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_system_notification",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="通知ID"),
        sa.Column("audience_type", sa.String(length=20), nullable=False, comment="受众: PLATFORM/CUSTOMER"),
        sa.Column("tenant_id", sa.Integer(), nullable=True, comment="企业ID，NULL表示全局"),
        sa.Column("category", sa.String(length=40), nullable=False, comment="分类"),
        sa.Column("level", sa.String(length=20), nullable=False, comment="级别"),
        sa.Column("title", sa.String(length=120), nullable=False, comment="标题"),
        sa.Column("message", sa.String(length=500), nullable=False, comment="正文"),
        sa.Column("payload_json", sa.Text(), nullable=True, comment="扩展 JSON"),
        sa.Column("source_key", sa.String(length=120), nullable=False, comment="去重键"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_system_notification_audience_type", "geo_system_notification", ["audience_type"])
    op.create_index("ix_geo_system_notification_tenant_id", "geo_system_notification", ["tenant_id"])
    op.create_index("ix_geo_system_notification_category", "geo_system_notification", ["category"])
    op.create_index("ix_geo_system_notification_source_key", "geo_system_notification", ["source_key"])

    op.create_table(
        "geo_system_notification_read",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="记录ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("notification_id", sa.Integer(), nullable=False, comment="通知ID"),
        sa.Column("read_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["geo_system_notification.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "notification_id", name="uq_geo_notification_read"),
    )
    op.create_index("ix_geo_system_notification_read_user_id", "geo_system_notification_read", ["user_id"])
    op.create_index("ix_geo_system_notification_read_notification_id", "geo_system_notification_read", ["notification_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_system_notification_read_notification_id", table_name="geo_system_notification_read")
    op.drop_index("ix_geo_system_notification_read_user_id", table_name="geo_system_notification_read")
    op.drop_table("geo_system_notification_read")
    op.drop_index("ix_geo_system_notification_source_key", table_name="geo_system_notification")
    op.drop_index("ix_geo_system_notification_category", table_name="geo_system_notification")
    op.drop_index("ix_geo_system_notification_tenant_id", table_name="geo_system_notification")
    op.drop_index("ix_geo_system_notification_audience_type", table_name="geo_system_notification")
    op.drop_table("geo_system_notification")
