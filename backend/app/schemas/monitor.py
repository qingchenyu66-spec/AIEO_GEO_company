from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


MonitorMode = Literal["standard", "reasoning", "search", "reasoning_search"]
ScreenshotMode = Literal[0, 1, 2]


class PlatformConfig(BaseModel):
    """提交给模力指数的平台配置。"""

    platform: str = Field(min_length=2, max_length=50)
    mode: MonitorMode = "standard"
    screenshot: ScreenshotMode = 1


class CompetitorBrand(BaseModel):
    """品牌监控中的竞品配置。"""

    name: str = Field(default="", max_length=100)
    aliases: list[str] = Field(default_factory=list)


class MonitorTaskCreateRequest(BaseModel):
    """本地创建 GEO 检测任务的请求体。"""

    tenant_id: int | None = None
    monitor_keywords: str | None = Field(default=None, max_length=255)
    monitor_keyword_aliases: list[str] = Field(default_factory=list)
    competitors: list[CompetitorBrand] = Field(default_factory=list)
    prompts: list[str] = Field(min_length=1, max_length=50)
    platforms: list[PlatformConfig] = Field(min_length=1)
    region_code: list[str] | None = Field(default=None, max_length=1)
    callback_url: HttpUrl | None = None


class MonitorTaskQuery(BaseModel):
    """前端展示用的本地任务摘要。"""

    task_id: str
    status: str
    monitor_keywords: str | None
    total_items: int
    completed_items: int
    failed_items: int
    prompts: list[Any]
    platforms: list[Any]
    created_at: str
    updated_at: str


class MonitorTaskDetail(BaseModel):
    """前端展示用的本地任务详情。"""

    task: dict[str, Any]
    subtasks: list[dict[str, Any]]
