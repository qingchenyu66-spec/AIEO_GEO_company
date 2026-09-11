from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.region_catalog import normalize_region_codes
from app.schemas.monitor import FAST_MONITOR_MODE, MonitorMode, ScreenshotMode
from app.services.platform_selection import normalize_platform_selections


class PlatformSelectionRequest(BaseModel):
    """词组勾选平台时绑定模力 mode / screenshot。"""

    code: str = Field(min_length=2, max_length=50)
    mode: MonitorMode = FAST_MONITOR_MODE
    screenshot: ScreenshotMode = 1


class BrandKeywordGroupSaveRequest(BaseModel):
    """保存企业监测词组：多个监测关键词绑定多个露出词。"""

    id: int | None = None
    name: str | None = Field(default=None, max_length=100)
    monitor_keyword: str | None = Field(default=None, max_length=150)
    monitor_keywords: list[str] = Field(default_factory=list)
    exposure_terms: list[str] = Field(default_factory=list)
    # 兼容旧前端传 string[]；新前端传 PlatformSelectionRequest[]
    platforms: list[str | PlatformSelectionRequest | dict] = Field(default_factory=list)
    sort_order: int = 0
    status: bool = True

    @field_validator("platforms", mode="before")
    @classmethod
    def coerce_platforms(cls, value: object) -> list:
        if not isinstance(value, list):
            return []
        return normalize_platform_selections(value)


class BrandWordGroupSaveRequest(BaseModel):
    """保存企业品牌词组：品牌词 + 平台 + 运行时间（无露出词）。"""

    id: int | None = None
    name: str | None = Field(default=None, max_length=100)
    monitor_keyword: str | None = Field(default=None, max_length=150)
    monitor_keywords: list[str] = Field(default_factory=list)
    platforms: list[str | PlatformSelectionRequest | dict] = Field(default_factory=list)
    run_mode: str = Field(default="once", pattern="^(once|weekly)$")
    run_immediately: bool = False
    sort_order: int = 0
    status: bool = True

    @field_validator("platforms", mode="before")
    @classmethod
    def coerce_platforms(cls, value: object) -> list:
        if not isinstance(value, list):
            return []
        return normalize_platform_selections(value)


class BrandWordGroupsSaveRequest(BaseModel):
    """批量保存企业品牌词配置。"""

    tenant_id: int | None = None
    groups: list[BrandWordGroupSaveRequest] = Field(default_factory=list)


class CompetitorSaveRequest(BaseModel):
    """保存企业竞品配置。"""

    tenant_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    short_name: str | None = Field(default=None, max_length=100)
    aliases: list[str] = Field(default_factory=list)
    website_url: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default="直接竞品", max_length=50)


class BrandAssetSaveRequest(BaseModel):
    """保存企业品牌资产配置。"""

    tenant_id: int | None = None
    # 2026-08-18 - 新增企业草稿无 tenant_id；保存时带服务期一并建企业
    service_start_date: date | None = None
    service_end_date: date | None = None
    billing_mode: str = Field(default="hosted", pattern="^(hosted|credit)$")
    # 起步算力选填；有值才在新建保存时充值
    opening_credit_amount: Decimal | None = Field(default=None, ge=0)
    # 2026-09-01 - 商品卡按企业开通；仅资料可编辑时写入
    goods_card_enabled: bool | None = None
    company_full_name: str = Field(min_length=2, max_length=150)
    brand_name: str = Field(min_length=1, max_length=100)
    brand_short_name: str | None = Field(default=None, max_length=100)
    monitor_keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    product_keywords: list[str] = Field(default_factory=list)
    monitored_platforms: list[str] = Field(default_factory=list)
    keyword_groups: list[BrandKeywordGroupSaveRequest] = Field(default_factory=list)
    brand_word_groups: list[BrandWordGroupSaveRequest] = Field(default_factory=list)
    competitors: list[CompetitorSaveRequest] = Field(default_factory=list)
    region_codes: list[str] = Field(default_factory=list, max_length=34)

    @field_validator("region_codes")
    @classmethod
    def validate_region_codes(cls, value: list[str]) -> list[str]:
        return normalize_region_codes(value)
    official_url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    schedule_type: str = Field(default="daily_times", pattern="^(daily_times|fixed_times|weekly|monthly)$")
    # 2026-09-09 - 新建企业监测计划默认空，由运营自行配置场次
    schedule_times: list[str] = Field(default_factory=list)
    schedule_frequency: int = Field(default=1, ge=1, le=24)
    schedule_weekdays: list[int] = Field(default_factory=list)
    schedule_month_days: list[int] = Field(default_factory=list)
    # 2026-08-25 - Logo 随企业资料进审批 - 先传暂存，审批通过后再落库
    logo_staging_key: str | None = Field(default=None, max_length=64)
    # 2026-09-01 - 商品卡开通（仅平台企业管理可写；客户写口忽略）
    goods_card_enabled: bool | None = None

