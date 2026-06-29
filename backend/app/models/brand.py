from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BrandAsset(Base):
    """企业品牌资产配置。"""

    __tablename__ = "geo_brand_asset"
    __table_args__ = (UniqueConstraint("tenant_id", name="uk_geo_brand_asset_tenant"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="品牌资产ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    company_full_name: Mapped[str] = mapped_column(String(150), nullable=False, comment="企业全称")
    brand_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="品牌主词")
    brand_short_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="企业或品牌简称")
    monitor_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="监测词列表JSON")
    aliases_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="品牌别名和简称JSON")
    product_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="产品词或业务词JSON")
    monitored_platforms_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="已购买或允许监测的平台编码JSON")
    region_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="监测地区编码，空值代表全部区域")
    official_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="官网或主站URL")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="品牌说明")
    schedule_type: Mapped[str] = mapped_column(String(20), default="daily_times", nullable=False, comment="监测计划类型")
    schedule_times_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="指定执行时间JSON")
    schedule_frequency: Mapped[int] = mapped_column(default=3, nullable=False, comment="每天执行次数")
    schedule_weekdays_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="每周执行星期JSON")
    schedule_month_days_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="每月执行日期JSON")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")


class BrandKeywordGroup(Base):
    """企业监测词组：一个监测关键词绑定多个露出词。"""

    __tablename__ = "geo_brand_keyword_group"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="词组ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    brand_asset_id: Mapped[int] = mapped_column(ForeignKey("geo_brand_asset.id"), index=True, nullable=False, comment="品牌资产ID")
    monitor_keyword: Mapped[str] = mapped_column(String(150), nullable=False, comment="监测关键词")
    exposure_terms_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="露出词JSON")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")


class BrandCompetitor(Base):
    """企业竞品库。"""

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
