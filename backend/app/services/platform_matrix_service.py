"""Platform-side service health matrix for supported Molizhishu platforms."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.platform import GeoPlatform
from app.services.molizhishu_platforms import (
    filter_submittable_platforms,
    get_platform_catalog_meta,
    get_supported_platform_catalog,
    refresh_platform_catalog,
)

TERMINAL_SUBTASK_STATUSES = {"completed", "partial_completed", "failed", "stopped"}
SUCCESS_SUBTASK_STATUSES = {"completed", "partial_completed"}


def _today_bounds() -> tuple[datetime, datetime]:
    today = date.today()
    return datetime.combine(today, time.min), datetime.combine(today, time.max.replace(microsecond=0))


def _today_global_platform_health(db: Session) -> dict[str, dict[str, Any]]:
    """Aggregate today's subtask outcomes per platform across all tenants.

    2026-07-30 - platforms/matrix Out of sort memory(1038) - 勿整行拉 subtask+ORDER BY，改 SQL 按平台聚合
    """
    start_at, end_at = _today_bounds()
    terminal = list(TERMINAL_SUBTASK_STATUSES)
    success = list(SUCCESS_SUBTASK_STATUSES)
    rows = db.execute(
        select(
            GeoMonitorSubtask.platform,
            func.count().label("total"),
            func.sum(
                case((GeoMonitorSubtask.status.in_(terminal), 1), else_=0)
            ).label("completed"),
            func.sum(case((GeoMonitorSubtask.status == "failed", 1), else_=0)).label("failed"),
            func.sum(
                case((GeoMonitorSubtask.status.in_(success), 1), else_=0)
            ).label("success"),
            func.max(GeoMonitorSubtask.updated_at).label("latest_at"),
        )
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.purpose == "geo",
            GeoMonitorTask.created_at >= start_at,
            GeoMonitorTask.created_at <= end_at,
        )
        .group_by(GeoMonitorSubtask.platform)
    ).all()

    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = (row.platform or "").strip()
        if not code:
            continue
        buckets[code] = {
            "total": int(row.total or 0),
            "completed": int(row.completed or 0),
            "failed": int(row.failed or 0),
            "success": int(row.success or 0),
            "latest_at": row.latest_at,
        }
    return buckets


def _first_schedule_today(db: Session) -> GeoMonitorScheduleRun | None:
    start_at, end_at = _today_bounds()
    return db.scalar(
        select(GeoMonitorScheduleRun)
        .where(
            GeoMonitorScheduleRun.status == "submitted",
            GeoMonitorScheduleRun.created_at >= start_at,
            GeoMonitorScheduleRun.created_at <= end_at,
        )
        .order_by(GeoMonitorScheduleRun.created_at.asc(), GeoMonitorScheduleRun.id.asc())
    )


def _shelf_labels(*, listed: bool, available: bool) -> list[str]:
    labels: list[str] = []
    if not listed:
        labels.append("已下架")
    elif not available:
        labels.append("无服务")
    return labels


def build_platform_matrix(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Platform ops view: Molizhishu doc catalog + shelf/availability + today's probes."""
    del tenant_id
    if current.identity.identity_type != "PLATFORM":
        raise ValueError("模型平台服务状态仅平台运营端可查看")

    if force_refresh:
        from app.services.platform_catalog_lifecycle_service import sync_platform_catalog_lifecycle

        sync_platform_catalog_lifecycle(db, force_refresh=True)
    else:
        get_supported_platform_catalog(force_refresh=False)

    catalog = get_supported_platform_catalog()
    catalog_meta = get_platform_catalog_meta()
    health_map = _today_global_platform_health(db)
    first_schedule = _first_schedule_today(db)

    db_rows = {
        row.platform_code: row
        for row in db.scalars(select(GeoPlatform).where(GeoPlatform.deleted.is_(False))).all()
    }

    platforms: list[dict[str, Any]] = []
    probe_total = 0
    probe_success = 0
    probe_failed = 0
    seen: set[str] = set()

    for item in catalog:
        code = item["code"]
        seen.add(code)
        stats = health_map.get(code)
        total = int(stats.get("total") or 0) if stats else 0
        success = int(stats.get("success") or 0) if stats else 0
        failed = int(stats.get("failed") or 0) if stats else 0
        probe_total += total
        probe_success += success
        probe_failed += failed
        row = db_rows.get(code)
        listed = bool(row.catalog_listed) if row is not None else True
        available = bool(row.service_available) if row is not None else True
        channel = item.get("channel") or ("mobile" if row and row.access_type == "mobile" else "web")
        platforms.append({
            "code": code,
            "name": (row.platform_name if row and row.platform_name else None) or item["name"],
            "description": item.get("description"),
            "channel": channel,
            "channel_label": "移动端" if channel == "mobile" else "网页端",
            "supported": True,
            "catalog_listed": listed,
            "service_available": available,
            "labels": _shelf_labels(listed=listed, available=available),
            "service_checked_at": (
                row.service_checked_at.isoformat(timespec="seconds")
                if row is not None and row.service_checked_at
                else None
            ),
            "probe_total": total,
            "probe_success": success,
            "probe_failed": failed,
            "checked_at": stats["latest_at"].isoformat() if stats and stats.get("latest_at") else None,
        })

    # 已从官方目录消失但仍在库中的：保留展示以便看到「已下架」
    for code, row in sorted(db_rows.items(), key=lambda pair: (pair[1].sort_order or 0, pair[0])):
        if code in seen:
            continue
        if row.catalog_listed:
            continue
        stats = health_map.get(code)
        total = int(stats.get("total") or 0) if stats else 0
        success = int(stats.get("success") or 0) if stats else 0
        failed = int(stats.get("failed") or 0) if stats else 0
        probe_total += total
        probe_success += success
        probe_failed += failed
        channel = "mobile" if row.access_type == "mobile" else "web"
        platforms.append({
            "code": code,
            "name": row.platform_name,
            "description": row.description,
            "channel": channel,
            "channel_label": "移动端" if channel == "mobile" else "网页端",
            "supported": False,
            "catalog_listed": False,
            "service_available": bool(row.service_available),
            "labels": _shelf_labels(listed=False, available=bool(row.service_available)),
            "service_checked_at": (
                row.service_checked_at.isoformat(timespec="seconds") if row.service_checked_at else None
            ),
            "probe_total": total,
            "probe_success": success,
            "probe_failed": failed,
            "checked_at": stats["latest_at"].isoformat() if stats and stats.get("latest_at") else None,
        })

    updated_at = datetime.now().isoformat(timespec="seconds")
    latest_values = [value["latest_at"] for value in health_map.values() if value.get("latest_at")]
    if latest_values:
        updated_at = max(latest_values).isoformat(timespec="seconds")

    return {
        "snapshot_date": date.today().isoformat(),
        "supported_count": len([p for p in platforms if p.get("catalog_listed")]),
        "probe_total": probe_total,
        "probe_success": probe_success,
        "probe_failed": probe_failed,
        "first_schedule_at": first_schedule.created_at.isoformat() if first_schedule else None,
        "updated_at": updated_at,
        "catalog_source": catalog_meta.get("source"),
        "catalog_source_url": catalog_meta.get("source_url"),
        "catalog_fetched_at": catalog_meta.get("fetched_at"),
        "platforms": platforms,
    }


def is_first_daily_schedule_window(db: Session, tenant_id: int, schedule_key: str) -> bool:
    today_prefix = date.today().strftime("%Y%m%d")
    if not schedule_key.startswith(today_prefix):
        return False
    prior = db.scalar(
        select(GeoMonitorScheduleRun.id)
        .where(
            GeoMonitorScheduleRun.tenant_id == tenant_id,
            GeoMonitorScheduleRun.schedule_key.like(f"{today_prefix}%"),
            GeoMonitorScheduleRun.schedule_key < schedule_key,
        )
        .limit(1)
    )
    return prior is None


def prepare_daily_platform_matrix_before_submit(
    db: Session,
    *,
    tenant_id: int,
    schedule_key: str,
) -> bool:
    """Before the first daily batch, normalize purchasable platforms for the tenant."""
    if not is_first_daily_schedule_window(db, tenant_id, schedule_key):
        return False
    refresh_platform_catalog(force=True)
    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))
    if asset is None:
        return False
    normalized = filter_submittable_platforms(asset.monitored_platforms_json)
    if normalized != list(asset.monitored_platforms_json or []):
        asset.monitored_platforms_json = normalized
    asset.updated_at = datetime.now()
    db.flush()
    return True
