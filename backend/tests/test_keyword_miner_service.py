"""keyword miner history service unit checks."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.keyword_miner_service import (
    _summarize_edit_notes,
    _summary_from_result,
    finalize_stale_jobs,
)


def test_summarize_edit_notes_shows_word_diff():
    text = _summarize_edit_notes(
        [
            {"kind": "select", "old_word": "旧词A", "word": "新词A", "reason": "更贴场景"},
            {"kind": "expand", "stage": "售后维保", "old_word": "旧问", "word": "新问", "reason": "品牌专属"},
        ]
    )
    assert "旧词A" in text and "新词A" in text
    assert "售后维保" in text
    assert "更贴场景" in text


def test_save_job_edits_writes_audit(monkeypatch):
    from app.services import keyword_miner_service as kms

    monkeypatch.setattr(kms, "_require_workbench", lambda *_a, **_k: None)
    monkeypatch.setattr(kms, "has_any_identity_menu_permission", lambda *_a, **_k: True)
    audits: list[tuple[str, str]] = []

    def fake_audit(_db, _current, action, desc, **_kw):
        audits.append((action, desc))

    monkeypatch.setattr(kms, "_audit", fake_audit)
    row = SimpleNamespace(
        id=7,
        job_id="job123",
        status="done",
        company="艾迪亚",
        product="",
        created_at=None,
        updated_at=None,
        job_created_at=None,
        job_updated_at=None,
        error=None,
        result_json={"selection": []},
        edited_result_json=None,
        edit_notes_json=None,
        payload_json=None,
        selection_count=0,
        expansion_count=0,
        task="both",
        platforms_json=[],
        source="",
        model="",
        top_words_json=[],
    )
    db = MagicMock()
    db.scalar.return_value = row
    current = SimpleNamespace(identity=SimpleNamespace(id=1), user=SimpleNamespace(id=1))
    payload = SimpleNamespace(
        edited_result={"selection": []},
        edit_notes=[{"kind": "select", "old_word": "A", "word": "B", "reason": "纠错"}],
    )
    kms.save_job_edits(db, current, "job123", payload)
    assert audits
    assert audits[0][0] == "修订选词"
    assert "job123" in audits[0][1]
    assert "A" in audits[0][1] and "B" in audits[0][1]


def test_list_examples_returns_paging_fields(monkeypatch):
    from app.services import keyword_miner_service as kms

    monkeypatch.setattr(kms, "_require_examples", lambda *_a, **_k: None)
    row = SimpleNamespace(
        id=1,
        kind="select",
        industry="家装",
        product_tags=[],
        stage="需求萌生",
        word="测试词",
        answer="",
        intent="",
        heat=None,
        note="",
        edit_reason="",
        status="active",
        source_job_id=None,
        source_company="",
        source_product="",
        use_count=0,
        created_at=None,
        updated_at=None,
    )
    db = MagicMock()
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [row]
    current = SimpleNamespace(identity=SimpleNamespace(id=1), user=SimpleNamespace(id=1))
    out = kms.list_examples(db, current, limit=20, offset=0)
    assert out["total"] == 1
    assert out["limit"] == 20
    assert out["offset"] == 0
    assert len(out["items"]) == 1
    assert out["items"][0]["word"] == "测试词"


def test_finalize_stale_jobs_marks_running_error():
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
    row = SimpleNamespace(status="running", error=None, job_updated_at=old, updated_at=old)
    db = MagicMock()
    db.scalars.return_value.all.return_value = [row]
    assert finalize_stale_jobs(db, older_than_seconds=3600) == 1
    assert row.status == "error"
    assert "超时" in (row.error or "")


def test_finalize_stale_jobs_skips_fresh_running():
    fresh = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    row = SimpleNamespace(status="running", error=None, job_updated_at=fresh, updated_at=fresh)
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    assert finalize_stale_jobs(db, older_than_seconds=3600) == 0
    assert row.status == "running"


def test_summary_from_result_counts_and_tops():
    result = {
        "source": "demo",
        "model": "m1",
        "meta": {"task": "both", "platforms": ["kimi", "豆包"]},
        "selection": [
            {"word": "a", "score": 10},
            {"word": "b", "score": 90},
            {"word": "c", "score": 50},
        ],
        "expansion": {"阶段1": [{"q": "x"}, {"q": "y"}], "阶段2": [{"q": "z"}]},
    }
    summary = _summary_from_result(result)
    assert summary["selection_count"] == 3
    assert summary["expansion_count"] == 3
    assert summary["task"] == "both"
    assert summary["platforms"] == ["kimi", "豆包"]
    assert summary["top_words"][0] == "b"
    assert summary["source"] == "demo"
    assert summary["model"] == "m1"


def test_summary_from_result_empty():
    summary = _summary_from_result(None)
    assert summary["selection_count"] == 0
    assert summary["expansion_count"] == 0
    assert summary["top_words"] == []
