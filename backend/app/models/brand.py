from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BrandAsset(Base):
    """企业品牌资产配置，检测任务默认从这里读取主品牌和别名。"""

    __tablename__ = "geo_brand_asset"
    __table_args__ = (UniqueConstraint("tenant_id", name="uk_geo_brand_asset_tenant"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="品牌资产ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    company_full_name: Mapped[str] = mapped_column(String(150), nullable=False, comment="企业全称")
    brand_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="品牌主词")
    brand_short_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="企业或品牌简称")
    monitor_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="监控词列表JSON")
    aliases_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="品牌别名和简称JSON")
    product_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="产品词或业务词JSON")
    official_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="官网或主站URL")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="品牌说明")
    schedule_type: Mapped[str] = mapped_column(String(20), default="daily_times", nullable=False, comment="监测计划类型：daily_times每天几次，fixed_times指定时间，weekly每周，monthly每月")
    schedule_times_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="指定执行时间JSON，例如['09:30','14:30']")
    schedule_frequency: Mapped[int] = mapped_column(default=3, nullable=False, comment="每天执行次数，仅daily_times类型使用")
    schedule_weekdays_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="每周执行星期JSON，1-7代表周一到周日")
    schedule_month_days_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="每月执行日期JSON，1-31")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")


class BrandCompetitor(Base):
    """企业竞品库，提交品牌监控时会转换成模力指数 competitors。"""

    __tablename__ = "geo_brand_competitor"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="竞品ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="竞品名称")
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="竞品简称")
    aliases_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="竞品别名JSON")
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="竞品官网或主链接")
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="竞品类型")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
