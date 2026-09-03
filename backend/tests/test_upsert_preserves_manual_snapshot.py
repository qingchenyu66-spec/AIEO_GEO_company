"""同步 upsert 不得覆盖人工补录正文。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import (
    _upsert_subtask,
    subtask_blocks_remote_content_overwrite,
)


def _existing(**raw_extra):
    raw = {
        "source": "manual_snapshot",
        "manual_rank_locked": True,
        "snapshot_url": "https://example.com/share",
    }
    raw.update(raw_extra)
    return SimpleNamespace(
        id=1,
        subtask_id="18428409",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="礼品公司推荐",
        status="completed",
        answer_content="人工补录正文",
        mention_position=3,
        mention_context=None,
        page_screenshot=None,
        reference_list_json=None,
        citation_list_json=None,
        reasoning_process_json=None,
        recommended_questions_json=None,
        media_content_json=None,
        error_message=None,
        proxy_ip=None,
        amount=None,
        raw_result_json=raw,
        all_rankings_json=None,
        competitor_rankings_json=None,
        sentiment=None,
        remote_time=None,
    )


class FakeScalar:
    def __init__(self, value):
        self._value = value

    def scalar(self, _stmt):
        return self._value


def test_subtask_blocks_remote_content_overwrite_flags() -> None:
    assert subtask_blocks_remote_content_overwrite(_existing()) is True
    assert (
        subtask_blocks_remote_content_overwrite(
            SimpleNamespace(raw_result_json={"backfill_parse_status": "pending"})
        )
        is True
    )
    assert (
        subtask_blocks_remote_content_overwrite(SimpleNamespace(raw_result_json={"source": "api"}))
        is False
    )


def test_upsert_preserves_manual_snapshot_answer(monkeypatch):
    existing = _existing()
    db = FakeScalar(existing)
    monkeypatch.setattr(
        "app.services.monitor_service.select",
        lambda *args, **kwargs: MagicMock(),
    )

    out = _upsert_subtask(
        db,
        "t1",
        {
            "subTaskId": "18428409",
            "platform": "doubao",
            "status": "completed",
            "answerContent": "远端易赠网正文应被忽略",
            "pageScreenshot": "https://img.molizhishu.com/screenshots/old.png",
            "time": 123,
            "amount": 0.18,
        },
    )
    assert out.answer_content == "人工补录正文"
    assert out.mention_position == 3
    assert out.page_screenshot is None
    assert out.raw_result_json.get("source") == "manual_snapshot"
    assert out.raw_result_json.get("manual_rank_locked") is True
    assert out.remote_time == 123


def test_upsert_preserves_pending_backfill_parse(monkeypatch):
    """2026-09-03 - 入队后未标 source 窗口 - pending 也不得被 sync 盖回旧图。"""
    existing = _existing(
        source="api",
        manual_rank_locked=False,
        backfill_parse_status="pending",
        screenshot_pending=True,
        before_backfill={"page_screenshot": "https://old.png"},
    )
    existing.page_screenshot = None
    existing.answer_content = "模力旧正文"
    db = FakeScalar(existing)
    monkeypatch.setattr(
        "app.services.monitor_service.select",
        lambda *args, **kwargs: MagicMock(),
    )

    out = _upsert_subtask(
        db,
        "t1",
        {
            "subTaskId": "18428409",
            "platform": "doubao",
            "status": "completed",
            "answerContent": "远端应被忽略",
            "pageScreenshot": "https://img.molizhishu.com/screenshots/remote.png",
            "time": 456,
            "amount": 0.2,
        },
    )
    assert out.answer_content == "模力旧正文"
    assert out.page_screenshot is None
    assert out.raw_result_json.get("backfill_parse_status") == "pending"
    assert out.raw_result_json.get("before_backfill", {}).get("page_screenshot") == "https://old.png"
    assert out.remote_time == 456
