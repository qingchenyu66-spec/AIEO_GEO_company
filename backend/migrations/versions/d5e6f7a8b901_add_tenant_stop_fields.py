"""add tenant stop fields

Revision ID: d5e6f7a8b901
Revises: c4f2a9b7d601
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b901"
down_revision = "c4f2a9b7d601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sys_tenant",
        sa.Column("stop_reason", sa.String(length=30), nullable=True, comment="停服原因：manual人工停服、canceled未开始取消、expired到期"),
    )
    op.add_column(
        "sys_tenant",
        sa.Column("stopped_at", sa.DateTime(), nullable=True, comment="停服时间"),
    )
    op.add_column(
        "sys_tenant",
        sa.Column("stopped_by", sa.Integer(), nullable=True, comment="停服操作人ID"),
    )
    op.create_index("ix_sys_tenant_stopped_by", "sys_tenant", ["stopped_by"])
    op.create_foreign_key(
        "fk_sys_tenant_stopped_by",
        "sys_tenant",
        "sys_user",
        ["stopped_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_sys_tenant_stopped_by", "sys_tenant", type_="foreignkey")
    op.drop_index("ix_sys_tenant_stopped_by", table_name="sys_tenant")
    op.drop_column("sys_tenant", "stopped_by")
    op.drop_column("sys_tenant", "stopped_at")
    op.drop_column("sys_tenant", "stop_reason")
