"""add knowledge files

Revision ID: d21b9a4f6c30
Revises: b5c8f2a1d904
Create Date: 2026-06-24 11:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d21b9a4f6c30"
down_revision: Union[str, Sequence[str], None] = "b5c8f2a1d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建企业知识库原文件表。"""
    op.create_table(
        "geo_knowledge_file",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="知识库文件ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属企业ID"),
        sa.Column("uploader_user_id", sa.Integer(), nullable=False, comment="上传用户ID"),
        sa.Column("original_name", sa.String(length=255), nullable=False, comment="原始文件名"),
        sa.Column("stored_name", sa.String(length=255), nullable=False, comment="存储文件名"),
        sa.Column("file_ext", sa.String(length=20), nullable=False, comment="文件扩展名"),
        sa.Column("content_type", sa.String(length=120), nullable=True, comment="文件MIME类型"),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="文件大小字节"),
        sa.Column("storage_path", sa.String(length=500), nullable=False, comment="本地存储相对路径"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="文件状态：uploaded已上传"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.ForeignKeyConstraint(["uploader_user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="企业知识库原文件表",
    )
    op.create_index(op.f("ix_geo_knowledge_file_deleted"), "geo_knowledge_file", ["deleted"], unique=False)
    op.create_index(op.f("ix_geo_knowledge_file_tenant_id"), "geo_knowledge_file", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_geo_knowledge_file_uploader_user_id"), "geo_knowledge_file", ["uploader_user_id"], unique=False)


def downgrade() -> None:
    """回滚企业知识库原文件表。"""
    op.drop_index(op.f("ix_geo_knowledge_file_uploader_user_id"), table_name="geo_knowledge_file")
    op.drop_index(op.f("ix_geo_knowledge_file_tenant_id"), table_name="geo_knowledge_file")
    op.drop_index(op.f("ix_geo_knowledge_file_deleted"), table_name="geo_knowledge_file")
    op.drop_table("geo_knowledge_file")
