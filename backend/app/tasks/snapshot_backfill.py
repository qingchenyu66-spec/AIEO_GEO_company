"""快照补录异步截图任务（default 队列，不走模力 submit/sync）。"""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.share_page_screenshot_service import apply_backfill_screenshot

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.snapshot_backfill.capture_backfill_screenshot_task",
    ignore_result=True,
    # 2026-08-07 - 补录同步截图提交卡十几秒 - 改 Celery default 队列异步
    soft_time_limit=180,
    time_limit=240,
)
def capture_backfill_screenshot_task(subtask_id: str, snapshot_url: str) -> dict:
    db = SessionLocal()
    try:
        return apply_backfill_screenshot(db, subtask_id=subtask_id, snapshot_url=snapshot_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("backfill screenshot task failed subtask_id=%s", subtask_id)
        return {"status": "failed", "subtask_id": str(subtask_id), "error": str(exc)[:240]}
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.snapshot_backfill.refresh_source_daily_after_backfill_task",
    ignore_result=True,
    # 2026-08-17 - 补录同步信源日表拖过前端 30s - 异步重刷
    soft_time_limit=300,
    time_limit=360,
)
def refresh_source_daily_after_backfill_task(
    tenant_id: int,
    task_id: str,
    previous_stat_date: str | None,
    new_stat_date: str | None,
) -> dict:
    from app.services.monitor_source_rollup_service import _run_source_daily_after_backfill

    db = SessionLocal()
    try:
        _run_source_daily_after_backfill(
            db,
            tenant_id=int(tenant_id),
            task_id=str(task_id),
            previous_stat_date=previous_stat_date,
            new_stat_date=new_stat_date,
        )
        db.commit()
        return {
            "status": "ok",
            "tenant_id": int(tenant_id),
            "task_id": str(task_id),
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("source daily after backfill failed task_id=%s", task_id)
        return {"status": "failed", "task_id": str(task_id), "error": str(exc)[:240]}
    finally:
        db.close()
