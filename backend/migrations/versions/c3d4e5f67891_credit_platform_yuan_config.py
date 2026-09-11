"""add platform_molizhishu_yuan_per_subtask system config

Revision ID: c3d4e5f67891
Revises: b2c3d4e67890
Create Date: 2026-08-28 10:50:00.000000

2026-08-28 - 模力真金闸子任务成本可配置，默认 0.19 元/条
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f67891"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e67890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'platform_molizhishu_yuan_per_subtask', '模力子任务成本(元)', '0.19', '算力自助', '正常',
               '下一窗真金预估=子任务数×本值；模力调价后在此同步', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_system_config
            WHERE config_key = 'platform_molizhishu_yuan_per_subtask' AND deleted = 0
        )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE sys_system_config SET deleted = 1
        WHERE config_key = 'platform_molizhishu_yuan_per_subtask' AND deleted = 0
        """
    )
