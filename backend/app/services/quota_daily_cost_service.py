"""模力监测按日消耗（运营总览费用日历）。"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask


def month_range(year: int, month: int) -> tuple[date, date]:
    """Return [month_start, next_month_start)."""
    if month < 1 or month > 12:
        raise ValueError("month 必须在 1–12")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def build_month_day_rows(
    *,
    year: int,
    month: int,
    amount_by_day: dict[date, float],
    count_by_day: dict[date, int] | None = None,
) -> list[dict[str, Any]]:
    """Fill every calendar day in the month; missing days are zero."""
    start, end = month_range(year, month)
    counts = count_by_day or {}
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        amount = round(float(amount_by_day.get(cursor, 0) or 0), 4)
        rows.append({
            "date": cursor.isoformat(),
            "amount": amount,
            "subtask_count": int(counts.get(cursor, 0) or 0),
        })
        cursor += timedelta(days=1)
    return rows


def heat_level(amount: float, max_amount: float) -> int:
    """0–4 heat bucket for calendar cells. ponytail: linear buckets; upgrade if log scale needed."""
    if amount <= 0 or max_amount <= 0:
        return 0
    ratio = amount / max_amount
    if ratio <= 0.25:
        return 1
    if ratio <= 0.5:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


def fetch_molizhishu_daily_costs(
    db: Session,
    *,
    year: int,
    month: int,
    tenant_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Aggregate GeoMonitorSubtask.amount by task created date for one calendar month."""
    start, end = month_range(year, month)
    if tenant_ids is not None and not tenant_ids:
        days = build_month_day_rows(year=year, month=month, amount_by_day={})
        return _pack_response(year=year, month=month, days=days)

    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.min.time())
    day_col = func.date(GeoMonitorTask.created_at)
    stmt = (
        select(
            day_col.label("day"),
            func.coalesce(func.sum(GeoMonitorSubtask.amount), 0),
            func.count(GeoMonitorSubtask.id),
        )
        .join(GeoMonitorSubtask, GeoMonitorSubtask.task_id == GeoMonitorTask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.created_at >= start_dt,
            GeoMonitorTask.created_at < end_dt,
        )
        .group_by(day_col)
    )
    if tenant_ids is not None:
        stmt = stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))

    amount_by_day: dict[date, float] = {}
    count_by_day: dict[date, int] = {}
    for day_value, amount, count in db.execute(stmt).all():
        if day_value is None:
            continue
        if isinstance(day_value, datetime):
            day_value = day_value.date()
        elif not isinstance(day_value, date):
            day_value = date.fromisoformat(str(day_value)[:10])
        amount_by_day[day_value] = float(amount or 0)
        count_by_day[day_value] = int(count or 0)

    days = build_month_day_rows(
        year=year,
        month=month,
        amount_by_day=amount_by_day,
        count_by_day=count_by_day,
    )
    return _pack_response(year=year, month=month, days=days)


def _pack_response(*, year: int, month: int, days: list[dict[str, Any]]) -> dict[str, Any]:
    amounts = [float(item.get("amount") or 0) for item in days]
    month_total = round(sum(amounts), 4)
    max_amount = round(max(amounts) if amounts else 0, 4)
    enriched = [
        {
            **item,
            "heat": heat_level(float(item.get("amount") or 0), max_amount),
        }
        for item in days
    ]
    # 周一为一周起始，便于前端排格
    first_weekday = date(year, month, 1).weekday()  # Mon=0
    return {
        "year": year,
        "month": month,
        "month_label": f"{year}-{month:02d}",
        "source": "molizhishu_monitor",
        "source_label": "模力监测按日消耗",
        "deepseek_note": "DeepSeek 仅余额快照，无官方按日流水",
        "days_in_month": calendar.monthrange(year, month)[1],
        "first_weekday": first_weekday,
        "month_total": month_total,
        "max_amount": max_amount,
        "days": enriched,
    }
