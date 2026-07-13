from __future__ import annotations

from app.services.report_period_comparison_service import build_comparison, wrap_period_html_for_word
from app.services.playwright_health import playwright_chromium_health


def test_build_comparison_skips_demo_fallback_when_disabled() -> None:
    current = {"kpis": {"mention_rate": 60.0, "avg_rank": 2.5, "top3_rate": 45.0, "completed_count": 120}}
    comparison = build_comparison(
        "weekly",
        current,
        {"kpis": {"completed_count": 0}},
        "上周",
        used_demo_previous=False,
        allow_demo_fallback=False,
    )

    assert comparison["used_demo_previous"] is False
    assert comparison["kpis"]["mention_rate"]["previous"] is None
    assert comparison["kpis"]["avg_rank"]["previous"] is None


def test_wrap_period_html_for_word_adds_prog_id() -> None:
    raw = "<!doctype html><html><head><title>t</title></head><body>ok</body></html>"
    wrapped = wrap_period_html_for_word(raw).decode("utf-8")
    assert "ProgId" in wrapped
    assert "Word.Document" in wrapped


def test_playwright_chromium_health_returns_structured_status() -> None:
    result = playwright_chromium_health()
    assert result["status"] in {"ready", "error"}
    assert result.get("detail")


def test_parse_report_date_handles_iso_and_date() -> None:
    from datetime import date, datetime

    from app.services.report_period_comparison_service import _parse_report_date

    assert _parse_report_date("2026-07-01") == date(2026, 7, 1)
    assert _parse_report_date("2026-07-01T12:00:00") == date(2026, 7, 1)
    assert _parse_report_date(date(2026, 7, 2)) == date(2026, 7, 2)
    assert _parse_report_date(datetime(2026, 7, 3, 10, 0)) == date(2026, 7, 3)
    assert _parse_report_date("") is None
    assert _parse_report_date("bad") is None
