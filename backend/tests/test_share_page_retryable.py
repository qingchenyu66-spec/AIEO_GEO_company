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
