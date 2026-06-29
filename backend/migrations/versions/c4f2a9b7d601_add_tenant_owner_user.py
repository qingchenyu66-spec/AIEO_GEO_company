"""add tenant owner user

Revision ID: c4f2a9b7d601
Revises: b1c2d3e4f560
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa


revision = "c4f2a9b7d601"
down_revision = "b1c2d3e4f560"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sys_tenant",
        sa.Column("owner_user_id", sa.Integer(), nullable=True, comment="归属销售/创建人用户ID"),
    )
    op.create_index("ix_sys_tenant_owner_user_id", "sys_tenant", ["owner_user_id"])
    op.create_foreign_key(
        "fk_sys_tenant_owner_user_id",
        "sys_tenant",
        "sys_user",
        ["owner_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_sys_tenant_owner_user_id", "sys_tenant", type_="foreignkey")
    op.drop_index("ix_sys_tenant_owner_user_id", table_name="sys_tenant")
    op.drop_column("sys_tenant", "owner_user_id")
