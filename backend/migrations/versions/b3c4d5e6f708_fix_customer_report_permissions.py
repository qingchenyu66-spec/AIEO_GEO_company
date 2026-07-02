"""fix customer report permissions and normalize empty grants

Revision ID: b3c4d5e6f708
Revises: a2b3c4d5e6f7
Create Date: 2026-07-01 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b3c4d5e6f708"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        JOIN sys_user_identity ui ON ui.id = uim.identity_id
        SET uim.can_create = 0, uim.can_update = 0, uim.can_delete = 0, uim.can_export = 1
        WHERE m.menu_code = 'customer.reports'
          AND m.deleted = 0
          AND ui.identity_type = 'CUSTOMER'
          AND ui.deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        JOIN sys_position p ON p.id = pm.position_id
        SET pm.can_create = 0, pm.can_update = 0, pm.can_delete = 0, pm.can_export = 1
        WHERE m.menu_code = 'customer.reports'
          AND m.deleted = 0
          AND p.identity_type = 'CUSTOMER'
          AND p.deleted = 0
        """
    )


def downgrade() -> None:
    pass
