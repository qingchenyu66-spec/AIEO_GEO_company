"""add tenant logo columns

Revision ID: u6v7w8x90123
Revises: t5u6v7w89012
Create Date: 2026-08-24

2026-08-24 - 企业侧栏 Logo - sys_tenant 增加 logo_path / logo_updated_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "u6v7w8x90123"
down_revision = "t5u6v7w89012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("sys_tenant")}
    if "logo_path" not in columns:
        op.add_column("sys_tenant", sa.Column("logo_path", sa.String(length=255), nullable=True, comment="企业 Logo 相对路径"))
    if "logo_updated_at" not in columns:
        op.add_column("sys_tenant", sa.Column("logo_updated_at", sa.DateTime(), nullable=True, comment="企业 Logo 更新时间"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("sys_tenant")}
    if "logo_updated_at" in columns:
        op.drop_column("sys_tenant", "logo_updated_at")
    if "logo_path" in columns:
        op.drop_column("sys_tenant", "logo_path")
