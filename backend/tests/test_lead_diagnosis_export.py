"""Lead diagnosis export must pass db into build_report_export (HTML/DOCX need it)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import lead_diagnosis_service as svc


def test_build_lead_diagnosis_export_passes_db(monkeypatch) -> None:
    detail = {
        "status": "ready",
        "brand_name": "测试品牌",
        "contact_phone": None,
        "contact_name": None,
        "competitors": [],
        "created_at": "2026-07-01T00:00:00",
        "diagnosis_result": {"diagnosis": {"sentiment_summary": "ok"}, "kpis": {}},
    }
    monkeypatch.setattr(svc, "get_lead_diagnosis", lambda *_a, **_k: detail)
    monkeypatch.setattr(
        svc,
        "_refresh_diagnosis_daily_ranks_for_export",
        lambda _db, _lead_id, result: result,
    )

    captured: dict = {}

    def _fake_export(report, fmt, *, db=None, theme="b"):
        captured["fmt"] = fmt
        captured["db"] = db
        captured["report_type"] = report.get("report_type")
        return b"<html>ok</html>", "t.html", "text/html"

    monkeypatch.setattr(
        "app.services.report_export_service.build_report_export",
        _fake_export,
    )

    db = MagicMock()
    content, filename, mime = svc.build_lead_diagnosis_export(
        db,
        lead_id=1,
        export_format="html",
        current=SimpleNamespace(),
    )
    assert content.startswith(b"<html>")
    assert filename.endswith(".html")
    assert "html" in mime
    assert captured["fmt"] == "html"
    assert captured["db"] is db
    assert captured["report_type"] == "diagnosis"
