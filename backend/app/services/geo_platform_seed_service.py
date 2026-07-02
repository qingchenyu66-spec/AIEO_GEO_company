"""从模力平台目录同步 geo_platform 表。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform import GeoPlatform
from app.services.molizhishu_platforms import get_supported_platform_catalog


def sync_geo_platforms_from_catalog(db: Session, *, force_refresh: bool = False) -> dict[str, Any]:
    catalog = get_supported_platform_catalog(force_refresh=force_refresh)
    created = 0
    updated = 0
    for item in catalog:
        code = str(item.get("code") or "").strip().lower()
        if not code:
            continue
        row = db.scalar(select(GeoPlatform).where(GeoPlatform.platform_code == code))
        channel = str(item.get("channel") or "web")
        access_type = "mobile" if channel == "mobile" else "api"
        if row is None:
            db.add(
                GeoPlatform(
                    platform_code=code,
                    platform_name=str(item.get("name") or code),
                    access_type=access_type,
                    status=True,
                    sort_order=int(item.get("sort_order") or 0),
                    description=str(item.get("description") or "") or None,
                )
            )
            created += 1
            continue
        row.platform_name = str(item.get("name") or row.platform_name)
        row.description = str(item.get("description") or "") or None
        row.sort_order = int(item.get("sort_order") or row.sort_order or 0)
        row.access_type = access_type
        row.deleted = False
        row.status = True
        updated += 1
    db.commit()
    return {"created": created, "updated": updated, "total": len(catalog)}
