"""seed h5_diagnosis_schedule_runs from days*3

Revision ID: h9i0j1k23456
Revises: g8h9i0j12345
Create Date: 2026-08-31 15:30:00.000000

2026-08-31 - H5 监测次数可任意 1–90 - 新增配置项，旧天数×3 回填
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "h9i0j1k23456"
down_revision: Union[str, Sequence[str], None] = "g8h9i0j12345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 运行时读写走 sys_config；顺带回填历史表 sys_system_config（若存在）
    op.execute(
        """
        INSERT INTO sys_config (config_key, config_value, scope, description, status)
        SELECT
            'h5_diagnosis_schedule_runs',
            CAST(GREATEST(1, LEAST(90, CAST(COALESCE(NULLIF(d.config_value, ''), '3') AS UNSIGNED) * 3)) AS CHAR),
            'schedule',
            '真实抓取轮次 1-90',
            1
        FROM (
            SELECT config_value
            FROM sys_config
            WHERE config_key = 'h5_diagnosis_schedule_days'
            LIMIT 1
        ) AS d
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_config WHERE config_key = 'h5_diagnosis_schedule_runs'
        )
        """
    )
    op.execute(
        """
        INSERT INTO sys_config (config_key, config_value, scope, description, status)
        SELECT 'h5_diagnosis_schedule_runs', '9', 'schedule', '真实抓取轮次 1-90', 1
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_config WHERE config_key = 'h5_diagnosis_schedule_runs'
        )
        """
    )
    op.execute(
        """
        INSERT INTO sys_system_config (
            config_key, config_name, config_value, scope, status, remark, deleted
        )
        SELECT
            'h5_diagnosis_schedule_runs',
            'H5 诊断监测次数',
            CAST(GREATEST(1, LEAST(90, CAST(COALESCE(NULLIF(d.config_value, ''), '3') AS UNSIGNED) * 3)) AS CHAR),
            'global',
            1,
            '真实抓取轮次 1-90',
            0
        FROM (
            SELECT config_value
            FROM sys_system_config
            WHERE config_key = 'h5_diagnosis_schedule_days' AND deleted = 0
            LIMIT 1
        ) AS d
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_system_config
            WHERE config_key = 'h5_diagnosis_schedule_runs' AND deleted = 0
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM sys_config WHERE config_key = 'h5_diagnosis_schedule_runs'")
    op.execute(
        "UPDATE sys_system_config SET deleted = 1 WHERE config_key = 'h5_diagnosis_schedule_runs'"
    )
