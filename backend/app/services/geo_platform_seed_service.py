"""从模力平台目录同步 geo_platform 表（委托生命周期服务：含下架剥离）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.molizhishu_platforms import get_supported_platform_catalog
from app.services.platform_catalog_lifecycle_service import sync_platform_catalog_lifecycle


def sync_geo_platforms_from_catalog(db: Session, *, force_refresh: bool = False) -> dict[str, Any]:
    # 保留对本模块 get_supported_platform_catalog 的 monkeypatch 兼容（单测）
    _ = get_supported_platform_catalog
    result = sync_platform_catalog_lifecycle(db, force_refresh=force_refresh)
    return {
        **result,
        "created": len(result.get("created") or []),
        "updated": max(0, int(result.get("catalog_size") or 0) - len(result.get("created") or [])),
        "total": int(result.get("catalog_size") or 0),
        "created_codes": list(result.get("created") or []),
        "delisted_codes": list(result.get("delisted") or []),
    }
