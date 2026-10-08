from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    # 2026-10-08 - 不再拦截登录. 列保留, 新建/重置/登录都写成 false
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False, comment="历史强制改密标记, 已停用"
    )
    display_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户姓名")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_by: Mapped[int | None] = mapped_column(index=True, nullable=True, comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")

    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="user", cascade="all, delete-orphan")


from app.models.user_identity import UserIdentity  # noqa: E402

