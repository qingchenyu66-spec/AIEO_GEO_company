from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GeoPlatform(Base):
    """模型平台配置——管理各AI平台的名称、图标、访问方式和状态。"""

    __tablename__ = "geo_platform"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="平台ID")
    platform_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False, comment="平台编码")
    platform_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="平台名称")
    platform_icon: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="平台图标URL")
    access_type: Mapped[str] = mapped_column(String(30), default="api", nullable=False, comment="访问方式: api/web/embedded")
    api_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="API端点")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序权重")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="平台描述")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")


class AlertThreshold(Base):
    """预警阈值配置——配置各监控指标的预警和告警阈值。"""

    __tablename__ = "geo_alert_threshold"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="阈值配置ID")
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=True, comment="所属企业ID，NULL表示全局默认")
    metric_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False, comment="指标类型: sentiment_score/mention_count/ranking/health_score")
    threshold_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="阈值名称")
    warning_value: Mapped[str] = mapped_column(String(50), nullable=False, comment="预警阈值")
    critical_value: Mapped[str] = mapped_column(String(50), nullable=False, comment="严重告警阈值")
    unit: Mapped[str] = mapped_column(String(20), default="", nullable=False, comment="单位")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    updated_by: Mapped[str | None] = mapped_column(String(80), nullable=True, comment="最后更新人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
