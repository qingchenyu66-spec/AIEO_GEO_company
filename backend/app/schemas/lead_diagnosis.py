from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.lead_diagnosis_prompts import normalize_lead_prompts


LeadDiagnosisStatus = Literal["pending", "collecting", "ready", "failed"]


class LeadDiagnosisCreateRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=100)
    prompts: list[str] = Field(min_length=1, max_length=5)
    competitors: list[str] = Field(default_factory=list, max_length=10)
    # 2026-07-29 - 新建须指定诊断平台 - 至少 1 个可提交码，禁止隐式全开
    platforms: list[str] = Field(min_length=1, max_length=32)
    contact_name: str | None = Field(default=None, max_length=60)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_note: str | None = Field(default=None, max_length=500)
    region_codes: list[str] = Field(default_factory=list, max_length=34)
    diagnosis_date: date | None = None
    start_immediately: bool = False

    @field_validator("prompts")
    @classmethod
    def normalize_prompts(cls, value: list[str]) -> list[str]:
        return normalize_lead_prompts(value)

    @field_validator("competitors")
    @classmethod
    def normalize_competitors(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("platforms")
    @classmethod
    def normalize_platforms(cls, value: list[str]) -> list[str]:
        from app.services.molizhishu_catalog_service import filter_submittable_platforms

        codes = filter_submittable_platforms([str(item or "").strip() for item in value])
        if not codes:
            raise ValueError("请至少选择一个可提交的诊断平台")
        return codes

    @field_validator("region_codes")
    @classmethod
    def normalize_region_codes(cls, value: list[str]) -> list[str]:
        from app.core.region_catalog import normalize_region_codes as normalize_codes

        return normalize_codes(value)


class LeadDiagnosisUpdateRequest(BaseModel):
    contact_name: str | None = Field(default=None, max_length=60)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_note: str | None = Field(default=None, max_length=500)
