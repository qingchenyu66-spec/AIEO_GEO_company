"""预览缓存指纹：报告更新后旧落盘 HTML 失效。"""

from pathlib import Path


def test_read_or_build_uses_materialized_file_when_fingerprint_matches(tmp_path: Path, monkeypatch) -> None:
    from app.services import report_export_service as svc

    monkeypatch.setattr(svc, "REPORT_PREVIEW_ROOT", tmp_path)
    report = {"id": 42, "report_type": "weekly", "tenant_id": 6, "updated_at": "2026-07-14T10:00:00"}
    fp = svc._report_preview_fingerprint(report, theme="b")
    path = svc.report_preview_html_path(42)
    path.write_text(f"<!-- geo-preview-fp:{fp} -->\n<html>cached</html>", encoding="utf-8")

    html = svc.read_or_build_report_html_preview(db=None, report=report)  # type: ignore[arg-type]
    assert "cached" in html


def test_stale_preview_cache_rebuilds(tmp_path: Path, monkeypatch) -> None:
    from app.services import report_export_service as svc

    monkeypatch.setattr(svc, "REPORT_PREVIEW_ROOT", tmp_path)
    monkeypatch.setattr(svc, "build_report_html_preview", lambda db, report, theme="b": "<html>rebuilt</html>")
    report = {"id": 9, "report_type": "weekly", "tenant_id": 6, "updated_at": "2026-07-14T12:00:00"}
    path = svc.report_preview_html_path(9)
    path.write_text("<!-- geo-preview-fp:deadbeef -->\n<html>stale</html>", encoding="utf-8")

    html = svc.read_or_build_report_html_preview(db=None, report=report)  # type: ignore[arg-type]
    assert "rebuilt" in html
    assert "geo-preview-fp:" in html
    assert "stale" not in html


def test_materialize_writes_file(tmp_path: Path, monkeypatch) -> None:
    from app.services import report_export_service as svc

    monkeypatch.setattr(svc, "REPORT_PREVIEW_ROOT", tmp_path)
    monkeypatch.setattr(svc, "build_report_html_preview", lambda db, report, theme="b": "<html>built</html>")

    path = svc.materialize_report_html_preview(
        db=None,  # type: ignore[arg-type]
        report={"id": 7, "report_type": "weekly", "tenant_id": 6, "updated_at": "t1"},
    )
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "built" in text
    assert "geo-preview-fp:" in text
