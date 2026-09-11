"""add credit self-service foundation (Epic A)

Revision ID: w8x9y0z12345
Revises: v7w8x9y01234
Create Date: 2026-08-27

2026-08-27 - 算力自助一期 Epic A - billing_mode/ledger/单价/block/terms/客户职位/菜单种子
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w8x9y0z12345"
down_revision: Union[str, Sequence[str], None] = "v7w8x9y01234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_CREDIT_POLICY = {
    "keyword_limit": 30,
    "schedule_slots_limit": 3,
    "region_limit": 5,
    "daily_credit_cap": None,
    "region_editable": True,
    "credits_per_yuan": 4.2,
    "settle_cell_credit_cap": 2,
}

CUSTOMER_ENTERPRISE_MENUS = [
    ("customer.enterprise_config", "企业配置", "/customer/enterprise", "Building2", 130, True),
    ("customer.enterprise_monitor", "监测配置", "/customer/enterprise/monitor", "Settings", 131, False),
    ("customer.enterprise_members", "成员与权限", "/customer/enterprise/members", "Users", 132, False),
    ("customer.enterprise_credit", "算力中心", "/customer/enterprise/credit", "Coins", 133, False),
    ("customer.enterprise_audit", "操作记录", "/customer/enterprise/audit", "ScrollText", 134, False),
]

PLATFORM_CREDIT_MENUS = [
    ("platform.tenant_credit", "企业算力", "/platform/credit/tenants", "Wallet", 38, True),
    ("platform.tenant_credit_blocks", "提交拦截", "/platform/credit/blocks", "ShieldAlert", 39, True),
    ("platform.credit_ops_board", "算力运营", "/platform/credit/ops", "LayoutDashboard", 40, True),
]

CUSTOMER_POSITION_SEEDS = [
    ("enterprise_admin", "企业管理员", True, 10),
    ("enterprise_configurator", "配置员", True, 20),
    ("enterprise_viewer", "只读成员", True, 30),
]


def _insert_menu(conn, menu_code: str, menu_name: str, identity_type: str, route_path: str, icon: str, sort_order: int, is_visible: bool, parent_code: str | None = None) -> None:
    parent_clause = "NULL"
    if parent_code:
        parent_clause = f"(SELECT id FROM sys_menu WHERE menu_code = '{parent_code}' AND deleted = 0 LIMIT 1)"
    vis = 1 if is_visible else 0
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (menu_code, menu_name, identity_type, parent_id, route_path, icon, sort_order, is_visible, status, deleted)
        SELECT '{menu_code}', '{menu_name}', '{identity_type}', {parent_clause}, '{route_path}', '{icon}', {sort_order}, {vis}, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE menu_code = '{menu_code}' AND deleted = 0)
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted)
        SELECT '{menu_code}', '{menu_name}', '{identity_type}', {sort_order}, {vis}, '{icon}', '{route_path}', '', 0
        FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM sys_menu_config WHERE menu_code = '{menu_code}' AND deleted = 0)
        """
    )


