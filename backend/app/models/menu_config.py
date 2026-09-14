from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class MenuConfig(Base):
    """菜单配置表，支持动态调整菜单名称、顺序、可见性"""

    __tablename__ = "sys_menu_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="配置ID")
    menu_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True, comment="菜单编码")
    menu_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="菜单显示名称")
    identity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True,
                                               comment="身份类型：PLATFORM/CUSTOMER")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序权重")
    show_in_sidebar: Mapped[bool] = mapped_column(Boolean, default=True, index=True, comment="是否进侧栏")
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, index=True, comment="功能是否启用")
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="图标名称")
    route_path: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="路由路径")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注说明")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
