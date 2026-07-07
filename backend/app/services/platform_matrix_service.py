"""Platform-side service health matrix for supported Molizhishu platforms."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
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
    """Aggregate today's subtask outcomes per platform across all tenants."""
    start_at, end_at = _today_bounds()
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .where(
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.created_at >= start_at,
                GeoMonitorTask.created_at <= end_at,
            )
            .order_by(GeoMonitorSubtask.updated_at.desc(), GeoMonitorSubtask.id.desc())
        )
    )
    buckets: dict[str, dict[str, Any]] = {}
    for item in subtasks:
        code = (item.platform or "").strip()
        if not code:
            continue
        bucket = buckets.setdefault(
            code,
            {
                "total": 0,
                "completed": 0,
                "failed": 0,
                "success": 0,
                "latest_at": None,
            },
        )
        bucket["total"] += 1
        if item.status in TERMINAL_SUBTASK_STATUSES:
            bucket["completed"] += 1
        if item.status == "failed":
            bucket["failed"] += 1
        if item.status in SUCCESS_SUBTASK_STATUSES:
            bucket["success"] += 1
        if item.updated_at and (bucket["latest_at"] is None or item.updated_at > bucket["latest_at"]):
            bucket["latest_at"] = item.updated_at
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


def build_platform_matrix(db: Session, current: CurrentSession, *, tenant_id: int | None = None) -> dict[str, Any]:
    """Platform ops view: Molizhishu doc catalog + today's cross-tenant probe counts."""
    del tenant_id
    if current.identity.identity_type != "PLATFORM":
        raise ValueError("模型平台服务状态仅平台运营端可查看")

    catalog = get_supported_platform_catalog()
    catalog_meta = get_platform_catalog_meta()
    health_map = _today_global_platform_health(db)
    first_schedule = _first_schedule_today(db)

    platforms: list[dict[str, Any]] = []
    probe_total = 0
    probe_success = 0
    probe_failed = 0

    for item in catalog:
        code = item["code"]
        stats = health_map.get(code)
        total = int(stats.get("total") or 0) if stats else 0
        success = int(stats.get("success") or 0) if stats else 0
        failed = int(stats.get("failed") or 0) if stats else 0
        probe_total += total
        probe_success += success
        probe_failed += failed
        platforms.append({
            "code": code,
            "name": item["name"],
            "description": item.get("description"),
            "channel": item["channel"],
            "channel_label": "移动端" if item["channel"] == "mobile" else "网页端",
            "supported": True,
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
        "supported_count": len(catalog),
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
