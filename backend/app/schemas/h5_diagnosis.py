from pydantic import BaseModel, Field, field_validator

from app.core.lead_diagnosis_prompts import normalize_lead_prompts


class H5DiagnosisOrderCreateRequest(BaseModel):
    contact_phone: str = Field(min_length=11, max_length=30)
    brand_name: str = Field(min_length=1, max_length=100)
    prompts: list[str] = Field(min_length=1, max_length=5)
    wechat_id: str = Field(default="", max_length=64)
    brand_aliases: str = Field(default="", max_length=500)
    industry: str = Field(default="", max_length=200)
    product_focus: str = Field(default="", max_length=200)
    website_url: str = Field(default="", max_length=500)
    competitors: str = Field(default="", max_length=500)

    @field_validator("prompts")
    @classmethod
    def normalize_prompts(cls, value: list[str]) -> list[str]:
        return normalize_lead_prompts(value)

    @field_validator("brand_aliases", "competitors", mode="before")
    @classmethod
    def keep_text(cls, value: object) -> str:
        return str(value or "").strip()
