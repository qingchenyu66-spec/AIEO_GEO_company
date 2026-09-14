"""desensitize molizhishu Chinese display copy

Revision ID: o1p2q3r45678
Revises: n0o1p2q34567
Create Date: 2026-09-14

2026-09-14 - 运营可见「模力」展示名脱敏：预警规则、系统配置、站内通知
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "o1p2q3r45678"
down_revision: Union[str, Sequence[str], None] = "n0o1p2q34567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE geo_alert_threshold
        SET threshold_name = REPLACE(threshold_name, '模力账户余额', '账户余额')
        WHERE threshold_name LIKE '%模力%'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE geo_alert_threshold
        SET threshold_name = TRIM(REPLACE(threshold_name, '模力', ''))
        WHERE threshold_name LIKE '%模力%'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_system_config
        SET config_name = '监测子任务成本(元)',
            remark = REPLACE(REPLACE(COALESCE(remark, ''), '模力调价', '监测调价'), '模力', '监测')
        WHERE config_key = 'platform_molizhishu_yuan_per_subtask'
          AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE geo_system_notification
        SET title = REPLACE(REPLACE(title, '模力余额不足', '监测账户余额不足'), '模力', '监测'),
            message = REPLACE(REPLACE(message, '模力账户余额', '监测账户余额'), '模力', '监测')
        WHERE title LIKE '%模力%' OR message LIKE '%模力%'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE geo_tenant_credit_ledger
        SET reason = '监测未计费释放预扣'
        WHERE reason = '模力未计费释放预扣'
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        UPDATE geo_alert_threshold
        SET threshold_name = '模力账户余额预警'
        WHERE metric_type = 'molizhishu_balance'
          AND threshold_name = '账户余额预警'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_system_config
        SET config_name = '模力子任务成本(元)',
            remark = '下一窗真金预估=子任务数×本值；模力调价后在此同步'
        WHERE config_key = 'platform_molizhishu_yuan_per_subtask'
          AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE geo_tenant_credit_ledger
        SET reason = '模力未计费释放预扣'
        WHERE reason = '监测未计费释放预扣'
        """
    )
