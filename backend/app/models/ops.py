from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OperationLog(Base):
    __table_args__ = {"extend_existing": True}
    __tablename__ = "sys_operation_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="日志ID")
    operator_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="操作人")
    action_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作类型")
    description: Mapped[str] = mapped_column(String(500), nullable=False, comment="操作描述")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="IP地址")
    risk_level: Mapped[str] = mapped_column(String(20), server_default="正常", nullable=False, comment="风险等级")
    target_module: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作模块")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="目标记录ID")
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="所属企业ID")
    operator_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="操作人用户ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="操作时间")


class SystemConfig(Base):
    __table_args__ = {"extend_existing": True}
    __tablename__ = "sys_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="配置ID")
    config_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="配置键")
    config_value: Mapped[str] = mapped_column(String(500), nullable=False, comment="配置值")
    scope: Mapped[str] = mapped_column(String(30), server_default="global", nullable=False, comment="作用范围")
    description: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="配置说明")
    updated_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="最后更新人")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
