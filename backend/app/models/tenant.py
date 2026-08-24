from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Tenant(Base):
    __tablename__ = "sys_tenant"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="企业名称")
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False, comment="企业编码")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id"), index=True, nullable=True, comment="归属销售/创建人用户ID")
    service_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="服务开始日期")
    service_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="服务结束日期")
    stop_reason: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="停服原因：manual人工停服、canceled未开始取消、expired到期")
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="停服时间")
    stopped_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id"), nullable=True, comment="停服操作人ID")
    logo_path: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="企业 Logo 相对路径")
    logo_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="企业 Logo 更新时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")

    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="tenant")


from app.models.user_identity import UserIdentity  # noqa: E402
