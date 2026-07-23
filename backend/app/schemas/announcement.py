from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AudienceTarget = Literal["platform_all", "customer_all", "customer_tenants"]
AnnouncementStatus = Literal["draft", "scheduled", "published", "off"]


class AnnouncementUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body_html: str = Field(min_length=1, max_length=200000)
    targets: list[AudienceTarget] = Field(min_length=1)
    tenant_ids: list[int] = Field(default_factory=list)
    publish_at: datetime | None = None
    expire_at: datetime | None = None
    # draft | publish_now | schedule
    action: Literal["draft", "publish_now", "schedule"] = "draft"

    @field_validator("targets")
    @classmethod
    def _unique_targets(cls, value: list[AudienceTarget]) -> list[AudienceTarget]:
        seen: list[AudienceTarget] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        if not seen:
            raise ValueError("请至少选择一个受众")
        return seen

    @model_validator(mode="after")
    def _check_audience(self) -> "AnnouncementUpsertRequest":
        targets = set(self.targets)
        if "customer_all" in targets and "customer_tenants" in targets:
            raise ValueError("「客户全员」与「指定企业」不能同时选择")
        if "customer_tenants" in targets and not self.tenant_ids:
            raise ValueError("指定企业时请选择至少一个企业")
        if self.action == "schedule" and self.publish_at is None:
            raise ValueError("定时发布请填写上线时间")
        if self.expire_at and self.publish_at and self.expire_at <= self.publish_at:
            raise ValueError("失效时间必须晚于上线时间")
        return self


class AnnouncementOut(BaseModel):
    id: int
    title: str
    body_html: str
    targets: list[str]
    tenant_ids: list[int]
    status: str
    publish_at: datetime | None
    expire_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnnouncementPendingOut(BaseModel):
    id: int
    title: str
    body_html: str
    publish_at: datetime | None
