"""add geo_keyword_miner_job for platform GEO选词 history

Revision ID: t6u7v8w90123
Revises: s5t6u7v89012
Create Date: 2026-09-24 15:50:00.000000

选词历史落入 GEO 主库 MySQL; keyword-miner 只负责挖掘.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t6u7v8w90123"
down_revision: Union[str, Sequence[str], None] = "s5t6u7v89012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_keyword_miner_job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False, comment="选词服务任务 ID"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="queued",
            comment="queued/running/done/error",
        ),
        sa.Column("company", sa.String(length=200), nullable=False, server_default="", comment="企业名"),
        sa.Column("product", sa.String(length=200), nullable=False, server_default="", comment="产品名"),
        sa.Column("error", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("payload_json", sa.JSON(), nullable=True, comment="提交参数"),
        sa.Column("result_json", sa.JSON(), nullable=True, comment="挖掘结果 JSON"),
        sa.Column("selection_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expansion_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task", sa.String(length=40), nullable=False, server_default="", comment="both/select/expand"),
        sa.Column("platforms_json", sa.JSON(), nullable=True, comment="目标平台列表"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="", comment="demo/llm 等"),
        sa.Column("model", sa.String(length=80), nullable=False, server_default="", comment="模型名"),
        sa.Column("top_words_json", sa.JSON(), nullable=True, comment="Top 关键词"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_identity_id", sa.Integer(), nullable=True),
        sa.Column("job_created_at", sa.DateTime(), nullable=True, comment="任务创建时间"),
        sa.Column("job_updated_at", sa.DateTime(), nullable=True, comment="任务最近更新时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_identity_id"], ["sys_user_identity.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_geo_keyword_miner_job_id"),
    )
    op.create_index("ix_geo_keyword_miner_job_job_id", "geo_keyword_miner_job", ["job_id"])
    op.create_index("ix_geo_keyword_miner_job_status", "geo_keyword_miner_job", ["status"])
    op.create_index("ix_geo_keyword_miner_job_updated", "geo_keyword_miner_job", ["job_updated_at"])
    op.create_index("ix_geo_keyword_miner_job_user", "geo_keyword_miner_job", ["created_by_user_id"])
    op.create_index("ix_geo_keyword_miner_job_identity", "geo_keyword_miner_job", ["created_by_identity_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_keyword_miner_job_identity", table_name="geo_keyword_miner_job")
    op.drop_index("ix_geo_keyword_miner_job_user", table_name="geo_keyword_miner_job")
    op.drop_index("ix_geo_keyword_miner_job_updated", table_name="geo_keyword_miner_job")
    op.drop_index("ix_geo_keyword_miner_job_status", table_name="geo_keyword_miner_job")
    op.drop_index("ix_geo_keyword_miner_job_job_id", table_name="geo_keyword_miner_job")
    op.drop_table("geo_keyword_miner_job")
