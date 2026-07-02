"""add lead diagnosis tables and platform menu

Revision ID: c4d5e6f70809
Revises: b3c4d5e6f708
Create Date: 2026-07-01 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f70809"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_lead_diagnosis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="售前诊断ID"),
        sa.Column("brand_name", sa.String(length=100), nullable=False, comment="品牌名称"),
        sa.Column("contact_name", sa.String(length=60), nullable=True, comment="联系人姓名"),
        sa.Column("contact_phone", sa.String(length=30), nullable=True, comment="联系电话"),
        sa.Column("contact_note", sa.String(length=500), nullable=True, comment="销售备注"),
        sa.Column("prompts_json", sa.JSON(), nullable=False, comment="检测问题列表，最多5条"),
        sa.Column("competitors_json", sa.JSON(), nullable=False, comment="竞品名称列表"),
        sa.Column("schedule_times_json", sa.JSON(), nullable=False, comment="每日抓取时段"),
        sa.Column("diagnosis_date", sa.Date(), nullable=False, comment="诊断日期"),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False, comment="pending/collecting/ready/failed"),
        sa.Column("health_score", sa.Integer(), nullable=True, comment="健康分0-100"),
        sa.Column("diagnosis_result_json", sa.JSON(), nullable=True, comment="汇总诊断结果"),
        sa.Column("converted_tenant_id", sa.Integer(), nullable=True, comment="转化后的企业ID"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True, comment="创建人用户ID"),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["converted_tenant_id"], ["sys_tenant.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_lead_diagnosis_diagnosis_date", "geo_lead_diagnosis", ["diagnosis_date"])
    op.create_index("ix_geo_lead_diagnosis_status", "geo_lead_diagnosis", ["status"])

    op.create_table(
        "geo_lead_diagnosis_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="抓取记录ID"),
        sa.Column("lead_diagnosis_id", sa.Integer(), nullable=False, comment="所属售前诊断ID"),
        sa.Column("schedule_key", sa.String(length=80), nullable=False, comment="时段唯一键"),
        sa.Column("schedule_label", sa.String(length=40), nullable=False, comment="时段展示名"),
        sa.Column("task_id", sa.String(length=64), nullable=True, comment="模力指数主任务ID"),
        sa.Column("status", sa.String(length=32), nullable=False, comment="pending/submitted/completed/failed/skipped"),
        sa.Column("prompt_count", sa.Integer(), server_default="0", nullable=False, comment="提交问题数"),
        sa.Column("platform_count", sa.Integer(), server_default="0", nullable=False, comment="提交平台数"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["lead_diagnosis_id"], ["geo_lead_diagnosis.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_diagnosis_id", "schedule_key", name="uk_lead_diag_schedule_key"),
    )
    op.create_index("ix_geo_lead_diagnosis_run_lead_diagnosis_id", "geo_lead_diagnosis_run", ["lead_diagnosis_id"])
    op.create_index("ix_geo_lead_diagnosis_run_task_id", "geo_lead_diagnosis_run", ["task_id"])
    op.create_index("ix_geo_lead_diagnosis_run_status", "geo_lead_diagnosis_run", ["status"])

    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT 'platform.lead_diagnosis', '售前诊断', 'PLATFORM', '/platform/lead-diagnosis', 'Stethoscope', 36, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = 'platform.lead_diagnosis'
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            'platform.lead_diagnosis', '售前诊断', 'PLATFORM', 36, 1, 'Stethoscope', '/platform/lead-diagnosis',
            '销售/运营内用：三时段抓取、汇总诊断、导出 PDF', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = 'platform.lead_diagnosis' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_role_menu rm
              WHERE rm.role_id = r.id AND rm.menu_id = m.id
          )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, m.id, 1, 1, 0, 1
        FROM sys_user_identity ui
        JOIN sys_menu m ON m.menu_code = 'platform.lead_diagnosis' AND m.deleted = 0
        WHERE ui.identity_type = 'PLATFORM' AND ui.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_user_identity_menu uim
              WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
          )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = 'platform.lead_diagnosis'
        """
    )
    conn.exec_driver_sql(
        """
        DELETE rm FROM sys_role_menu rm
        JOIN sys_menu m ON m.id = rm.menu_id
        WHERE m.menu_code = 'platform.lead_diagnosis'
        """
    )
    conn.exec_driver_sql("DELETE FROM sys_menu_config WHERE menu_code = 'platform.lead_diagnosis'")
    conn.exec_driver_sql("DELETE FROM sys_menu WHERE menu_code = 'platform.lead_diagnosis'")
    op.drop_index("ix_geo_lead_diagnosis_run_status", table_name="geo_lead_diagnosis_run")
    op.drop_index("ix_geo_lead_diagnosis_run_task_id", table_name="geo_lead_diagnosis_run")
    op.drop_index("ix_geo_lead_diagnosis_run_lead_diagnosis_id", table_name="geo_lead_diagnosis_run")
    op.drop_table("geo_lead_diagnosis_run")
    op.drop_index("ix_geo_lead_diagnosis_status", table_name="geo_lead_diagnosis")
    op.drop_index("ix_geo_lead_diagnosis_diagnosis_date", table_name="geo_lead_diagnosis")
    op.drop_table("geo_lead_diagnosis")
