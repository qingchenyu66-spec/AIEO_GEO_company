"""add geo_monitor_task.purpose for brand_word isolation

Revision ID: b6c7d8e0123
Revises: a5b6c7d9012
Create Date: 2026-07-21 11:25:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e0123"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d9012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_monitor_task",
        sa.Column(
            "purpose",
            sa.String(length=32),
            server_default="geo",
            nullable=False,
            comment="任务用途：geo日常监测 / brand_word品牌词分析",
        ),
    )
    op.create_index("ix_geo_monitor_task_purpose", "geo_monitor_task", ["purpose"])
    # 回填：调度 key 以 bw 开头的已提交任务标为品牌词
    op.execute(
        """
        UPDATE geo_monitor_task t
        INNER JOIN geo_monitor_schedule_run r ON r.task_id = t.task_id
        SET t.purpose = 'brand_word'
        WHERE r.schedule_key LIKE 'bw%%'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_geo_monitor_task_purpose", table_name="geo_monitor_task")
    op.drop_column("geo_monitor_task", "purpose")
