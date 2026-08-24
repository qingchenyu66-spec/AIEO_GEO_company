"""监测写后统一编排：日统计增量重算 + 缓存失效 + 窗口快照作废。

2026-08-21 - 稳定性桌面方案④：补录/回调/同步/排名落库走同一出口，避免漏清缓存
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask

logger = logging.getLogger(__name__)


def after_monitor_data_change(
    db: Session,
    *,
    tenant_id: int | None,
    task_id: str | None = None,
    task: GeoMonitorTask | None = None,
    subtask: GeoMonitorSubtask | None = None,
    previous_stat_date: date | None = None,
    bust_overview: bool = False,
) -> dict[str, Any]:
    """写路径收口。

    - 有 subtask+task：按补录口径重建涉及检测日（内含 invalidate）
    - 否则有 task_id：整任务涉及日重建，再 invalidate
    - 最后作废该企业窗口快照，下次读走日表/实时或等小时预热
    """
    resolved_tenant = tenant_id
    if resolved_tenant is None and task is not None and task.tenant_id is not None:
        resolved_tenant = int(task.tenant_id)

    mode = "none"
    try:
        from app.services.monitor_stats_service import (
            refresh_stats_after_subtask_backfill,
            refresh_stats_for_task,
        )

        if task is not None and subtask is not None:
            refresh_stats_after_subtask_backfill(
                db,
                task=task,
                subtask=subtask,
                previous_stat_date=previous_stat_date,
            )
            mode = "subtask"
        elif task_id:
            refresh_stats_for_task(db, str(task_id))
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise
            mode = "task"
            if resolved_tenant is not None:
                from app.services.monitor_service import invalidate_monitor_summary_cache

                invalidate_monitor_summary_cache(int(resolved_tenant), bust_overview=bust_overview)
    except Exception as exc:
        logger.warning(
            "after_monitor_data_change stats failed tenant_id=%s task_id=%s error=%s",
            resolved_tenant,
            task_id or (task.task_id if task else None),
            exc,
        )
        try:
            db.rollback()
        except Exception:
            pass

    if resolved_tenant is not None:
        try:
            from app.services.window_snapshot_service import invalidate_window_snapshots_for_tenant

            invalidate_window_snapshots_for_tenant(db, int(resolved_tenant))
        except Exception as exc:
            logger.warning(
                "invalidate_window_snapshots failed tenant_id=%s error=%s",
                resolved_tenant,
                exc,
            )

    return {"mode": mode, "tenant_id": resolved_tenant, "task_id": task_id}
