"""Rebuild geo_monitor_daily_stat from historical subtasks."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorTask
from app.services.monitor_stats_service import refresh_stats_for_task

logger = logging.getLogger(__name__)


def main(limit: int | None = None) -> None:
    db = SessionLocal()
    try:
        stmt = (
            select(GeoMonitorTask.task_id)
            .where(GeoMonitorTask.deleted.is_(False))
            .order_by(GeoMonitorTask.id.desc())
        )
        if limit:
            stmt = stmt.limit(limit)
        task_ids = list(db.scalars(stmt))
        for index, task_id in enumerate(task_ids, start=1):
            refresh_stats_for_task(db, task_id)
            db.commit()
            if index % 50 == 0:
                logger.info("rebuilt stats for %s tasks", index)
        logger.info("done: rebuilt stats for %s tasks", len(task_ids))
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
