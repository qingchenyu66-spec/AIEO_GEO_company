"""add tenant service period

Revision ID: 0f4d6c2a8b91
Revises: 689994f930b9
Create Date: 2026-06-25 14:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f4d6c2a8b91"
down_revision: Union[str, Sequence[str], None] = "689994f930b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sys_tenant", sa.Column("service_start_date", sa.Date(), nullable=True, comment="服务开始日期"))
    op.add_column("sys_tenant", sa.Column("service_end_date", sa.Date(), nullable=True, comment="服务结束日期"))


def downgrade() -> None:
    op.drop_column("sys_tenant", "service_end_date")
    op.drop_column("sys_tenant", "service_start_date")
