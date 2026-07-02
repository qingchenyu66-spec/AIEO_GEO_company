"""add knowledge parse fields

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7080910
Create Date: 2026-07-01 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d5e6f7080910"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_knowledge_file",
        sa.Column("parse_status", sa.String(length=20), nullable=False, server_default="none", comment="解析状态"),
    )
    op.add_column(
        "geo_knowledge_file",
        sa.Column("parse_error", sa.String(length=500), nullable=True, comment="解析失败原因"),
    )
    op.add_column(
        "geo_knowledge_file",
        sa.Column("parsed_at", sa.DateTime(), nullable=True, comment="解析完成时间"),
    )
    op.add_column(
        "geo_knowledge_file",
        sa.Column("parse_result_json", sa.JSON(), nullable=True, comment="DeepSeek 解析结果 JSON"),
    )


def downgrade() -> None:
    op.drop_column("geo_knowledge_file", "parse_result_json")
    op.drop_column("geo_knowledge_file", "parsed_at")
    op.drop_column("geo_knowledge_file", "parse_error")
    op.drop_column("geo_knowledge_file", "parse_status")
