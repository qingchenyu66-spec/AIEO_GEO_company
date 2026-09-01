"""窗口快照预热：无会话物化，不假扮平台账号、不撞菜单鉴权。"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.services import window_snapshot_service as snap_mod
from app.services.monitor_service import _workspace_competitor_score


def test_build_workspace_brief_window_payload_passes_current_none(monkeypatch):
    calls: list[dict] = []

    def fake_brief(db, current, **kwargs):
        calls.append({"current": current, **kwargs})
        return {"ok": True, "tenant_id": kwargs.get("tenant_id")}

    monkeypatch.setattr(snap_mod, "_as_of_customer_cutoff", lambda **kwargs: date(2026, 9, 1))
    monkeypatch.setattr("app.services.monitor_service.workspace_brief", fake_brief)
    # 预热路径不得再依赖平台会话
    monkeypatch.setattr(
        "app.services.platform_session.load_platform_session",
        lambda db: (_ for _ in ()).throw(AssertionError("load_platform_session must not be called")),
    )

    out = snap_mod.build_workspace_brief_window_payload(MagicMock(), tenant_id=42, window_days=7)
    assert out == {"ok": True, "tenant_id": 42}
    assert len(calls) == 1
    assert calls[0]["current"] is None
    assert calls[0]["tenant_id"] == 42
    assert calls[0]["start_date"] == date(2026, 8, 26)
    assert calls[0]["end_date"] == date(2026, 9, 1)


def test_workspace_competitor_score_uses_unauth_aggregate(monkeypatch):
    seen: dict = {}

    def fake_aggregate(db, tenant_id, *, start_date, end_date, subtask_limit=5000):
        seen["tenant_id"] = tenant_id
        seen["start_date"] = start_date
        seen["end_date"] = end_date
        seen["subtask_limit"] = subtask_limit
        return {
            "sample_total": 10,
            "rows": [
                {"is_brand": True, "mention_rate": 40.0},
                {"is_brand": False, "mention_rate": 25.0},
            ],
        }

    monkeypatch.setattr(
        "app.services.competitor_analytics_service.aggregate_competitor_period_stats",
        fake_aggregate,
    )
    # 若仍误走鉴权版，应直接失败
    monkeypatch.setattr(
        "app.services.competitor_analytics_service.build_competitor_compare_summary",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not use gated summary")),
    )

    out = _workspace_competitor_score(MagicMock(), 7, 2, as_of=date(2026, 9, 1))
    assert seen["tenant_id"] == 7
    assert seen["start_date"] == date(2026, 8, 26)
    assert seen["end_date"] == date(2026, 9, 1)
    assert out["competitor_lead_delta"] == 15.0
    assert out["competitor_score"] == 65.0


def test_workspace_competitor_score_skips_when_no_competitors():
    out = _workspace_competitor_score(MagicMock(), 1, 0)
    assert out["competitor_score"] is None


def test_workspace_brief_none_current_requires_tenant():
    from app.services.monitor_service import workspace_brief

    with pytest.raises(ValueError, match="需指定企业"):
        workspace_brief(MagicMock(), None)
