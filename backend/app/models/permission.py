from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Menu(Base):
    """系统菜单资源，所有前端可配置菜单都从这里读取。"""

    __tablename__ = "sys_menu"
    __table_args__ = (UniqueConstraint("menu_code", name="uk_sys_menu_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="菜单主键ID")
    menu_code: Mapped[str] = mapped_column(String(80), nullable=False, comment="菜单唯一编码")
    menu_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="菜单显示名称")
    identity_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="适用身份类型：PLATFORM平台端，CUSTOMER客户端")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sys_menu.id"), index=True, nullable=True, comment="父级菜单ID，一级菜单为空")
    route_path: Mapped[str] = mapped_column(String(120), nullable=False, comment="前端路由或页面锚点")
    icon: Mapped[str] = mapped_column(String(50), nullable=False, comment="前端图标标识")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值，越小越靠前")
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否在左侧菜单展示")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")


class Role(Base):
    """系统角色，角色决定默认菜单集合和基础数据范围。"""

    __tablename__ = "sys_role"
    __table_args__ = (UniqueConstraint("role_code", name="uk_sys_role_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="角色主键ID")
    role_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色唯一编码")
    role_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="角色显示名称")
    identity_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="适用身份类型：PLATFORM平台端，CUSTOMER客户端")
    data_scope: Mapped[str] = mapped_column(String(20), default="SELF", nullable=False, comment="数据范围：ALL全部，TENANT本企业，SELF本人创建")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="角色说明")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")


class RoleMenu(Base):
    """角色默认菜单，新增身份时可直接继承这一组菜单。"""

    __tablename__ = "sys_role_menu"
    __table_args__ = (UniqueConstraint("role_id", "menu_id", name="uk_sys_role_menu"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="角色菜单主键ID")
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_role.id"), index=True, nullable=False, comment="角色ID")
    menu_id: Mapped[int] = mapped_column(ForeignKey("sys_menu.id"), index=True, nullable=False, comment="菜单ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")


class Position(Base):
    """业务职位，新增用户时从这里选择，例如运营、销售、交付。"""

    __tablename__ = "sys_position"
    __table_args__ = (UniqueConstraint("position_code", name="uk_sys_position_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="职位ID")
    position_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="职位编码")
    position_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="职位名称")
    identity_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="适用身份：PLATFORM/CUSTOMER")
    role_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="默认角色编码")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="职位说明")
    # 2026-07-30 - 平台范围细到单端 - 多选下拉存码；空且有编辑权=全不能勾
    allowed_monitor_platforms_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="可配置监测平台码列表",
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")


class PositionMenu(Base):
    """职位默认菜单和动作权限，选职位时自动带出。"""

    __tablename__ = "sys_position_menu"
    __table_args__ = (UniqueConstraint("position_id", "menu_id", name="uk_sys_position_menu"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="职位菜单ID")
    position_id: Mapped[int] = mapped_column(ForeignKey("sys_position.id"), index=True, nullable=False, comment="职位ID")
    menu_id: Mapped[int] = mapped_column(ForeignKey("sys_menu.id"), index=True, nullable=False, comment="菜单ID")
    can_create: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许新建")
    can_update: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许编辑")
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许删除或停用")
    can_export: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否允许导出")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")


class CustomerPosition(Base):
    """客户侧职位模板（与 sys_position 分表，credit 企业成员用）。"""

    __tablename__ = "sys_customer_position"
    __table_args__ = (UniqueConstraint("tenant_id", "position_code", name="uk_customer_position_tenant_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_tenant.id"),
        index=True,
        nullable=True,
        comment="NULL=平台种子模板；非 NULL=该企业专属",
    )
    position_code: Mapped[str] = mapped_column(String(50), nullable=False)
    position_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_system_template: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)


class CustomerPositionMenu(Base):
    """客户职位默认菜单权限。"""

    __tablename__ = "sys_customer_position_menu"
    __table_args__ = (UniqueConstraint("position_id", "menu_id", name="uk_customer_position_menu"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("sys_customer_position.id"), index=True, nullable=False)
    menu_id: Mapped[int] = mapped_column(ForeignKey("sys_menu.id"), index=True, nullable=False)
    can_create: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_update: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_export: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class UserIdentityMenu(Base):
    """某个登录身份实际拥有的菜单和动作权限。"""

    __tablename__ = "sys_user_identity_menu"
    __table_args__ = (UniqueConstraint("identity_id", "menu_id", name="uk_sys_identity_menu"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="身份菜单主键ID")
    identity_id: Mapped[int] = mapped_column(ForeignKey("sys_user_identity.id"), index=True, nullable=False, comment="用户身份ID")
    menu_id: Mapped[int] = mapped_column(ForeignKey("sys_menu.id"), index=True, nullable=False, comment="菜单ID")
    can_create: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许新建")
    can_update: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许编辑")
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许删除或禁用")
    can_export: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否允许导出")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
