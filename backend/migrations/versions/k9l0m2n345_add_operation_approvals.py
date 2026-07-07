"""add operation approval queue

Revision ID: k9l0m2n345
Revises: j8k9l0m1n234
Create Date: 2026-07-07 09:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k9l0m2n345"
down_revision: Union[str, Sequence[str], None] = "j8k9l0m1n234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPROVER_POSITIONS = ("PLATFORM_ADMIN", "PLATFORM_OPERATION")


def upgrade() -> None:
    op.create_table(
        "sys_operation_approval",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="审批单ID"),
        sa.Column("operation_key", sa.String(length=80), nullable=False, comment="操作编码"),
        sa.Column("module", sa.String(length=40), nullable=False, comment="业务模块"),
        sa.Column("action", sa.String(length=20), nullable=False, comment="动作类型"),
        sa.Column("summary", sa.String(length=255), nullable=False, comment="摘要"),
        sa.Column("tenant_id", sa.Integer(), nullable=True, comment="关联企业ID"),
        sa.Column("target_id", sa.Integer(), nullable=True, comment="目标资源ID"),
        sa.Column("payload_json", sa.JSON(), nullable=False, comment="请求参数JSON"),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False, comment="pending/approved/rejected"),
        sa.Column("requester_user_id", sa.Integer(), nullable=False, comment="申请人用户ID"),
        sa.Column("requester_identity_id", sa.Integer(), nullable=False, comment="申请人身份ID"),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True, comment="审批人用户ID"),
        sa.Column("reviewer_identity_id", sa.Integer(), nullable=True, comment="审批人身份ID"),
        sa.Column("review_comment", sa.String(length=500), nullable=True, comment="审批意见"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审批时间"),
        sa.Column("executed_result_json", sa.JSON(), nullable=True, comment="执行结果JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="逻辑删除"),
        sa.ForeignKeyConstraint(["requester_identity_id"], ["sys_user_identity.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["reviewer_identity_id"], ["sys_user_identity.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sys_operation_approval_operation_key", "sys_operation_approval", ["operation_key"])
    op.create_index("ix_sys_operation_approval_status", "sys_operation_approval", ["status"])
    op.create_index("ix_sys_operation_approval_tenant_id", "sys_operation_approval", ["tenant_id"])
    op.create_index("ix_sys_operation_approval_requester_user_id", "sys_operation_approval", ["requester_user_id"])
    op.create_index("ix_sys_operation_approval_requester_identity_id", "sys_operation_approval", ["requester_identity_id"])
    op.create_index("ix_sys_operation_approval_deleted", "sys_operation_approval", ["deleted"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO sys_menu (menu_code, menu_name, identity_type, parent_id, route_path, icon, sort_order, is_visible, status, deleted)
            VALUES ('platform.approvals', '操作审批', 'PLATFORM', NULL, '/platform/approvals', 'ClipboardCheck', 15, 1, 1, 0)
            ON DUPLICATE KEY UPDATE menu_name=VALUES(menu_name), route_path=VALUES(route_path), is_visible=1, status=1, deleted=0
            """
        )
    )
    menu_id = bind.execute(sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.approvals' AND deleted=0")).scalar()
    positions = bind.execute(
        sa.text("SELECT id FROM sys_position WHERE position_code IN ('PLATFORM_ADMIN','PLATFORM_OPERATION','PLATFORM_SALES') AND deleted=0")
    ).scalars().all()
    for position_id in positions:
        writable = bind.execute(
            sa.text("SELECT position_code FROM sys_position WHERE id=:id"),
            {"id": position_id},
        ).scalar()
        can_update = 1 if writable in APPROVER_POSITIONS else 0
        bind.execute(
            sa.text(
                """
                INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
                VALUES (:position_id, :menu_id, 0, :can_update, 0, 1)
                ON DUPLICATE KEY UPDATE can_export=1, can_update=GREATEST(can_update, :can_update)
                """
            ),
            {"position_id": position_id, "menu_id": menu_id, "can_update": can_update},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE sys_menu SET deleted=1 WHERE menu_code='platform.approvals'"))
    op.drop_index("ix_sys_operation_approval_deleted", table_name="sys_operation_approval")
    op.drop_index("ix_sys_operation_approval_requester_identity_id", table_name="sys_operation_approval")
    op.drop_index("ix_sys_operation_approval_requester_user_id", table_name="sys_operation_approval")
    op.drop_index("ix_sys_operation_approval_tenant_id", table_name="sys_operation_approval")
    op.drop_index("ix_sys_operation_approval_status", table_name="sys_operation_approval")
    op.drop_index("ix_sys_operation_approval_operation_key", table_name="sys_operation_approval")
    op.drop_table("sys_operation_approval")
