"""系统公告与用户确认。"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Announcement(Base):
    __tablename__ = "geo_announcement"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="标题")
    # 2026-07-28 - 公告粘贴截图易超 TEXT 64KB - MySQL 用 MEDIUMTEXT
    body_html: Mapped[str] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"),
        nullable=False,
        comment="富文本 HTML",
    )
    # targets: platform_all / customer_all / customer_tenants（可多选；后两者互斥）
    targets_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="受众目标列表")
    tenant_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="指定企业 ID 列表")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True, comment="draft/scheduled/published/off"
    )
    publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True, comment="计划/实际上线时间")
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True, comment="失效时间")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AnnouncementAck(Base):
    __tablename__ = "geo_announcement_ack"
    __table_args__ = (UniqueConstraint("user_id", "announcement_id", name="uq_geo_announcement_ack"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=False)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("geo_announcement.id"), index=True, nullable=False)
    acked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AnnouncementMedia(Base):
    """公告本地上传的图片/附件。"""

    __tablename__ = "geo_announcement_media"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uploader_user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(64), nullable=False)
    file_ext: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="file", comment="image/file")
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
