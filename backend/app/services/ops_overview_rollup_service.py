"""运营总览重聚合：物理表 + 按需重建。"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.core.platform_order import sort_platform_items
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.ops import OpsOverviewRollup
from app.models.tenant import Tenant
from app.services.lead_diagnosis_service import build_platform_cost_ranking
from app.services.snapshot_backfill_service import list_snapshot_backfill_page


logger = logging.getLogger(__name__)

PLATFORM_STATS_WINDOW_DAYS = 7
COST_RANKING_WINDOW_DAYS = 30
# 表内数据在此时间内视为可直接读；超时则重建
ROLLUP_FRESH_SECONDS = 600
TERMINAL_STATUSES = {"completed", "partial_completed", "failed", "stopped"}
SCOPE_PLATFORM = "platform"


def overview_rollup_scope(tenant_ids: list[int] | None) -> str:
    if tenant_ids is None:
        return SCOPE_PLATFORM
    digest = ",".join(str(item) for item in sorted(tenant_ids))
    return f"tenants:{hashlib.md5(digest.encode('utf-8')).hexdigest()[:12]}"


def build_overview_heavy_rollup(
    db: Session,
    *,
    tenant_ids: list[int] | None,
    tenant_name_map: dict[int, str],
    service_active: int,
    tenant_total: int,
    today_cost: float = 0.0,
    terminal_statuses: set[str] | None = None,
) -> dict[str, Any]:
    """平台统计 / 费用排行 / 客户累计（含补录待办计数）。"""
    statuses = terminal_statuses or TERMINAL_STATUSES
    today = date.today()
    platform_since = datetime.combine(today - timedelta(days=PLATFORM_STATS_WINDOW_DAYS - 1), datetime.min.time())
    cost_since = datetime.combine(today - timedelta(days=COST_RANKING_WINDOW_DAYS - 1), datetime.min.time())

    platform_stmt = (
        select(
            GeoMonitorSubtask.platform,
            func.count(GeoMonitorSubtask.id),
            func.sum(case((GeoMonitorSubtask.status.in_(statuses), 1), else_=0)),
            func.sum(case((GeoMonitorSubtask.status == "failed", 1), else_=0)),
            func.coalesce(func.sum(GeoMonitorSubtask.amount), 0),
        )
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.created_at >= platform_since,
        )
    )
    if tenant_ids is not None:
        platform_stmt = platform_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    platform_rows = db.execute(
        platform_stmt.group_by(GeoMonitorSubtask.platform)
        .order_by(func.count(GeoMonitorSubtask.id).desc())
        .limit(12)
    ).all()
    platform_stats = sort_platform_items([
        {
            "platform": row[0],
            "total": int(row[1] or 0),
            "completed": int(row[2] or 0),
            "failed": int(row[3] or 0),
            "cost": float(row[4] or 0),
            "success_rate": round(((int(row[2] or 0) - int(row[3] or 0)) / max(1, int(row[2] or 0))) * 100, 1),
        }
        for row in platform_rows
    ])

    cost_ranking = build_platform_cost_ranking(
        db,
        tenant_name_map=tenant_name_map,
        tenant_ids=tenant_ids,
        limit=8,
        since=cost_since,
    )
    total_cost = round(sum(row["cost"] for row in cost_ranking), 4)

    total_subtasks_stmt = (
        select(func.count(GeoMonitorSubtask.id))
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(GeoMonitorTask.deleted.is_(False), GeoMonitorTask.created_at >= cost_since)
    )
    mentioned_subtasks_stmt = (
        select(func.count(GeoMonitorSubtask.id))
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.created_at >= cost_since,
            GeoMonitorSubtask.mention_position.isnot(None),
        )
    )
    source_count_stmt = (
        select(func.count(GeoMonitorSubtask.id))
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.created_at >= cost_since,
            GeoMonitorSubtask.reference_list_json.isnot(None),
        )
    )
    task_total_stmt = select(func.count(GeoMonitorTask.id)).where(
        GeoMonitorTask.deleted.is_(False),
        GeoMonitorTask.created_at >= cost_since,
    )
    if tenant_ids is not None:
        total_subtasks_stmt = total_subtasks_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
        mentioned_subtasks_stmt = mentioned_subtasks_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
        source_count_stmt = source_count_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
        task_total_stmt = task_total_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    total_subtasks = int(db.scalar(total_subtasks_stmt) or 0)
    mentioned_subtasks = int(db.scalar(mentioned_subtasks_stmt) or 0)
    source_count = int(db.scalar(source_count_stmt) or 0)
    mention_rate = round((mentioned_subtasks / max(1, total_subtasks)) * 100, 1)

    backfill_summary = list_snapshot_backfill_page(
        db,
        tenant_ids=tenant_ids,
        pending_only=True,
        limit=1,
        include_summary=True,
    )
    pending_backfill = int(backfill_summary.get("summary", {}).get("pending") or 0)

    return {
        "platform_stats": platform_stats,
        "cost_ranking": cost_ranking,
        "quota_overview": {
            "used_amount": total_cost,
            "today_amount": round(today_cost, 4),
            "estimated_month_amount": round(today_cost * 30, 4),
            "total_subtasks": total_subtasks,
            "avg_cost_per_subtask": round(total_cost / max(1, total_subtasks), 4),
        },
        "customer_data": {
            "tenant_total": tenant_total,
            "active_tenants": service_active,
            "task_total": int(db.scalar(task_total_stmt) or 0),
            "subtask_total": total_subtasks,
            "mention_rate": mention_rate,
            "source_count": source_count,
        },
        "pending_backfill": pending_backfill,
        "meta": {
            "platform_stats_window_days": PLATFORM_STATS_WINDOW_DAYS,
            "cost_ranking_window_days": COST_RANKING_WINDOW_DAYS,
            "source": "ops_overview_rollup",
        },
    }


def _is_fresh(row: OpsOverviewRollup, *, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    age = (now - row.computed_at).total_seconds()
    return age >= 0 and age <= ROLLUP_FRESH_SECONDS


def _upsert_rollup(db: Session, *, scope_key: str, payload: dict[str, Any]) -> OpsOverviewRollup:
    row = db.scalar(select(OpsOverviewRollup).where(OpsOverviewRollup.scope_key == scope_key))
    now = datetime.now()
    kind = "platform" if scope_key == SCOPE_PLATFORM else "tenants"
    if row is None:
        row = OpsOverviewRollup(
            scope_key=scope_key,
            scope_kind=kind,
            payload_json=payload,
            platform_window_days=PLATFORM_STATS_WINDOW_DAYS,
            cost_window_days=COST_RANKING_WINDOW_DAYS,
            computed_at=now,
        )
        db.add(row)
    else:
        row.scope_kind = kind
        row.payload_json = payload
        row.platform_window_days = PLATFORM_STATS_WINDOW_DAYS
        row.cost_window_days = COST_RANKING_WINDOW_DAYS
        row.computed_at = now
    db.flush()
    return row


def load_or_refresh_overview_rollup(
    db: Session,
    *,
    tenant_ids: list[int] | None,
    tenant_name_map: dict[int, str],
    service_active: int,
    tenant_total: int,
    today_cost: float = 0.0,
    force: bool = False,
) -> dict[str, Any]:
    """读物理预聚合；过期或 force 则重建并写回（写库用独立 session，避免污染请求事务）。"""
    from app.core.database import SessionLocal

    scope_key = overview_rollup_scope(tenant_ids)
    if not force:
        row = db.scalar(select(OpsOverviewRollup).where(OpsOverviewRollup.scope_key == scope_key))
        if row is not None and _is_fresh(row) and isinstance(row.payload_json, dict):
            payload = dict(row.payload_json)
            payload.setdefault("meta", {})
            if isinstance(payload["meta"], dict):
                payload["meta"] = {**payload["meta"], "source": "ops_overview_rollup", "cached": True}
            return payload

    payload = build_overview_heavy_rollup(
        db,
        tenant_ids=tenant_ids,
        tenant_name_map=tenant_name_map,
        service_active=service_active,
        tenant_total=tenant_total,
        today_cost=today_cost,
    )
    write_db = SessionLocal()
    try:
        _upsert_rollup(write_db, scope_key=scope_key, payload=payload)
        write_db.commit()
    except Exception:
        write_db.rollback()
        logger.exception("persist ops_overview_rollup failed scope=%s", scope_key)
    finally:
        write_db.close()

    payload = dict(payload)
    meta = dict(payload.get("meta") or {})
    meta.update({"source": "ops_overview_rollup", "cached": False})
    payload["meta"] = meta
    return payload


def refresh_platform_overview_rollup(db: Session) -> dict[str, Any]:
    """Beat：刷新全平台 scope。"""
    today = date.today()
    tenants = list(db.scalars(select(Tenant).where(Tenant.deleted.is_(False))))
    tenant_name_map = {tenant.id: tenant.name for tenant in tenants}

    def _active(tenant: Tenant) -> bool:
        if tenant.service_end_date and tenant.service_end_date < today:
            return False
        if not tenant.status:
            return False
        if tenant.service_start_date and tenant.service_start_date > today:
            return False
        return True

    service_active = sum(1 for tenant in tenants if _active(tenant))
    return load_or_refresh_overview_rollup(
        db,
        tenant_ids=None,
        tenant_name_map=tenant_name_map,
        service_active=service_active,
        tenant_total=len(tenants),
        today_cost=0.0,
        force=True,
    )


def purge_overview_rollups(db: Session, *, scope_key: str | None = None) -> int:
    """失效物理预聚合行。"""
    stmt = delete(OpsOverviewRollup)
    if scope_key:
        stmt = stmt.where(OpsOverviewRollup.scope_key == scope_key)
    result = db.execute(stmt)
    return int(result.rowcount or 0)
