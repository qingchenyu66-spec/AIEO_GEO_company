# -*- coding: utf-8 -*-
"""按 (tenant_id, stat_date, platform) 去重重建 geo_monitor_daily_stat。

比逐 task refresh 更快，且同 key 只重建一次，避开会话内重复 INSERT。
加列 top3_count 后须对本脚本 --apply 回填，否则历史日 Top3 仍为 0。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorDailyStat, GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset
from app.services.monitor_stats_service import (
    TERMINAL_STATUSES,
    _detect_stat_date,
    _rebuild_daily_stat_for_platform_day,
)
from app.services.schedule_context import lead_diagnosis_runs_for_tasks, schedule_runs_for_tasks

sys.stdout.reconfigure(encoding="utf-8")


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def collect_keys(
    db,
    *,
    tenant_id: int | None,
    since: date | None,
    until: date | None,
) -> list[tuple[int, date, str]]:
    """从现有日统计 + 终态子任务涉及的检测日收集待重建 key。"""
    keys: set[tuple[int, date, str]] = set()

    stat_stmt = select(
        GeoMonitorDailyStat.tenant_id,
        GeoMonitorDailyStat.stat_date,
        GeoMonitorDailyStat.platform,
    )
    if tenant_id is not None:
        stat_stmt = stat_stmt.where(GeoMonitorDailyStat.tenant_id == tenant_id)
    if since:
        stat_stmt = stat_stmt.where(GeoMonitorDailyStat.stat_date >= since)
    if until:
        stat_stmt = stat_stmt.where(GeoMonitorDailyStat.stat_date <= until)
    for tid, day, platform in db.execute(stat_stmt).all():
        if tid is None or day is None or not platform:
            continue
        keys.add((int(tid), day, str(platform)))

    task_stmt = (
        select(GeoMonitorTask)
        .where(GeoMonitorTask.deleted.is_(False), GeoMonitorTask.tenant_id.isnot(None))
    )
    if tenant_id is not None:
        task_stmt = task_stmt.where(GeoMonitorTask.tenant_id == tenant_id)
    tasks = list(db.scalars(task_stmt))
    if not tasks:
        return sorted(keys, key=lambda x: (x[0], x[1], x[2]))

    by_tenant: dict[int, list[GeoMonitorTask]] = {}
    for task in tasks:
        by_tenant.setdefault(int(task.tenant_id), []).append(task)

    for tid, tenant_tasks in by_tenant.items():
        task_ids = [t.task_id for t in tenant_tasks]
        subtasks = list(
            db.scalars(
                select(GeoMonitorSubtask).where(
                    GeoMonitorSubtask.task_id.in_(task_ids),
                    GeoMonitorSubtask.status.in_(TERMINAL_STATUSES),
                )
            )
        )
        if not subtasks:
            continue
        schedule_runs = schedule_runs_for_tasks(db, task_ids)
        lead_runs = lead_diagnosis_runs_for_tasks(db, task_ids)
        asset = get_brand_asset(db, tid)
        task_map = {t.task_id: t for t in tenant_tasks}
        for item in subtasks:
            task = task_map.get(item.task_id)
            if task is None:
                continue
            day = _detect_stat_date(
                item,
                task,
                schedule_run=schedule_runs.get(item.task_id),
                lead_run=lead_runs.get(item.task_id),
                asset=asset,
            )
            if day is None:
                continue
            if since and day < since:
                continue
            if until and day > until:
                continue
            keys.add((tid, day, str(item.platform)))

    return sorted(keys, key=lambda x: (x[0], x[1], x[2]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild geo_monitor_daily_stat keys")
    parser.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    parser.add_argument("--tenant-id", type=int)
    parser.add_argument("--since", help="YYYY-MM-DD")
    parser.add_argument("--until", help="YYYY-MM-DD")
    parser.add_argument("--batch-commit", type=int, default=50)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        keys = collect_keys(
            db,
            tenant_id=args.tenant_id,
            since=_parse_day(args.since),
            until=_parse_day(args.until),
        )
        report = {
            "apply": bool(args.apply),
            "tenant_id": args.tenant_id,
            "key_count": len(keys),
            "sample_keys": [
                {"tenant_id": t, "stat_date": d.isoformat(), "platform": p}
                for t, d, p in keys[:15]
            ],
        }
        if not args.apply:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return

        rebuilt = 0
        for index, (tid, day, platform) in enumerate(keys, start=1):
            _rebuild_daily_stat_for_platform_day(
                db,
                tenant_id=tid,
                stat_date=day,
                platform=platform,
            )
            rebuilt += 1
            if index % args.batch_commit == 0:
                db.commit()
        db.commit()
        report["rebuilt"] = rebuilt
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
