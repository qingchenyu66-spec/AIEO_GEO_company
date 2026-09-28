"""GEO 选词历史与范例库 API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeywordMinerJobUpsertRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=20)
    company: str = ""
    product: str = ""
    error: str | None = None
    payload: dict | None = None
    result: dict | None = None
    edited_result: dict | None = None
    edit_notes: list[dict] | None = None
    created_at: float | None = None
    updated_at: float | None = None
    selection_count: int | None = None
    expansion_count: int | None = None
    task: str | None = None
    platforms: list[str] | None = None
    source: str | None = None
    model: str | None = None
    top_words: list[str] | None = None


class KeywordMinerJobEditRequest(BaseModel):
    edited_result: dict = Field(..., description="修订后的选词/拓词结果")
    edit_notes: list[dict] = Field(default_factory=list, description="改因备注列表")


class KeywordMinerExampleItemIn(BaseModel):
    kind: str = Field(..., description="select/expand")
    industry: str = ""
    stage: str = ""
    word: str = Field(..., min_length=1, max_length=255)
    answer: str | None = None
    intent: str | None = None
    heat: int | None = None
    note: str | None = None
    edit_reason: str | None = None
    product_tags: list[str] | None = None


class KeywordMinerExampleBatchRequest(BaseModel):
    industry: str = ""
    source_job_id: str | None = None
    source_company: str = ""
    source_product: str = ""
    items: list[KeywordMinerExampleItemIn] = Field(default_factory=list)


class KeywordMinerExampleUpdateRequest(BaseModel):
    industry: str | None = None
    stage: str | None = None
    word: str | None = None
    answer: str | None = None
    intent: str | None = None
    heat: int | None = None
    note: str | None = None
    edit_reason: str | None = None
    status: str | None = None
    product_tags: list[str] | None = None
