"""Daily Molizhishu catalog sync: shelf up/down + strip勾选 + notify."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.brand import BrandAsset, BrandKeywordGroup
from app.models.platform import GeoPlatform
from app.services.molizhishu_platforms import get_supported_platform_catalog
from app.services.platform_selection import normalize_platform_selections, selection_codes
from app.services.system_notification_service import upsert_platform_service_notification

logger = logging.getLogger(__name__)


def _upsert_from_catalog(db: Session, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    catalog_codes = {str(item.get("code") or "").strip().lower() for item in catalog if item.get("code")}
    existing = {
        row.platform_code: row
        for row in db.scalars(select(GeoPlatform).where(GeoPlatform.deleted.is_(False))).all()
    }
    created: list[str] = []
    relisted: list[str] = []
    for item in catalog:
        code = str(item.get("code") or "").strip().lower()
        if not code:
            continue
        channel = str(item.get("channel") or "web")
        access_type = "mobile" if channel == "mobile" else "api"
        row = existing.get(code)
        if row is None:
            db.add(
                GeoPlatform(
                    platform_code=code,
                    platform_name=str(item.get("name") or code),
                    access_type=access_type,
                    status=True,
                    catalog_listed=True,
                    service_available=True,
                    sort_order=int(item.get("sort_order") or 0),
                    description=str(item.get("description") or "") or None,
                    deleted=False,
                )
            )
            created.append(code)
            continue
        was_listed = bool(row.catalog_listed)
        row.platform_name = str(item.get("name") or row.platform_name)
        row.description = str(item.get("description") or "") or None
        row.sort_order = int(item.get("sort_order") or row.sort_order or 0)
        row.access_type = access_type
        row.deleted = False
        row.status = True
        row.catalog_listed = True
        if not was_listed:
            relisted.append(code)
    delisted: list[str] = []
    for code, row in existing.items():
        if code in catalog_codes:
            continue
        if row.catalog_listed or row.status:
            row.catalog_listed = False
            row.status = False
            delisted.append(code)
    db.flush()
    return {"created": created, "relisted": relisted, "delisted": delisted, "catalog_size": len(catalog_codes)}


def strip_delisted_from_brand_configs(db: Session, delisted_codes: list[str]) -> int:
    """Remove delisted platforms from keyword groups + asset monitored_platforms. Returns affected tenants."""
    if not delisted_codes:
        return 0
    banned = set(delisted_codes)
    touched_tenants: set[int] = set()
    groups = list(db.scalars(select(BrandKeywordGroup).where(BrandKeywordGroup.deleted.is_(False))))
    for group in groups:
        selections = normalize_platform_selections(group.platforms_json or [])
        kept = [item for item in selections if item["code"] not in banned]
        if len(kept) == len(selections):
            continue
        group.platforms_json = kept
        flag_modified(group, "platforms_json")
        touched_tenants.add(group.tenant_id)
    assets = list(db.scalars(select(BrandAsset).where(BrandAsset.deleted.is_(False))))
    for asset in assets:
        raw = list(asset.monitored_platforms_json or [])
        # monitored_platforms stays code list
        codes = selection_codes(raw) if raw and isinstance(raw[0], dict) else [str(c).strip() for c in raw if str(c).strip()]
        kept_codes = [c for c in codes if c not in banned]
        if len(kept_codes) == len(codes):
            continue
        asset.monitored_platforms_json = kept_codes
        flag_modified(asset, "monitored_platforms_json")
        touched_tenants.add(asset.tenant_id)
    return len(touched_tenants)


def sync_platform_catalog_lifecycle(db: Session, *, force_refresh: bool = True) -> dict[str, Any]:
    """Daily job: pull official catalog, shelf up/down, uncheck delisted, notify."""
    catalog = get_supported_platform_catalog(force_refresh=force_refresh)
    result = _upsert_from_catalog(db, catalog)
    tenants_touched = strip_delisted_from_brand_configs(db, result["delisted"])
    result["tenants_stripped"] = tenants_touched
    db.commit()

    if result["delisted"]:
        names = _code_name_map(db, result["delisted"])
        label = "、".join(names.get(c, c) for c in result["delisted"][:8])
        upsert_platform_service_notification(
            db,
            event="delisted",
            title="监测平台已下架",
            message=f"模力目录下架：{label}。已从企业词组取消勾选，请确认监测覆盖。",
            payload={"codes": result["delisted"], "event": "delisted"},
            source_key=f"platform:delisted:{datetime.now():%Y%m%d}",
            level="warning",
        )
    if result["created"] or result["relisted"]:
        codes = result["created"] + result["relisted"]
        names = _code_name_map(db, codes)
        label = "、".join(names.get(c, c) for c in codes[:8])
        upsert_platform_service_notification(
            db,
            event="listed",
            title="监测平台已上架",
            message=f"模力目录新增/恢复：{label}。默认不自动勾选，需在企业管理中手动选择。",
            payload={"codes": codes, "event": "listed"},
            source_key=f"platform:listed:{datetime.now():%Y%m%d}",
            level="info",
        )
    logger.info("[platform-catalog] sync %s", result)
    return result


def _code_name_map(db: Session, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = db.scalars(select(GeoPlatform).where(GeoPlatform.platform_code.in_(codes))).all()
    return {row.platform_code: row.platform_name for row in rows}


def list_platforms_for_brand_config(db: Session) -> list[dict[str, Any]]:
    """UI catalog for 企业管理勾选：含下架/无服务态。"""
    rows = list(
        db.scalars(
            select(GeoPlatform)
            .where(GeoPlatform.deleted.is_(False))
            .order_by(GeoPlatform.sort_order.asc(), GeoPlatform.id.asc())
        )
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        listed = bool(row.catalog_listed)
        available = bool(row.service_available)
        selectable = listed and available
        labels: list[str] = []
        if not listed:
            labels.append("已下架")
        elif not available:
            labels.append("无服务")
        result.append({
            "code": row.platform_code,
            "name": row.platform_name,
            "channel": "mobile" if row.access_type == "mobile" else "web",
            "catalog_listed": listed,
            "service_available": available,
            "selectable": selectable,
            "labels": labels,
            "service_checked_at": row.service_checked_at.isoformat(timespec="seconds") if row.service_checked_at else None,
            "modes": ["standard", "search", "reasoning", "reasoning_search"],
            "default_mode": "standard",
            "default_screenshot": 1,
        })
    # 仅展示仍在目录或仍有历史勾选需求的：下架也展示一行标「已下架」便于只读
    return result


def submittable_platform_codes(db: Session, codes: list[str]) -> list[str]:
    """Filter to catalog-listed + service-available + known codes."""
    if not codes:
        return []
    rows = {
        row.platform_code: row
        for row in db.scalars(
            select(GeoPlatform).where(
                GeoPlatform.deleted.is_(False),
                GeoPlatform.platform_code.in_(codes),
            )
        )
    }
    result: list[str] = []
    for code in codes:
        row = rows.get(code)
        if row is None:
            continue
        if row.catalog_listed and row.service_available and row.status:
            result.append(code)
    return result
