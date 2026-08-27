"""稳定性 ④⑤⑥ 自检：告警阈值、窗口匹配、API 分轨。"""

from datetime import date

from app.services.stability_metrics_service import (
    classify_api_lane,
    evaluate_stability_alerts,
)
from app.services.window_snapshot_service import match_workspace_window_days


def test_classify_api_lane():
    assert classify_api_lane("/api/v1/auth/me") == "fast"
    assert classify_api_lane("/api/v1/monitor/ranking-matrix") == "heavy"
    assert classify_api_lane("/api/v1/monitor/molizhishu/callback") == "callback"
    assert classify_api_lane("/api/v1/analytics/competitor-compare") == "heavy"


def test_match_workspace_window_days_uses_cutoff(monkeypatch):
    from app.services import window_snapshot_service as mod

    monkeypatch.setattr(mod, "_as_of_customer_cutoff", lambda now=None: date(2026, 8, 20))
    assert match_workspace_window_days(date(2026, 8, 14), date(2026, 8, 20)) == 7
    assert match_workspace_window_days(date(2026, 7, 22), date(2026, 8, 20)) == 30
    assert match_workspace_window_days(date(2026, 8, 1), date(2026, 8, 20)) is None


def test_evaluate_stability_alerts_skips_fast_p95():
    metrics = {
        "latency": {"lanes": {"fast": {"p95_ms": 6000, "count": 20}, "heavy": {"p95_ms": 100}, "callback": {}}},
        "callback": {"hours": 24, "total": 0, "failed": 0, "failure_rate": 0},
        "matrix_jobs": {"max_ms": None},
    }
    alerts = evaluate_stability_alerts(metrics)
    assert not any(a["queue"] == "api_fast_p95" for a in alerts)


def test_evaluate_stability_alerts_skips_heavy_p95():
    metrics = {
        "latency": {"lanes": {"fast": {"p95_ms": 100}, "heavy": {"p95_ms": 15000}, "callback": {}}},
        "callback": {"hours": 24, "total": 0, "failed": 0, "failure_rate": 0},
        "matrix_jobs": {"max_ms": None},
    }
    alerts = evaluate_stability_alerts(metrics)
    assert not any(a["queue"] == "api_heavy_p95" for a in alerts)


def test_evaluate_stability_alerts_callback_rate():
    metrics = {
        "latency": {"lanes": {}},
        "callback": {"hours": 24, "total": 100, "failed": 20, "failure_rate": 0.2},
        "matrix_jobs": {"max_ms": 1000},
    }
    alerts = evaluate_stability_alerts(metrics)
    assert any(a["queue"] == "callback_fail_rate" for a in alerts)
