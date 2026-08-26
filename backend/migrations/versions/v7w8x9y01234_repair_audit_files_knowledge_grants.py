"""repair platform.audit.files knowledge upload grants

Revision ID: v7w8x9y01234
Revises: u6v7w8x90123
Create Date: 2026-08-26

2026-08-26 - 管理员 seed 曾给 audit.files 写 can_create/can_update，但职位 UI 只展示查看，
             导致未勾上传仍能看到上传入口；统一清为仅 can_export，需上传请在职位里勾。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v7w8x9y01234"
down_revision = "u6v7w8x90123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # 2026-08-26 - 知识库上传/删除改走 can_create/can_update，旧数据默认只留查看
    bind.execute(
        sa.text(
            """
            UPDATE sys_position_menu pm
            INNER JOIN sys_menu m ON m.id = pm.menu_id
            SET pm.can_create = 0, pm.can_update = 0
            WHERE m.menu_code = 'platform.audit.files' AND m.deleted = 0
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE sys_user_identity_menu uim
            INNER JOIN sys_menu m ON m.id = uim.menu_id
            SET uim.can_create = 0, uim.can_update = 0
            WHERE m.menu_code = 'platform.audit.files' AND m.deleted = 0
            """
        )
    )


def downgrade() -> None:
    pass
