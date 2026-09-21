"""分享页未展开 / 超时可自动再入队。"""

from __future__ import annotations

from app.services.share_page_fetch_service import share_page_unusable_message
from app.services.snapshot_backfill_service import (
    _BACKFILL_SHARE_TRANSIENT_MAX_RETRIES,
    _is_share_page_retryable_error,
)


def test_share_page_unexpanded_is_retryable() -> None:
    assert _is_share_page_retryable_error(share_page_unusable_message())
    assert _is_share_page_retryable_error("分享页打开超时，请稍后重试")
    assert not _is_share_page_retryable_error("分享页不可用或已失效，请更换可公开访问的链接")
    assert _BACKFILL_SHARE_TRANSIENT_MAX_RETRIES >= 2


def test_unexpanded_retry_waits_before_requeue() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.snapshot_backfill_service import (
        _BACKFILL_SHARE_RETRY_COUNTDOWN_SECONDS,
        _try_requeue_share_open_timeout_retry,
    )

    subtask = SimpleNamespace(
        subtask_id="st-retry",
        raw_result_json={
            "backfill_parse_status": "pending",
            "_pending_parse_job_id": "job-1",
            "_backfill_timeout_retries": 0,
        },
    )
    db = MagicMock()
    db.scalar.return_value = subtask
    seen: dict[str, int] = {}

    def _enqueue(*, subtask_id, parse_job_id, countdown=0):
        seen["countdown"] = countdown
        return "queued"

    import app.services.snapshot_backfill_service as mod

    original = mod.enqueue_backfill_parse
    mod.enqueue_backfill_parse = _enqueue
    try:
        out = _try_requeue_share_open_timeout_retry(
            db,
            subtask,
            parse_job_id="job-1",
            err_text=share_page_unusable_message(),
        )
    finally:
        mod.enqueue_backfill_parse = original
    assert out is not None
    assert out["status"] == "retrying"
    assert seen["countdown"] == _BACKFILL_SHARE_RETRY_COUNTDOWN_SECONDS
    assert _BACKFILL_SHARE_RETRY_COUNTDOWN_SECONDS >= 20
