"""同步 upsert 不得覆盖人工补录正文。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import _upsert_subtask


def test_upsert_preserves_manual_snapshot_answer(monkeypatch):
    existing = SimpleNamespace(
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
        raw_result_json={
            "source": "manual_snapshot",
            "manual_rank_locked": True,
            "snapshot_url": "https://example.com/share",
        },
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
            "time": 123,
            "amount": 0.18,
        },
    )
    assert out.answer_content == "人工补录正文"
    assert out.mention_position == 3
    assert out.raw_result_json.get("source") == "manual_snapshot"
    assert out.raw_result_json.get("manual_rank_locked") is True
    assert out.remote_time == 123
