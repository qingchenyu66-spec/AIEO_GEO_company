"""Molizhishu platform helpers — catalog is synced from official docs."""

from __future__ import annotations

from typing import Any

from app.services.molizhishu_catalog_service import (
    filter_submittable_platforms,
    get_platform_catalog_meta,
    get_supported_platform_catalog,
    refresh_platform_catalog,
    supported_platform_codes,
)

__all__ = [
    "filter_submittable_platforms",
    "get_platform_catalog_meta",
    "get_supported_platform_catalog",
    "refresh_platform_catalog",
    "supported_platform_catalog",
    "supported_platform_codes",
]


def supported_platform_catalog(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    return get_supported_platform_catalog(force_refresh=force_refresh)
