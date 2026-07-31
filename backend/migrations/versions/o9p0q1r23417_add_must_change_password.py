"""add sys_user.must_change_password for forced first-login password change

Revision ID: o9p0q1r23417
Revises: n8o9p0q12316
Create Date: 2026-07-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o9p0q1r23417"
down_revision: Union[str, Sequence[str], None] = "n8o9p0q12316"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sys_user",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否必须修改密码后才能使用系统",
        ),
    )


def downgrade() -> None:
    op.drop_column("sys_user", "must_change_password")
