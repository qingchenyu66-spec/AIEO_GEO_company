from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


LeadDiagnosisStatus = Literal["pending", "collecting", "ready", "failed"]


class LeadDiagnosisCreateRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=100)
    prompts: list[str] = Field(min_length=1, max_length=5)
    competitors: list[str] = Field(default_factory=list, max_length=10)
    contact_name: str | None = Field(default=None, max_length=60)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_note: str | None = Field(default=None, max_length=500)
    region_codes: list[str] = Field(default_factory=list, max_length=34)
    diagnosis_date: date | None = None
    start_immediately: bool = False

    @field_validator("prompts")
    @classmethod
    def normalize_prompts(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("至少填写一个检测问题")
        if len(cleaned) > 5:
            raise ValueError("最多支持 5 个检测问题")
        return cleaned

    @field_validator("competitors")
    @classmethod
    def normalize_competitors(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("region_codes")
    @classmethod
    def normalize_region_codes(cls, value: list[str]) -> list[str]:
        from app.core.region_catalog import normalize_region_codes as normalize_codes

        return normalize_codes(value)


class LeadDiagnosisUpdateRequest(BaseModel):
    contact_name: str | None = Field(default=None, max_length=60)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_note: str | None = Field(default=None, max_length=500)
