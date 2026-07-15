"""Weekly hybrid platform availability: formal stats + cold-platform probe."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.platform import GeoPlatform
from app.schemas.monitor import FAST_MONITOR_MODE, MonitorTaskCreateRequest, PlatformConfig
from app.services.system_notification_service import upsert_platform_service_notification

logger = logging.getLogger(__name__)

FORMAL_WINDOW_DAYS = 7
FORMAL_MIN_SAMPLES = 10
SUCCESS_RATE_THRESHOLD = 0.5
SUCCESS_STATUSES = frozenset({"completed", "partial_completed"})
TERMINAL_STATUSES = frozenset({"completed", "partial_completed", "failed", "stopped"})
PROBE_PROMPT = "请用一句话介绍你自己"


def _formal_stats(db: Session, since: datetime) -> dict[str, dict[str, int]]:
    rows = db.execute(
        select(
            GeoMonitorSubtask.platform,
            GeoMonitorSubtask.status,
            func.count(),
        )
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.created_at >= since,
            GeoMonitorSubtask.platform != "",
        )
        .group_by(GeoMonitorSubtask.platform, GeoMonitorSubtask.status)
    ).all()
    buckets: dict[str, dict[str, int]] = {}
    for platform, status, count in rows:
        code = str(platform or "").strip()
        if not code:
            continue
        bucket = buckets.setdefault(code, {"total": 0, "success": 0, "failed": 0, "terminal": 0})
        n = int(count or 0)
        bucket["total"] += n
        if status in SUCCESS_STATUSES:
            bucket["success"] += n
        if status == "failed":
            bucket["failed"] += n
        if status in TERMINAL_STATUSES:
            bucket["terminal"] += n
    return buckets


def _availability_from_formal(stats: dict[str, int] | None) -> bool | None:
    """Return True/False from formal data, or None if cold (need probe)."""
    if not stats or int(stats.get("total") or 0) < FORMAL_MIN_SAMPLES:
        return None
    total = int(stats["total"])
    success = int(stats.get("success") or 0)
    failed = int(stats.get("failed") or 0)
    if failed == total:
        return False
    return (success / total) >= SUCCESS_RATE_THRESHOLD


def evaluate_platform_availability(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Update service_available from formal data; queue cold platforms for probe."""
    now = now or datetime.now()
    since = now - timedelta(days=FORMAL_WINDOW_DAYS)
    stats_map = _formal_stats(db, since)
    platforms = list(
        db.scalars(
            select(GeoPlatform).where(
                GeoPlatform.deleted.is_(False),
                GeoPlatform.catalog_listed.is_(True),
            )
        )
    )
    flipped_down: list[str] = []
    flipped_up: list[str] = []
    cold: list[str] = []
    for row in platforms:
        prev = bool(row.service_available)
        verdict = _availability_from_formal(stats_map.get(row.platform_code))
        if verdict is None:
            cold.append(row.platform_code)
            # cold: keep previous until probe finalizes
            row.service_checked_at = now
            continue
        row.service_available = verdict
        row.service_checked_at = now
        if prev and not verdict:
            flipped_down.append(row.platform_code)
        elif (not prev) and verdict:
            flipped_up.append(row.platform_code)
    db.commit()
    return {
        "flipped_down": flipped_down,
        "flipped_up": flipped_up,
        "cold": cold,
        "checked": len(platforms),
    }


def apply_probe_results(db: Session, platform_results: dict[str, bool], *, now: datetime | None = None) -> dict[str, Any]:
    """Apply cold-platform probe outcomes. Recover→available but never auto-recheck品牌."""
    now = now or datetime.now()
    flipped_down: list[str] = []
    flipped_up: list[str] = []
    for code, ok in platform_results.items():
        row = db.scalar(
            select(GeoPlatform).where(
                GeoPlatform.platform_code == code,
                GeoPlatform.deleted.is_(False),
            )
        )
        if row is None:
            continue
        prev = bool(row.service_available)
        row.service_available = bool(ok)
        row.service_checked_at = now
        if prev and not ok:
            flipped_down.append(code)
        elif (not prev) and ok:
            flipped_up.append(code)
    db.commit()
    return {"flipped_down": flipped_down, "flipped_up": flipped_up}


def notify_availability_flips(db: Session, *, flipped_down: list[str], flipped_up: list[str]) -> None:
    names = {
        row.platform_code: row.platform_name
        for row in db.scalars(select(GeoPlatform).where(GeoPlatform.platform_code.in_(flipped_down + flipped_up))).all()
    }
    if flipped_down:
        label = "、".join(names.get(c, c) for c in flipped_down[:8])
        upsert_platform_service_notification(
            db,
            event="unavailable",
            title="监测平台暂不可用",
            message=f"以下平台已标记无服务并将跳过提交：{label}。企业勾选将置灰，需恢复后手动重新勾选。",
            payload={"codes": flipped_down, "event": "unavailable"},
            source_key=f"platform:unavailable:{datetime.now():%Y%m%d%H}",
            level="warning",
        )
    if flipped_up:
        label = "、".join(names.get(c, c) for c in flipped_up[:8])
        upsert_platform_service_notification(
            db,
            event="recovered",
            title="监测平台服务已恢复",
            message=f"以下平台已取消无服务标记：{label}。默认不会自动恢复勾选，请在企业管理中手动启用。",
            payload={"codes": flipped_up, "event": "recovered"},
            source_key=f"platform:recovered:{datetime.now():%Y%m%d%H}",
            level="info",
        )


def build_cold_probe_request(cold_codes: list[str]) -> MonitorTaskCreateRequest | None:
    if not cold_codes:
        return None
    platforms = [
        PlatformConfig(platform=code, mode=FAST_MONITOR_MODE, screenshot=1)
        for code in cold_codes
    ]
    return MonitorTaskCreateRequest(
        tenant_id=None,
        prompts=[PROBE_PROMPT],
        platforms=platforms,
        monitor_keywords="平台可用性探针",
        monitor_keyword_aliases=[],
    )


def run_weekly_availability_check(db: Session) -> dict[str, Any]:
    """Formal evaluate + return cold list for optional probe submit by task layer."""
    result = evaluate_platform_availability(db)
    notify_availability_flips(
        db,
        flipped_down=result["flipped_down"],
        flipped_up=result["flipped_up"],
    )
    return result
