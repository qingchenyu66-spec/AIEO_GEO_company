# -*- coding: utf-8 -*-
"""受控补跑：排名类子任务库内 mention_position 为空时只补空落库。

用法（干跑）：
  PYTHONPATH=backend backend/.venv/Scripts/python.exe backend/scripts/backfill_null_mention_ranks.py --days 14 --dry-run

写库：
  PYTHONPATH=backend backend/.venv/Scripts/python.exe backend/scripts/backfill_null_mention_ranks.py --days 14 --limit 500

2026-08-14 - 矩阵/详情位次同源：历史「详情有、库空」补写 mention_position
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.monitor_service import (
    SUCCESS_STATUSES,
    ensure_subtask_rank_persisted,
    prompt_monitor_intent,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--tenant-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    since = datetime.now() - timedelta(days=max(1, args.days))
    db = SessionLocal()
    try:
        stmt = (
            select(GeoMonitorSubtask)
            .where(
                GeoMonitorSubtask.status.in_(tuple(SUCCESS_STATUSES)),
                GeoMonitorSubtask.mention_position.is_(None),
                GeoMonitorSubtask.answer_content.is_not(None),
                GeoMonitorSubtask.updated_at >= since,
            )
            .order_by(GeoMonitorSubtask.id.desc())
            .limit(max(1, args.limit) * 3)
        )
        rows = list(db.scalars(stmt))
        candidates: list[GeoMonitorSubtask] = []
        for item in rows:
            if prompt_monitor_intent(item.prompt) != "ranking":
                continue
            if not str(item.answer_content or "").strip():
                continue
            candidates.append(item)
            if len(candidates) >= args.limit:
                break

        print(
            {
                "since": since.isoformat(timespec="seconds"),
                "scanned": len(rows),
                "candidates": len(candidates),
                "dry_run": args.dry_run,
            }
        )
        if args.dry_run or not candidates:
            return

        task_cache: dict[str, GeoMonitorTask] = {}
        filled = 0
        for subtask in candidates:
            task = task_cache.get(subtask.task_id)
            if task is None:
                task = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == subtask.task_id))
                if task is None:
                    continue
                if args.tenant_id is not None and int(task.tenant_id or 0) != args.tenant_id:
                    continue
                task_cache[subtask.task_id] = task
            if ensure_subtask_rank_persisted(db, subtask, task):
                db.add(subtask)
                filled += 1
                if filled % 20 == 0:
                    db.commit()
        db.commit()
        print({"filled": filled})
    finally:
        db.close()


if __name__ == "__main__":
    main()
