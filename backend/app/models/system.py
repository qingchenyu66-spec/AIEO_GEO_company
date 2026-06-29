from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OperationLog(Base):
    """平台操作审计日志，记录登录、配置、同步、导出、删除等关键动作。"""

    __tablename__ = "sys_operation_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="操作日志ID")
    operator_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="操作人名称")
    action_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True, comment="操作类型")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="操作描述")
    risk_level: Mapped[str] = mapped_column(String(20), default="正常", nullable=False, comment="风险等级：正常、关注、高危")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="操作IP地址")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True, comment="操作时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")


class SystemConfig(Base):
    """系统配置项，承载页面展示、接口、权限、保留周期等平台级参数。"""

    __tablename__ = "sys_system_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="系统配置ID")
    config_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, comment="配置键")
    config_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="配置名称")
    config_value: Mapped[str] = mapped_column(String(500), nullable=False, comment="配置值")
    scope: Mapped[str] = mapped_column(String(120), nullable=False, comment="作用范围")
    status: Mapped[str] = mapped_column(String(20), default="正常", nullable=False, comment="配置状态")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注说明")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
