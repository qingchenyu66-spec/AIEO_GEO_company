"""add geo monitor tasks

Revision ID: 9b8c2d7e4f10
Revises: f3164d1c8a72
Create Date: 2026-06-23 11:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9b8c2d7e4f10"
down_revision: Union[str, Sequence[str], None] = "f3164d1c8a72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 GEO 监控任务、子任务结果和回调事件表。"""
    op.create_table(
        "geo_monitor_task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="本地主任务ID"),
        sa.Column("task_id", sa.String(length=64), nullable=False, comment="模力指数主任务ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=True, comment="所属企业ID"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人用户ID"),
        sa.Column("monitor_keywords", sa.String(length=255), nullable=True, comment="监控品牌或关键词"),
        sa.Column("status", sa.String(length=32), nullable=False, comment="主任务状态"),
        sa.Column("total_items", sa.Integer(), nullable=False, comment="子任务总数"),
        sa.Column("completed_items", sa.Integer(), nullable=False, comment="已完成子任务数"),
        sa.Column("failed_items", sa.Integer(), nullable=False, comment="失败子任务数"),
        sa.Column("prompts_json", sa.JSON(), nullable=False, comment="提交的问题列表JSON"),
        sa.Column("platforms_json", sa.JSON(), nullable=False, comment="提交的平台配置JSON"),
        sa.Column("region_code_json", sa.JSON(), nullable=True, comment="提交的地区编码JSON"),
        sa.Column("callback_url", sa.String(length=500), nullable=True, comment="本次任务回调地址"),
        sa.Column("poll_url", sa.String(length=500), nullable=True, comment="远端轮询地址"),
        sa.Column("remote_created_at", sa.BigInteger(), nullable=True, comment="远端创建时间毫秒时间戳"),
        sa.Column("remote_completed_at", sa.BigInteger(), nullable=True, comment="远端完成时间毫秒时间戳"),
        sa.Column("raw_request_json", sa.JSON(), nullable=False, comment="提交给模力指数的原始请求JSON"),
        sa.Column("raw_response_json", sa.JSON(), nullable=False, comment="模力指数提交任务原始响应JSON"),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最近一次同步或提交错误"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="本地创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="本地更新时间"),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uk_geo_monitor_task_id"),
        comment="GEO监控主任务表",
    )
    op.create_index(op.f("ix_geo_monitor_task_created_by"), "geo_monitor_task", ["created_by"], unique=False)
    op.create_index(op.f("ix_geo_monitor_task_deleted"), "geo_monitor_task", ["deleted"], unique=False)
    op.create_index(op.f("ix_geo_monitor_task_status"), "geo_monitor_task", ["status"], unique=False)
    op.create_index(op.f("ix_geo_monitor_task_task_id"), "geo_monitor_task", ["task_id"], unique=True)
    op.create_index(op.f("ix_geo_monitor_task_tenant_id"), "geo_monitor_task", ["tenant_id"], unique=False)

    op.create_table(
        "geo_monitor_subtask",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="本地子任务ID"),
        sa.Column("subtask_id", sa.String(length=64), nullable=False, comment="模力指数子任务ID"),
        sa.Column("task_id", sa.String(length=64), nullable=False, comment="模力指数主任务ID"),
        sa.Column("platform", sa.String(length=50), nullable=False, comment="AI平台编码"),
        sa.Column("mode", sa.String(length=50), nullable=False, comment="监控模式"),
        sa.Column("prompt", sa.Text(), nullable=False, comment="检测问题"),
        sa.Column("status", sa.String(length=32), nullable=False, comment="子任务状态"),
        sa.Column("remote_time", sa.BigInteger(), nullable=True, comment="远端完成时间毫秒时间戳"),
        sa.Column("page_screenshot", sa.String(length=1000), nullable=True, comment="网页快照或截图URL"),
        sa.Column("answer_content", sa.Text(), nullable=True, comment="AI回答原文"),
        sa.Column("reference_list_json", sa.JSON(), nullable=True, comment="全部引用来源JSON"),
        sa.Column("citation_list_json", sa.JSON(), nullable=True, comment="真实引用来源JSON"),
        sa.Column("reasoning_process_json", sa.JSON(), nullable=True, comment="推理过程JSON"),
        sa.Column("recommended_questions_json", sa.JSON(), nullable=True, comment="推荐追问JSON"),
        sa.Column("media_content_json", sa.JSON(), nullable=True, comment="媒体内容JSON"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="子任务失败原因"),
        sa.Column("proxy_ip", sa.String(length=64), nullable=True, comment="执行代理IP"),
        sa.Column("amount", sa.Numeric(precision=10, scale=4), nullable=True, comment="本子任务扣费金额"),
        sa.Column("mention_position", sa.Integer(), nullable=True, comment="监控词提及位置"),
        sa.Column("mention_context", sa.Text(), nullable=True, comment="监控词提及上下文"),
        sa.Column("sentiment", sa.String(length=32), nullable=True, comment="情感倾向"),
        sa.Column("competitor_rankings_json", sa.JSON(), nullable=True, comment="竞品排名JSON"),
        sa.Column("all_rankings_json", sa.JSON(), nullable=True, comment="全部品牌排名JSON"),
        sa.Column("raw_result_json", sa.JSON(), nullable=False, comment="子任务原始结果JSON"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="本地更新时间"),
        sa.ForeignKeyConstraint(["task_id"], ["geo_monitor_task.task_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subtask_id", name="uk_geo_monitor_subtask_id"),
        comment="GEO监控子任务结果表",
    )
    op.create_index(op.f("ix_geo_monitor_subtask_platform"), "geo_monitor_subtask", ["platform"], unique=False)
    op.create_index(op.f("ix_geo_monitor_subtask_status"), "geo_monitor_subtask", ["status"], unique=False)
    op.create_index(op.f("ix_geo_monitor_subtask_task_id"), "geo_monitor_subtask", ["task_id"], unique=False)

    op.create_table(
        "geo_monitor_callback_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="回调事件ID"),
        sa.Column("task_id", sa.String(length=64), nullable=False, comment="模力指数主任务ID"),
        sa.Column("payload_hash", sa.String(length=64), nullable=False, comment="回调内容SHA256哈希"),
        sa.Column("process_status", sa.String(length=32), nullable=False, comment="处理状态"),
        sa.Column("payload_json", sa.JSON(), nullable=False, comment="回调原始JSON"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="处理失败原因"),
        sa.Column("received_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="接收时间"),
        sa.Column("processed_at", sa.DateTime(), nullable=True, comment="处理完成时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payload_hash", name="uk_geo_callback_payload_hash"),
        comment="GEO模力回调事件表",
    )
    op.create_index(op.f("ix_geo_monitor_callback_event_task_id"), "geo_monitor_callback_event", ["task_id"], unique=False)


def downgrade() -> None:
    """回滚 GEO 监控任务相关表。"""
    op.drop_index(op.f("ix_geo_monitor_callback_event_task_id"), table_name="geo_monitor_callback_event")
    op.drop_table("geo_monitor_callback_event")
    op.drop_index(op.f("ix_geo_monitor_subtask_task_id"), table_name="geo_monitor_subtask")
    op.drop_index(op.f("ix_geo_monitor_subtask_status"), table_name="geo_monitor_subtask")
    op.drop_index(op.f("ix_geo_monitor_subtask_platform"), table_name="geo_monitor_subtask")
    op.drop_table("geo_monitor_subtask")
    op.drop_index(op.f("ix_geo_monitor_task_tenant_id"), table_name="geo_monitor_task")
    op.drop_index(op.f("ix_geo_monitor_task_task_id"), table_name="geo_monitor_task")
    op.drop_index(op.f("ix_geo_monitor_task_status"), table_name="geo_monitor_task")
    op.drop_index(op.f("ix_geo_monitor_task_deleted"), table_name="geo_monitor_task")
    op.drop_index(op.f("ix_geo_monitor_task_created_by"), table_name="geo_monitor_task")
    op.drop_table("geo_monitor_task")
