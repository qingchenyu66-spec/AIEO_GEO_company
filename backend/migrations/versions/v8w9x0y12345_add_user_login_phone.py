"""add sys_user.phone for SMS login

Revision ID: v8w9x0y12345
Revises: u7v8w9x01234
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v8w9x0y12345"
down_revision: Union[str, Sequence[str], None] = "u7v8w9x01234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sys_user",
        sa.Column("phone", sa.String(length=20), nullable=True, comment="登录手机号, 填写后可直接验证码登录"),
    )
    op.create_index("uk_sys_user_phone", "sys_user", ["phone"], unique=True)


def downgrade() -> None:
    op.drop_index("uk_sys_user_phone", table_name="sys_user")
    op.drop_column("sys_user", "phone")