def upgrade() -> None:
    policy_json = json.dumps(DEFAULT_CREDIT_POLICY, ensure_ascii=False)
    op.add_column("sys_tenant", sa.Column("billing_mode", sa.String(length=20), server_default="hosted", nullable=False, comment="hosted 托管 | credit 算力自助"))
    op.add_column("sys_tenant", sa.Column("credit_balance", sa.Numeric(14, 2), server_default="0", nullable=False, comment="可用算力余额"))
    op.add_column("sys_tenant", sa.Column("credit_reserved", sa.Numeric(14, 2), server_default="0", nullable=False, comment="预扣锁定中"))
    op.add_column("sys_tenant", sa.Column("credit_policy_json", sa.JSON(), nullable=True, comment="词数/场次/地区上限等"))
    op.add_column("sys_tenant", sa.Column("platform_whitelist_json", sa.JSON(), server_default=sa.text("(JSON_ARRAY())"), nullable=False, comment="credit 允许监测的平台 code"))
    op.create_index("ix_sys_tenant_billing_mode", "sys_tenant", ["billing_mode"])

    op.add_column(
        "geo_brand_word_group",
        sa.Column("run_immediately", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="保存后是否立即 submit+扣费"),
    )

    op.create_table(
        "sys_customer_position",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True, comment="NULL=平台种子"),
        sa.Column("position_code", sa.String(length=50), nullable=False),
        sa.Column("position_name", sa.String(length=80), nullable=False),
        sa.Column("is_system_template", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "position_code", name="uk_customer_position_tenant_code"),
    )
    op.create_index("ix_sys_customer_position_tenant_id", "sys_customer_position", ["tenant_id"])

    op.create_table(
        "sys_customer_position_menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=False),
        sa.Column("can_create", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("can_update", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("can_delete", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("can_export", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["menu_id"], ["sys_menu.id"]),
        sa.ForeignKeyConstraint(["position_id"], ["sys_customer_position.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_id", "menu_id", name="uk_customer_position_menu"),
    )

    op.add_column(
        "sys_user_identity",
        sa.Column("customer_position_id", sa.Integer(), nullable=True, comment="客户职位ID"),
    )
    op.create_index("ix_sys_user_identity_customer_position_id", "sys_user_identity", ["customer_position_id"])
    op.create_foreign_key(
        "fk_sys_user_identity_customer_position",
        "sys_user_identity",
        "sys_customer_position",
        ["customer_position_id"],
        ["id"],
    )

    op.create_table(
        "geo_tenant_credit_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("entry_type", sa.String(length=20), nullable=False),
        sa.Column("ref_type", sa.String(length=40), nullable=True),
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("platform_code", sa.String(length=50), nullable=True),
        sa.Column("keyword", sa.String(length=200), nullable=True),
        sa.Column("window_key", sa.String(length=32), nullable=True),
        sa.Column("region_key", sa.String(length=80), nullable=True),
        sa.Column("operator_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("reserve_expires_at", sa.DateTime(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["operator_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_tenant_credit_ledger_tenant_id", "geo_tenant_credit_ledger", ["tenant_id"])
    op.create_index("ix_geo_tenant_credit_ledger_entry_type", "geo_tenant_credit_ledger", ["entry_type"])
    op.create_index("ix_geo_tenant_credit_ledger_ref_id", "geo_tenant_credit_ledger", ["ref_id"])
    op.create_index("ix_geo_tenant_credit_ledger_window_key", "geo_tenant_credit_ledger", ["window_key"])

    op.create_table(
        "geo_credit_price_rule",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("platform_code", sa.String(length=50), nullable=True),
        sa.Column("credits_per_subtask", sa.Numeric(10, 4), nullable=False),
        sa.Column("status", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "tenant_id", "platform_code", name="uk_credit_price_rule_scope"),
    )

    op.create_table(
        "geo_credit_submit_block",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("window_key", sa.String(length=32), nullable=False),
        sa.Column("block_reason", sa.String(length=30), nullable=False),
        sa.Column("required_credits", sa.Numeric(14, 2), nullable=True),
        sa.Column("available_credits", sa.Numeric(14, 2), nullable=True),
        sa.Column("platform_balance_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("platform_required_estimate", sa.Numeric(14, 2), nullable=True),
        sa.Column("tenant_notified_at", sa.DateTime(), nullable=True),
        sa.Column("ops_notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_credit_submit_block_tenant_id", "geo_credit_submit_block", ["tenant_id"])
    op.create_index("ix_geo_credit_submit_block_window_key", "geo_credit_submit_block", ["window_key"])
    op.create_index("ix_geo_credit_submit_block_block_reason", "geo_credit_submit_block", ["block_reason"])

    op.create_table(
        "geo_billing_mode_change_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("from_mode", sa.String(length=20), nullable=False),
        sa.Column("to_mode", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("contract_note", sa.String(length=500), nullable=True),
        sa.Column("operator_user_id", sa.Integer(), nullable=False),
        sa.Column("effective_policy", sa.String(length=20), server_default="next_window", nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("credit_balance_action", sa.String(length=20), nullable=True),
        sa.Column("opening_credit_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("daily_estimate_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["operator_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_billing_mode_change_log_tenant_id", "geo_billing_mode_change_log", ["tenant_id"])

    op.create_table(
        "geo_credit_terms_version",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version_code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("notice_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_code"),
    )

    op.create_table(
        "geo_tenant_credit_terms_ack",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("terms_version_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.ForeignKeyConstraint(["terms_version_id"], ["geo_credit_terms_version.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "terms_version_id", name="uk_tenant_credit_terms_ack"),
    )

    conn = op.get_bind()
    conn.exec_driver_sql("UPDATE sys_tenant SET billing_mode = 'hosted' WHERE billing_mode IS NULL OR billing_mode = ''")
    conn.exec_driver_sql(
        f"UPDATE sys_tenant SET credit_policy_json = CAST('{policy_json}' AS JSON) WHERE credit_policy_json IS NULL"
    )

    for code, name, route, icon, sort_order, is_visible in CUSTOMER_ENTERPRISE_MENUS:
        _insert_menu(conn, code, name, "CUSTOMER", route, icon, sort_order, is_visible)
    for code, name, route, icon, sort_order, is_visible in PLATFORM_CREDIT_MENUS:
        _insert_menu(conn, code, name, "PLATFORM", route, icon, sort_order, is_visible)

    conn.exec_driver_sql(
        """
        UPDATE sys_menu child
        JOIN sys_menu parent ON parent.menu_code = 'customer.enterprise_config' AND parent.deleted = 0
        SET child.parent_id = parent.id
        WHERE child.menu_code IN (
            'customer.enterprise_monitor', 'customer.enterprise_members',
            'customer.enterprise_credit', 'customer.enterprise_audit'
        ) AND child.deleted = 0 AND child.parent_id IS NULL
        """
    )

    for pos_code, pos_name, is_template, sort_order in CUSTOMER_POSITION_SEEDS:
        conn.exec_driver_sql(
            f"""
            INSERT INTO sys_customer_position (tenant_id, position_code, position_name, is_system_template, sort_order, status, deleted)
            SELECT NULL, '{pos_code}', '{pos_name}', {1 if is_template else 0}, {sort_order}, 1, 0
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM sys_customer_position
                WHERE tenant_id IS NULL AND position_code = '{pos_code}' AND deleted = 0
            )
            """
        )

    conn.exec_driver_sql(
        """
        INSERT INTO geo_credit_price_rule (scope, tenant_id, platform_code, credits_per_subtask, status)
        SELECT 'global', NULL, NULL, 1.0000, 1 FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM geo_credit_price_rule WHERE scope = 'global' AND tenant_id IS NULL AND platform_code IS NULL
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO geo_credit_price_rule (scope, tenant_id, platform_code, credits_per_subtask, status)
        SELECT 'global', NULL, 'deep_think_addon', 0.5000, 1 FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM geo_credit_price_rule WHERE scope = 'global' AND platform_code = 'deep_think_addon'
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO geo_credit_price_rule (scope, tenant_id, platform_code, credits_per_subtask, status)
        SELECT 'global', NULL, 'chatgpt', 2.0000, 1 FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM geo_credit_price_rule WHERE scope = 'global' AND platform_code = 'chatgpt'
        )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'credit_reserve_ttl_seconds', '预扣 TTL 秒数', '1800', '算力自助', '正常', '预扣超时自动 release', 0 FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'credit_reserve_ttl_seconds' AND deleted = 0)
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'platform_balance_buffer_yuan', '监测账户安全垫', '500', '算力自助', '正常', '下一窗全平台预估 + 缓冲（元）', 0 FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'platform_balance_buffer_yuan' AND deleted = 0)
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_system_config (config_key, config_name, config_value, scope, status, remark, deleted)
        SELECT 'platform_balance_runway_windows', 'Runway 窗数', '1', '算力自助', '正常', '余额至少够 N 窗全平台预估', 0 FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM sys_system_config WHERE config_key = 'platform_balance_runway_windows' AND deleted = 0)
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code IN (
            'platform.tenant_credit', 'platform.tenant_credit_blocks', 'platform.credit_ops_board'
        ) AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (SELECT 1 FROM sys_role_menu rm WHERE rm.role_id = r.id AND rm.menu_id = m.id)
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    for code in (
        "customer.enterprise_audit",
        "customer.enterprise_credit",
        "customer.enterprise_members",
        "customer.enterprise_monitor",
        "customer.enterprise_config",
        "platform.credit_ops_board",
        "platform.tenant_credit_blocks",
        "platform.tenant_credit",
    ):
        conn.exec_driver_sql(f"UPDATE sys_menu SET deleted = 1 WHERE menu_code = '{code}'")
        conn.exec_driver_sql(f"UPDATE sys_menu_config SET deleted = 1 WHERE menu_code = '{code}'")

    op.drop_table("geo_tenant_credit_terms_ack")
    op.drop_table("geo_credit_terms_version")
    op.drop_table("geo_billing_mode_change_log")
    op.drop_table("geo_credit_submit_block")
    op.drop_table("geo_credit_price_rule")
    op.drop_table("geo_tenant_credit_ledger")
    op.drop_table("sys_customer_position_menu")
    op.drop_table("sys_customer_position")

    op.drop_constraint("fk_sys_user_identity_customer_position", "sys_user_identity", type_="foreignkey")
    op.drop_index("ix_sys_user_identity_customer_position_id", table_name="sys_user_identity")
    op.drop_column("sys_user_identity", "customer_position_id")
    op.drop_column("geo_brand_word_group", "run_immediately")

    op.drop_index("ix_sys_tenant_billing_mode", table_name="sys_tenant")
    op.drop_column("sys_tenant", "platform_whitelist_json")
    op.drop_column("sys_tenant", "credit_policy_json")
    op.drop_column("sys_tenant", "credit_reserved")
    op.drop_column("sys_tenant", "credit_balance")
    op.drop_column("sys_tenant", "billing_mode")
