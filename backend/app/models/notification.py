from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemNotification(Base):
    """系统站内通知——运营/客户侧消息中心。"""

    __tablename__ = "geo_system_notification"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="通知ID")
    audience_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="受众: PLATFORM/CUSTOMER")
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=True, comment="企业ID，NULL表示全局")
    category: Mapped[str] = mapped_column(String(40), index=True, nullable=False, comment="分类: celery_queue/monitor/system")
    level: Mapped[str] = mapped_column(String(20), nullable=False, comment="级别: info/warning/critical")
    title: Mapped[str] = mapped_column(String(120), nullable=False, comment="标题")
    message: Mapped[str] = mapped_column(String(500), nullable=False, comment="正文")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="扩展 JSON")
    source_key: Mapped[str] = mapped_column(String(120), index=True, nullable=False, comment="去重键")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间"
    )


class SystemNotificationRead(Base):
    """用户已读记录。"""

    __tablename__ = "geo_system_notification_read"
    __table_args__ = (UniqueConstraint("user_id", "notification_id", name="uq_geo_notification_read"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="记录ID")
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=False, comment="用户ID")
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("geo_system_notification.id"), index=True, nullable=False, comment="通知ID"
    )
    read_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="已读时间")
