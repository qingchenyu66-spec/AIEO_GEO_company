"""Monitor task purpose: geo (default) vs brand_word (品牌分析 only)."""

from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from app.models.monitor import GeoMonitorTask

PURPOSE_GEO = "geo"
PURPOSE_BRAND_WORD = "brand_word"
VALID_PURPOSES = frozenset({PURPOSE_GEO, PURPOSE_BRAND_WORD})


def normalize_task_purpose(value: str | None) -> str:
    text = str(value or PURPOSE_GEO).strip().lower()
    return text if text in VALID_PURPOSES else PURPOSE_GEO


def task_purpose_eq(purpose: str = PURPOSE_GEO) -> ColumnElement[bool]:
    """Filter tasks by purpose. GEO menus must pass PURPOSE_GEO (default)."""
    return GeoMonitorTask.purpose == normalize_task_purpose(purpose)
