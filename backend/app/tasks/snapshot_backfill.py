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
