from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KnowledgeFile(Base):
    """企业知识库原文件记录，只保存文件和元信息，不做文档解析。"""

    __tablename__ = "geo_knowledge_file"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="知识库文件ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    uploader_user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=False, comment="上传用户ID")
    original_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="存储文件名")
    file_ext: Mapped[str] = mapped_column(String(20), nullable=False, comment="文件扩展名")
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True, comment="文件MIME类型")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="文件大小字节")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="本地存储相对路径")
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False, comment="文件状态：uploaded已上传")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
