"""GEO选词：范例库表、修订字段、选词台/范例库子菜单

Revision ID: u7v8w9x01234
Revises: t6u7v8w90123
Create Date: 2026-09-28 10:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u7v8w9x01234"
down_revision: Union[str, Sequence[str], None] = "t6u7v8w90123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARENT = "platform.keyword_miner"
WORKBENCH = "platform.keyword_miner.workbench"
EXAMPLES = "platform.keyword_miner.examples"


def _insert_child_menu(conn, *, code: str, name: str, route: str, sort_order: int, remark: str) -> None:
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, parent_id,
            sort_order, is_visible, status, deleted
        )
        SELECT
            '{code}', '{name}', 'PLATFORM', '{route}', 'Sparkles', p.id,
            {sort_order}, 0, 1, 0
        FROM sys_menu p
        WHERE p.menu_code = '{PARENT}' AND p.deleted = 0
          AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE menu_code = '{code}')
        LIMIT 1
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{code}', '{name}', 'PLATFORM', {sort_order}, 0, 'Sparkles', '{route}', '{remark}', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{code}' AND deleted = 0
        )
        """
    )


def _copy_grants(conn, *, from_code: str, to_code: str) -> None:
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT rm.role_id, m2.id
        FROM sys_role_menu rm
        JOIN sys_menu m1 ON m1.id = rm.menu_id AND m1.menu_code = '{from_code}' AND m1.deleted = 0
        JOIN sys_menu m2 ON m2.menu_code = '{to_code}' AND m2.deleted = 0
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_role_menu x WHERE x.role_id = rm.role_id AND x.menu_id = m2.id
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
        SELECT pm.position_id, m2.id, pm.can_create, pm.can_update, pm.can_delete, pm.can_export
        FROM sys_position_menu pm
        JOIN sys_menu m1 ON m1.id = pm.menu_id AND m1.menu_code = '{from_code}' AND m1.deleted = 0
        JOIN sys_menu m2 ON m2.menu_code = '{to_code}' AND m2.deleted = 0
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_position_menu x WHERE x.position_id = pm.position_id AND x.menu_id = m2.id
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT uim.identity_id, m2.id, uim.can_create, uim.can_update, uim.can_delete, uim.can_export
        FROM sys_user_identity_menu uim
        JOIN sys_menu m1 ON m1.id = uim.menu_id AND m1.menu_code = '{from_code}' AND m1.deleted = 0
        JOIN sys_menu m2 ON m2.menu_code = '{to_code}' AND m2.deleted = 0
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_user_identity_menu x
            WHERE x.identity_id = uim.identity_id AND x.menu_id = m2.id
        )
        """
    )


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "geo_keyword_miner_job",
        sa.Column("edited_result_json", sa.JSON(), nullable=True, comment="人工修订后的结果 JSON"),
    )
    op.add_column(
        "geo_keyword_miner_job",
        sa.Column("edit_notes_json", sa.JSON(), nullable=True, comment="修订备注/改因列表"),
    )

    op.create_table(
        "geo_keyword_miner_example",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(20), nullable=False, index=True, comment="select/expand"),
        sa.Column("industry", sa.String(80), nullable=False, server_default="", index=True, comment="行业标签"),
        sa.Column("product_tags", sa.JSON(), nullable=True, comment="产品标签"),
        sa.Column("stage", sa.String(40), nullable=False, server_default="", comment="拓词阶段或选词类目"),
        sa.Column("word", sa.String(255), nullable=False, comment="关键词/问法"),
        sa.Column("answer", sa.Text(), nullable=True, comment="拓词答案要点"),
        sa.Column("intent", sa.String(40), nullable=True, comment="选词意图"),
        sa.Column("heat", sa.Integer(), nullable=True, comment="拓词热度"),
        sa.Column("note", sa.String(255), nullable=True, comment="说明"),
        sa.Column("edit_reason", sa.String(500), nullable=True, comment="改因备注"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True, comment="active/disabled"),
        sa.Column("source_job_id", sa.String(64), nullable=True, index=True, comment="来源任务"),
        sa.Column("source_company", sa.String(200), nullable=True, comment="来源企业"),
        sa.Column("source_product", sa.String(200), nullable=True, comment="来源产品"),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True, comment="去重哈希"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0", comment="注入引用次数"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("created_by_identity_id", sa.Integer(), sa.ForeignKey("sys_user_identity.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    _insert_child_menu(
        conn,
        code=WORKBENCH,
        name="选词台",
        route="/platform/keyword-miner/workbench",
        sort_order=37,
        remark="GEO选词工作台(iframe)",
    )
    _insert_child_menu(
        conn,
        code=EXAMPLES,
        name="范例库",
        route="/platform/keyword-miner/examples",
        sort_order=38,
        remark="GEO选词范例库(运营维护)",
    )
    _copy_grants(conn, from_code=PARENT, to_code=WORKBENCH)
    _copy_grants(conn, from_code=PARENT, to_code=EXAMPLES)


def downgrade() -> None:
    conn = op.get_bind()
    for code in (WORKBENCH, EXAMPLES):
        conn.exec_driver_sql(
            f"""
            DELETE uim FROM sys_user_identity_menu uim
            JOIN sys_menu m ON m.id = uim.menu_id WHERE m.menu_code = '{code}'
            """
        )
        conn.exec_driver_sql(
            f"""
            DELETE pm FROM sys_position_menu pm
            JOIN sys_menu m ON m.id = pm.menu_id WHERE m.menu_code = '{code}'
            """
        )
        conn.exec_driver_sql(
            f"""
            DELETE rm FROM sys_role_menu rm
            JOIN sys_menu m ON m.id = rm.menu_id WHERE m.menu_code = '{code}'
            """
        )
        conn.exec_driver_sql(f"DELETE FROM sys_menu_config WHERE menu_code = '{code}'")
        conn.exec_driver_sql(f"DELETE FROM sys_menu WHERE menu_code = '{code}'")

    op.drop_table("geo_keyword_miner_example")
    op.drop_column("geo_keyword_miner_job", "edit_notes_json")
    op.drop_column("geo_keyword_miner_job", "edited_result_json")
