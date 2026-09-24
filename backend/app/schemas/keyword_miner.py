"""GEO 选词历史 API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeywordMinerJobUpsertRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=20)
    company: str = ""
    product: str = ""
    error: str | None = None
    payload: dict | None = None
    result: dict | None = None
    created_at: float | None = None
    updated_at: float | None = None
    selection_count: int | None = None
    expansion_count: int | None = None
    task: str | None = None
    platforms: list[str] | None = None
    source: str | None = None
    model: str | None = None
    top_words: list[str] | None = None
