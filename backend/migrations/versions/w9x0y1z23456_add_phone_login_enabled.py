"""add sys_user.phone_login_enabled

Revision ID: w9x0y1z23456
Revises: v8w9x0y12345
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w9x0y1z23456"
down_revision: Union[str, Sequence[str], None] = "v8w9x0y12345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sys_user",
        sa.Column(
            "phone_login_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="是否允许用该手机号验证码登录",
        ),
    )


def downgrade() -> None:
    op.drop_column("sys_user", "phone_login_enabled")
