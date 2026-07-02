"""add geo report table

Revision ID: f1a2b3c4d5e6
Revises: b4c5d6e7f801
Create Date: 2026-07-01 13:35:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f801"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_report",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="报告ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("report_title", sa.String(length=200), nullable=False, comment="报告标题"),
        sa.Column("report_type", sa.String(length=40), nullable=False, comment="报告类型: diagnosis/periodic/comparison"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="状态: draft/published/archived"),
        sa.Column("data_summary", sa.Text(), nullable=True, comment="数据摘要"),
        sa.Column("report_content_json", sa.JSON(), nullable=True, comment="报告正文JSON"),
        sa.Column("report_url", sa.String(length=500), nullable=True, comment="报告导出链接"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人用户ID"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="GEO 报告中心",
    )
    op.create_index("ix_geo_report_tenant_id", "geo_report", ["tenant_id"])
    op.create_index("ix_geo_report_report_type", "geo_report", ["report_type"])
    op.create_index("ix_geo_report_created_by", "geo_report", ["created_by"])
    op.create_index("ix_geo_report_deleted", "geo_report", ["deleted"])


def downgrade() -> None:
    op.drop_index("ix_geo_report_deleted", table_name="geo_report")
    op.drop_index("ix_geo_report_created_by", table_name="geo_report")
    op.drop_index("ix_geo_report_report_type", table_name="geo_report")
    op.drop_index("ix_geo_report_tenant_id", table_name="geo_report")
    op.drop_table("geo_report")
