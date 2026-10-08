from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="密码变更时间, 更早的登录凭证失效"
    )
    # 2026-10-08 - 不再拦截登录. 列保留, 新建/重置/登录都写成 false
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False, comment="历史强制改密标记, 已停用"
    )
    display_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户姓名")
    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, index=True, nullable=True, comment="登录手机号, 填写后可直接验证码登录"
    )
    phone_login_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False, comment="是否允许用该手机号验证码登录"
    )
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_by: Mapped[int | None] = mapped_column(index=True, nullable=True, comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")

    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="user", cascade="all, delete-orphan")


from app.models.user_identity import UserIdentity  # noqa: E402

