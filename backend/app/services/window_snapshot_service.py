"""近 7/30 日窗口快照：工作台默认窗预聚合，页面优先读快照。

2026-08-21 - 稳定性桌面方案⑤：常用窗口落表，少扫明细
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.monitor import GeoMonitorWindowSnapshot

logger = logging.getLogger(__name__)

WINDOW_KINDS = ("workspace_brief",)
WINDOW_DAYS = (7, 30)
DEFAULT_FILTER_FP = "default"


def _as_of_customer_cutoff(now: datetime | None = None) -> date:
    from app.services.monitor_service import customer_display_cutoff

    return customer_display_cutoff(now).date()


def invalidate_window_snapshots_for_tenant(db: Session, tenant_id: int) -> int:
    result = db.execute(
        delete(GeoMonitorWindowSnapshot).where(GeoMonitorWindowSnapshot.tenant_id == int(tenant_id))
    )
    db.commit()
    return int(result.rowcount or 0)


def get_window_snapshot(
    db: Session,
    *,
    tenant_id: int,
    kind: str,
    window_days: int,
    as_of_date: date | None = None,
    filter_fp: str = DEFAULT_FILTER_FP,
) -> dict[str, Any] | None:
    as_of = as_of_date or _as_of_customer_cutoff()
    row = db.scalar(
        select(GeoMonitorWindowSnapshot).where(
            GeoMonitorWindowSnapshot.tenant_id == int(tenant_id),
            GeoMonitorWindowSnapshot.kind == kind,
            GeoMonitorWindowSnapshot.window_days == int(window_days),
            GeoMonitorWindowSnapshot.as_of_date == as_of,
            GeoMonitorWindowSnapshot.filter_fp == (filter_fp or DEFAULT_FILTER_FP),
        )
    )
    if row is None or not isinstance(row.payload_json, dict):
        return None
    return dict(row.payload_json)


def upsert_window_snapshot(
    db: Session,
    *,
    tenant_id: int,
    kind: str,
    window_days: int,
    payload: dict[str, Any],
    as_of_date: date | None = None,
    filter_fp: str = DEFAULT_FILTER_FP,
) -> None:
    as_of = as_of_date or _as_of_customer_cutoff()
    fp = filter_fp or DEFAULT_FILTER_FP
    row = db.scalar(
        select(GeoMonitorWindowSnapshot).where(
            GeoMonitorWindowSnapshot.tenant_id == int(tenant_id),
            GeoMonitorWindowSnapshot.kind == kind,
            GeoMonitorWindowSnapshot.window_days == int(window_days),
            GeoMonitorWindowSnapshot.as_of_date == as_of,
            GeoMonitorWindowSnapshot.filter_fp == fp,
        )
    )
    now = datetime.now()
    if row is None:
        row = GeoMonitorWindowSnapshot(
            tenant_id=int(tenant_id),
            kind=kind,
            window_days=int(window_days),
            as_of_date=as_of,
            filter_fp=fp,
            payload_json=payload,
            computed_at=now,
        )
        db.add(row)
    else:
        row.payload_json = payload
        row.computed_at = now
    db.commit()


def build_workspace_brief_window_payload(
    db: Session,
    *,
    tenant_id: int,
    window_days: int,
    as_of_date: date | None = None,
) -> dict[str, Any] | None:
    """按 tenant 无会话物化工作台 brief（与客户读口径同源，不走菜单/销售鉴权）。

    2026-09-01 - warm used platform session and hit data-scope permission errors - use current=None
    """
    from app.services.monitor_service import workspace_brief

    as_of = as_of_date or _as_of_customer_cutoff()
    start = as_of - timedelta(days=max(1, int(window_days)) - 1)
    return workspace_brief(
        db,
        None,
        tenant_id=int(tenant_id),
        start_date=start,
        end_date=as_of,
        scope="full",
        purpose="geo",
    )


def warm_window_snapshots_for_tenant(db: Session, tenant_id: int) -> dict[str, Any]:
    as_of = _as_of_customer_cutoff()
    warmed = 0
    failed = 0
    for days in WINDOW_DAYS:
        try:
            payload = build_workspace_brief_window_payload(
                db, tenant_id=int(tenant_id), window_days=days, as_of_date=as_of
            )
            if not payload:
                failed += 1
                continue
            upsert_window_snapshot(
                db,
                tenant_id=int(tenant_id),
                kind="workspace_brief",
                window_days=days,
                payload=payload,
                as_of_date=as_of,
            )
            warmed += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "warm workspace window failed tenant=%s days=%s error=%s",
                tenant_id,
                days,
                exc,
            )
            try:
                db.rollback()
            except Exception:
                pass
    return {"tenant_id": int(tenant_id), "warmed": warmed, "failed": failed, "as_of": as_of.isoformat()}


def list_active_tenant_ids_for_warmup(db: Session, *, limit: int = 80) -> list[int]:
    from app.models.tenant import Tenant

    rows = db.scalars(
        select(Tenant.id)
        .where(Tenant.deleted.is_(False), Tenant.status.is_(True))
        .order_by(Tenant.id.asc())
        .limit(max(1, min(int(limit), 200)))
    )
    return [int(x) for x in rows]


def match_workspace_window_days(start_date: date | None, end_date: date | None) -> int | None:
    """请求区间若正好是截止日回望 7/30 天，可吃快照。"""
    if start_date is None or end_date is None:
        return None
    as_of = _as_of_customer_cutoff()
    if end_date != as_of:
        return None
    span = (end_date - start_date).days + 1
    if span in WINDOW_DAYS:
        return span
    return None
