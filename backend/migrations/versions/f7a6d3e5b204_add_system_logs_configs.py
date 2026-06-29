"""add system logs configs

Revision ID: f7a6d3e5b204
Revises: e9f4b7c2a901
Create Date: 2026-06-24 15:50:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7a6d3e5b204"
down_revision: Union[str, Sequence[str], None] = "e9f4b7c2a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建操作日志和系统配置表，并写入首批可展示配置。"""
    op.create_table(
        "sys_operation_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="操作日志ID"),
        sa.Column("operator_name", sa.String(length=80), nullable=False, comment="操作人名称"),
        sa.Column("action_type", sa.String(length=60), nullable=False, comment="操作类型"),
        sa.Column("description", sa.Text(), nullable=False, comment="操作描述"),
        sa.Column("risk_level", sa.String(length=20), nullable=False, comment="风险等级：正常、关注、高危"),
        sa.Column("ip_address", sa.String(length=64), nullable=True, comment="操作IP地址"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="操作时间"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.PrimaryKeyConstraint("id"),
        comment="平台操作审计日志表",
    )
    op.create_index(op.f("ix_sys_operation_log_action_type"), "sys_operation_log", ["action_type"], unique=False)
    op.create_index(op.f("ix_sys_operation_log_created_at"), "sys_operation_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_sys_operation_log_deleted"), "sys_operation_log", ["deleted"], unique=False)

    op.create_table(
        "sys_system_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="系统配置ID"),
        sa.Column("config_key", sa.String(length=120), nullable=False, comment="配置键"),
        sa.Column("config_name", sa.String(length=120), nullable=False, comment="配置名称"),
        sa.Column("config_value", sa.String(length=500), nullable=False, comment="配置值"),
        sa.Column("scope", sa.String(length=120), nullable=False, comment="作用范围"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="配置状态"),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注说明"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_key"),
        comment="系统配置项表",
    )
    op.create_index(op.f("ix_sys_system_config_deleted"), "sys_system_config", ["deleted"], unique=False)

    op.bulk_insert(
        sa.table(
            "sys_system_config",
            sa.column("config_key", sa.String),
            sa.column("config_name", sa.String),
            sa.column("config_value", sa.String),
            sa.column("scope", sa.String),
            sa.column("status", sa.String),
            sa.column("remark", sa.String),
            sa.column("deleted", sa.Boolean),
        ),
        [
            {"config_key": "system.name", "config_name": "系统名称", "config_value": "GEO Monitor", "scope": "全局展示名称", "status": "正常", "remark": "登录页和后台顶部展示", "deleted": False},
            {"config_key": "permission.source", "config_name": "菜单权限来源", "config_value": "数据库菜单表", "scope": "用户新增与权限分配", "status": "正常", "remark": "所有菜单入库后再授权", "deleted": False},
            {"config_key": "knowledge.upload_api", "config_name": "数据上传接口", "config_value": "/api/v1/knowledge/files", "scope": "企业知识库原文件上传", "status": "启用", "remark": "只保存文件不解析", "deleted": False},
            {"config_key": "data.retention_days", "config_name": "数据保留周期", "config_value": "90天", "scope": "日志、快照和报告记录", "status": "正常", "remark": "后续可改为按套餐配置", "deleted": False},
        ],
    )

    op.bulk_insert(
        sa.table(
            "sys_operation_log",
            sa.column("operator_name", sa.String),
            sa.column("action_type", sa.String),
            sa.column("description", sa.Text),
            sa.column("risk_level", sa.String),
            sa.column("ip_address", sa.String),
            sa.column("deleted", sa.Boolean),
        ),
        [
            {"operator_name": "平台管理员", "action_type": "系统初始化", "description": "创建操作日志和系统配置模块", "risk_level": "正常", "ip_address": "127.0.0.1", "deleted": False},
            {"operator_name": "系统任务", "action_type": "模力同步", "description": "同步艾迪亚真实监测任务与子任务结果", "risk_level": "正常", "ip_address": "127.0.0.1", "deleted": False},
        ],
    )


def downgrade() -> None:
    """回滚操作日志和系统配置表。"""
    op.drop_index(op.f("ix_sys_system_config_deleted"), table_name="sys_system_config")
    op.drop_table("sys_system_config")
    op.drop_index(op.f("ix_sys_operation_log_deleted"), table_name="sys_operation_log")
    op.drop_index(op.f("ix_sys_operation_log_created_at"), table_name="sys_operation_log")
    op.drop_index(op.f("ix_sys_operation_log_action_type"), table_name="sys_operation_log")
    op.drop_table("sys_operation_log")
