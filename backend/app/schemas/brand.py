from pydantic import BaseModel, Field


class BrandAssetSaveRequest(BaseModel):
    """保存企业品牌资产配置。"""

    tenant_id: int | None = None
    company_full_name: str = Field(min_length=2, max_length=150)
    brand_name: str = Field(min_length=1, max_length=100)
    brand_short_name: str | None = Field(default=None, max_length=100)
    monitor_keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    product_keywords: list[str] = Field(default_factory=list)
    official_url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    schedule_type: str = Field(default="daily_times", pattern="^(daily_times|fixed_times|weekly|monthly)$")
    schedule_times: list[str] = Field(default_factory=lambda: ["09:30", "14:30", "20:30"])
    schedule_frequency: int = Field(default=3, ge=1, le=24)
    schedule_weekdays: list[int] = Field(default_factory=list)
    schedule_month_days: list[int] = Field(default_factory=list)


class CompetitorSaveRequest(BaseModel):
    """保存企业竞品配置。"""

    tenant_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    short_name: str | None = Field(default=None, max_length=100)
    aliases: list[str] = Field(default_factory=list)
    website_url: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default="直接竞品", max_length=50)
