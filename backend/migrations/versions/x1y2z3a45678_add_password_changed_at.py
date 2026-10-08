"""add sys_user.password_changed_at

Revision ID: x1y2z3a45678
Revises: w9x0y1z23456
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x1y2z3a45678"
down_revision: Union[str, Sequence[str], None] = "w9x0y1z23456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sys_user",
        sa.Column("password_changed_at", sa.DateTime(), nullable=True, comment="密码变更时间, 更早的登录凭证失效"),
    )


def downgrade() -> None:
    op.drop_column("sys_user", "password_changed_at")
