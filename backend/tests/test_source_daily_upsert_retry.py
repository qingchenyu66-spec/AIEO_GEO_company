"""信源日表并发撞 uk：rollback 后重试写入。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, PendingRollbackError

from app.models.monitor import GeoMonitorSourceDaily
from app.services import monitor_source_rollup_service as svc


def test_rebuild_source_daily_retries_after_pending_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.monitor_stats_service.load_subtasks_for_business_date_range",
        lambda *_a, **_k: ([], [], {}),
    )
    monkeypatch.setattr(
        "app.services.monitor_service._aggregate_source_stats_pair_maps",
        lambda *_a, **_k: ({}, {}, {}, {}),
    )

    row = GeoMonitorSourceDaily(
        tenant_id=120,
        stat_date=date(2026, 9, 18),
        branded_json={},
        all_json={},
        daily_by_platform_json={},
    )
    calls = {"n": 0}

    def _upsert(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PendingRollbackError(
                "This Session's transaction has been rolled back",
                None,
                None,
            )
        return row

    monkeypatch.setattr(svc, "_upsert_source_daily_row", _upsert)

    out = svc.rebuild_source_daily_for_day(
        db,
        tenant_id=120,
        stat_date=date(2026, 9, 18),
        purchased_platforms={"doubao"},
        exposure_terms=["品牌"],
        config_fp="fp1",
    )
    assert out is row
    assert calls["n"] == 2
    assert db.rollback.called


def test_upsert_source_daily_recovers_duplicate_insert() -> None:
    db = MagicMock()
    existing = GeoMonitorSourceDaily(
        tenant_id=120,
        stat_date=date(2026, 9, 18),
        branded_json={},
        all_json={},
        daily_by_platform_json={},
    )
    db.scalar.side_effect = [None, existing]

    class _Nested:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    db.begin_nested.side_effect = lambda: _Nested()
    flush_calls = {"n": 0}

    def _flush():
        flush_calls["n"] += 1
        if flush_calls["n"] == 1:
            raise IntegrityError("INSERT", {}, Exception("Duplicate entry '120-2026-09-18'"))

    db.flush.side_effect = _flush

    row = svc._upsert_source_daily_row(
        db,
        tenant_id=120,
        stat_date=date(2026, 9, 18),
        config_fp="fp",
        branded_map={"u": {"url": "https://a.example"}},
        all_map={},
        branded_day_count=1,
        platform_day={"doubao": 1},
    )
    assert row is existing
    assert row.config_fp == "fp"
    assert row.daily_branded_count == 1
    assert flush_calls["n"] == 2
