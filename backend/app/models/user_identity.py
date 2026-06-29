from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserIdentity(Base):
    __tablename__ = "sys_user_identity"
    __table_args__ = (UniqueConstraint("identity_code", name="uk_user_identity_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    identity_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="身份唯一编码")
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=False)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("sys_position.id"), index=True, nullable=True, comment="职位ID")
    identity_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="PLATFORM或CUSTOMER")
    identity_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="身份名称")
    role_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色编码")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="默认身份")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")

    user: Mapped["User"] = relationship(back_populates="identities")
    tenant: Mapped["Tenant | None"] = relationship(back_populates="identities")


from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
