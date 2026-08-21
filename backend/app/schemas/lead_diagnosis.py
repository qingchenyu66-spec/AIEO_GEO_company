from datetime import date
from typing import Any, Literal
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.lead_diagnosis_config import (
    LEAD_SCHEDULE_DAYS,
    LEAD_SCHEDULE_DAYS_MAX,
    LEAD_SCHEDULE_DAYS_MIN,
    clamp_lead_schedule_days,
)
from app.core.lead_diagnosis_prompts import normalize_lead_prompts


LeadDiagnosisStatus = Literal["pending", "collecting", "ready", "failed", "canceled"]

_LEAD_CONTEXT_TEXT_MAX = 200
_LEAD_CONTEXT_URL_MAX = 500
_LEAD_CONTEXT_SOURCE_DEFAULT = "lead_diagnosis_create"
_DANGEROUS_URL_RE = re.compile(r"^(javascript|data|vbscript):", re.I)


def _clip_text(value: Any, *, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def clean_lead_website_url(value: Any) -> str:
    """官网 URL 基本清洗：去空白、禁危险协议、缺 scheme 则补 https。"""
    raw = _clip_text(value, max_len=_LEAD_CONTEXT_URL_MAX)
    if not raw:
        return ""
    if _DANGEROUS_URL_RE.match(raw):
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = f"https://{raw}"
    return raw[:_LEAD_CONTEXT_URL_MAX]


def normalize_lead_context(value: Any) -> dict[str, str]:
    """结构化诊断上下文；旧数据/空值 → 空字段 + 默认 source。"""
    raw = value if isinstance(value, dict) else {}
    website_url = clean_lead_website_url(raw.get("website_url"))
    industry = _clip_text(raw.get("industry"), max_len=_LEAD_CONTEXT_TEXT_MAX)
    product_focus = _clip_text(raw.get("product_focus"), max_len=_LEAD_CONTEXT_TEXT_MAX)
    purchase_scenario = _clip_text(raw.get("purchase_scenario"), max_len=_LEAD_CONTEXT_TEXT_MAX)
    source = _clip_text(raw.get("source"), max_len=64) or _LEAD_CONTEXT_SOURCE_DEFAULT
    return {
        "website_url": website_url,
        "industry": industry,
        "product_focus": product_focus,
        "purchase_scenario": purchase_scenario,
        "source": source,
    }


def normalize_brand_aliases(value: Any, *, max_items: int = 20, max_len: int = 100) -> list[str]:
    """露出词/别名：去空白、去重保序、限条数与单条长度。"""
    raw_items: list[Any]
    if value is None:
        raw_items = []
    elif isinstance(value, str):
        raw_items = re.split(r"[,，、;/|]+", value)
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raw_items = []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > max_len:
            text = text[:max_len]
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


class LeadContext(BaseModel):
    """售前入口诊断上下文（与 prompts/contact_note 分离）。"""

    website_url: str = ""
    industry: str = ""
    product_focus: str = ""
    purchase_scenario: str = ""
    source: str = _LEAD_CONTEXT_SOURCE_DEFAULT

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> dict[str, str]:
        return normalize_lead_context(value)


class LeadDiagnosisCreateRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=100)
    prompts: list[str] = Field(min_length=1, max_length=5)
    competitors: list[str] = Field(default_factory=list, max_length=10)
    # 2026-08-13 - 可选露出词/品牌别名；空则服务端从全称自动派生
    brand_aliases: list[str] = Field(default_factory=list, max_length=20)
    # 2026-07-29 - 新建须指定诊断平台 - 至少 1 个可提交码，禁止隐式全开
    platforms: list[str] = Field(min_length=1, max_length=32)
    contact_name: str | None = Field(default=None, max_length=60)
    contact_phone: str | None = Field(default=None, max_length=30)
    # 2026-08-13 - contact_note 只保留销售备注，官网/行业/产品走 lead_context
    contact_note: str | None = Field(default=None, max_length=500)
    lead_context: LeadContext | None = None
    region_codes: list[str] = Field(default_factory=list, max_length=34)
    diagnosis_date: date | None = None
    # 2026-08-04 - 诊断天数建议 3–7 非必须 - 默认 3，硬限制 1–30
    schedule_days: int = Field(default=LEAD_SCHEDULE_DAYS, ge=LEAD_SCHEDULE_DAYS_MIN, le=LEAD_SCHEDULE_DAYS_MAX)
    start_immediately: bool = False

    @field_validator("schedule_days")
    @classmethod
    def normalize_schedule_days(cls, value: int) -> int:
        return clamp_lead_schedule_days(value)

    @field_validator("prompts")
    @classmethod
    def normalize_prompts(cls, value: list[str]) -> list[str]:
        return normalize_lead_prompts(value)

    @field_validator("competitors")
    @classmethod
    def normalize_competitors(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("brand_aliases", mode="before")
    @classmethod
    def normalize_brand_aliases_field(cls, value: Any) -> list[str]:
        return normalize_brand_aliases(value)

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

    def lead_context_dict(self) -> dict[str, str]:
        if self.lead_context is None:
            return normalize_lead_context({})
        return self.lead_context.model_dump()


class LeadDiagnosisUpdateRequest(BaseModel):
    contact_name: str | None = Field(default=None, max_length=60)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_note: str | None = Field(default=None, max_length=500)
