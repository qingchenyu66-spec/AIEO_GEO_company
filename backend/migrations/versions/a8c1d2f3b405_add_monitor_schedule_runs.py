"""add monitor schedule runs

Revision ID: a8c1d2f3b405
Revises: f7a6d3e5b204
Create Date: 2026-06-24 16:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8c1d2f3b405"
down_revision: Union[str, Sequence[str], None] = "f7a6d3e5b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增企业定时监测执行记录表，避免同一调度窗口重复提交。"""
    op.create_table(
        "geo_monitor_schedule_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="调度执行记录ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("schedule_key", sa.String(length=80), nullable=False, comment="调度窗口唯一键，例如20260624-0930"),
        sa.Column("task_id", sa.String(length=64), nullable=True, comment="提交成功后的模力指数主任务ID"),
        sa.Column("status", sa.String(length=32), nullable=False, comment="调度状态：submitted、skipped、failed"),
        sa.Column("prompt_count", sa.Integer(), nullable=False, comment="本次提交问题数量"),
        sa.Column("platform_count", sa.Integer(), nullable=False, comment="本次提交平台数量"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="提交失败原因"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="触发调度的用户ID"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="调度创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="调度更新时间"),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "schedule_key", name="uk_geo_schedule_tenant_key"),
        comment="企业定时监测执行记录表",
    )
    op.create_index(op.f("ix_geo_monitor_schedule_run_created_by"), "geo_monitor_schedule_run", ["created_by"], unique=False)
    op.create_index(op.f("ix_geo_monitor_schedule_run_status"), "geo_monitor_schedule_run", ["status"], unique=False)
    op.create_index(op.f("ix_geo_monitor_schedule_run_task_id"), "geo_monitor_schedule_run", ["task_id"], unique=False)
    op.create_index(op.f("ix_geo_monitor_schedule_run_tenant_id"), "geo_monitor_schedule_run", ["tenant_id"], unique=False)


def downgrade() -> None:
    """回滚企业定时监测执行记录表。"""
    op.drop_index(op.f("ix_geo_monitor_schedule_run_tenant_id"), table_name="geo_monitor_schedule_run")
    op.drop_index(op.f("ix_geo_monitor_schedule_run_task_id"), table_name="geo_monitor_schedule_run")
    op.drop_index(op.f("ix_geo_monitor_schedule_run_status"), table_name="geo_monitor_schedule_run")
    op.drop_index(op.f("ix_geo_monitor_schedule_run_created_by"), table_name="geo_monitor_schedule_run")
    op.drop_table("geo_monitor_schedule_run")
