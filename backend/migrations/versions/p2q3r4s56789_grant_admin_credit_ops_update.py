"""grant PLATFORM_ADMIN credit_ops_board can_update

Revision ID: p2q3r4s56789
Revises: o1p2q3r45678
Create Date: 2026-09-14

2026-09-14 - 管理员算力运营补编辑权；职位保存曾因动作表白名单缺失把 can_update 剥掉。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "p2q3r4s56789"
down_revision: Union[str, Sequence[str], None] = "o1p2q3r45678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOARD = "platform.credit_ops_board"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            UPDATE sys_position_menu pm
            JOIN sys_position p ON p.id = pm.position_id AND p.deleted = 0
            JOIN sys_menu m ON m.id = pm.menu_id AND m.deleted = 0
            SET pm.can_update = 1, pm.can_export = 1
            WHERE p.position_code = 'PLATFORM_ADMIN'
              AND m.menu_code = :code
            """
        ),
        {"code": BOARD},
    )
    conn.execute(
        text(
            """
            UPDATE sys_user_identity_menu uim
            JOIN sys_user_identity ui ON ui.id = uim.identity_id AND ui.deleted = 0
            JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0
            JOIN sys_menu m ON m.id = uim.menu_id AND m.deleted = 0
            SET uim.can_update = 1, uim.can_export = 1
            WHERE p.position_code = 'PLATFORM_ADMIN'
              AND m.menu_code = :code
            """
        ),
        {"code": BOARD},
    )


def downgrade() -> None:
    # 不回滚编辑权，避免误伤手工加过的授权
    pass
