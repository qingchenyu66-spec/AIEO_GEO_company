"""售前诊断：运营在任务配置页修改（不含问法）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.lead_diagnosis import LeadDiagnosisConfigReviseRequest
from app.services.lead_diagnosis_service import can_revise_lead_diagnosis_config, revise_lead_diagnosis_config


def test_can_revise_config_blocks_sales(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.require_lead_diagnosis_access",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.is_sales_identity",
        lambda db, identity: True,
    )
    current = SimpleNamespace(identity=SimpleNamespace(id=1))
    assert can_revise_lead_diagnosis_config(MagicMock(), current) is False


def test_revise_config_updates_competitors_not_platforms(monkeypatch) -> None:
    from datetime import datetime, timedelta

    future_base = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
    future_slots = [
        future_base.strftime("%Y-%m-%dT%H:%M"),
        (future_base + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M"),
        (future_base + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
    ]
    lead = SimpleNamespace(
        id=9,
        brand_name="测试品牌",
        status="pending",
        prompts_json=["问题一", "问题二"],
        competitors_json=["旧竞品"],
        brand_aliases_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=["09:30", "14:30", "20:30"],
        schedule_days=3,
        lead_context_json={},
        contact_name=None,
        contact_phone=None,
        contact_note=None,
        runs=[],
        diagnosis_date=__import__("datetime").date(2026, 9, 2),
        created_at=__import__("datetime").datetime(2026, 9, 2, 10, 0, 0),
    )
    db = MagicMock()
    db.scalar.return_value = lead

    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.can_revise_lead_diagnosis_config",
        lambda db, current: True,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.get_lead_diagnosis",
        lambda db, lead_id, current=None: {"id": lead_id, "platforms": lead.platforms_json},
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service._skip_orphan_pending_runs",
        lambda _lead: None,
    )

    current = SimpleNamespace(user=SimpleNamespace(id=2), identity=SimpleNamespace(id=3))
    out = revise_lead_diagnosis_config(
        db,
        current,
        9,
        LeadDiagnosisConfigReviseRequest(
            competitors=["竞品A", "竞品B"],
            platforms=["doubao", "kimi"],
            schedule_datetimes=future_slots,
        ),
    )
    assert lead.competitors_json == ["竞品A", "竞品B"]
    assert lead.platforms_json == ["doubao"]
    assert lead.lead_context_json.get("schedule_datetimes") == future_slots
    assert lead.prompts_json == ["问题一", "问题二"]
    assert out["id"] == 9


def test_revise_config_rejects_future_datetime_before_now(monkeypatch) -> None:
    from datetime import datetime

    lead = SimpleNamespace(
        id=10,
        brand_name="测试品牌",
        status="collecting",
        prompts_json=["问题一"],
        competitors_json=[],
        brand_aliases_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=["09:30", "14:30", "20:30"],
        schedule_days=3,
        lead_context_json={},
        contact_name=None,
        contact_phone=None,
        contact_note=None,
        runs=[],
        diagnosis_date=__import__("datetime").date(2026, 9, 2),
        created_at=datetime(2026, 9, 2, 10, 0, 0),
    )
    db = MagicMock()
    db.scalar.return_value = lead

    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.can_revise_lead_diagnosis_config",
        lambda db, current: True,
    )

    current = SimpleNamespace(user=SimpleNamespace(id=2), identity=SimpleNamespace(id=3))
    with pytest.raises(ValueError, match="不能早于当前时间"):
        revise_lead_diagnosis_config(
            db,
            current,
            10,
            LeadDiagnosisConfigReviseRequest(
                schedule_datetimes=["2020-01-01T09:30", "2030-01-01T09:30"],
            ),
        )


def test_revise_config_allows_past_completed_run_slots(monkeypatch) -> None:
    from datetime import datetime, timedelta

    past = (datetime.now() - timedelta(days=1)).replace(minute=30, second=0, microsecond=0)
    future = (datetime.now() + timedelta(days=2)).replace(second=0, microsecond=0)
    past_key = past.strftime("%Y-%m-%dT%H:%M")
    future_key = future.strftime("%Y-%m-%dT%H:%M")
    run = SimpleNamespace(
        schedule_label=f"{past.strftime('%Y-%m-%d %H:%M')} · 全部区域",
        schedule_key=past.strftime("%Y%m%d") + "-" + past.strftime("%H%M"),
        status="completed",
        task_id="task-1",
    )
    lead = SimpleNamespace(
        id=11,
        brand_name="测试品牌",
        status="collecting",
        prompts_json=["问题一"],
        competitors_json=[],
        brand_aliases_json=[],
        platforms_json=["doubao"],
        region_codes_json=["330000"],
        schedule_times_json=["09:30", "14:30", "20:30"],
        schedule_days=3,
        lead_context_json={},
        contact_name=None,
        contact_phone=None,
        contact_note=None,
        runs=[run],
        diagnosis_date=past.date(),
        created_at=past - timedelta(days=1),
    )
    db = MagicMock()
    db.scalar.return_value = lead
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.can_revise_lead_diagnosis_config",
        lambda db, current: True,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.get_lead_diagnosis",
        lambda db, lead_id, current=None: {"id": lead_id},
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service._skip_orphan_pending_runs",
        lambda _lead: None,
    )
    current = SimpleNamespace(user=SimpleNamespace(id=2), identity=SimpleNamespace(id=3))
    revise_lead_diagnosis_config(
        db,
        current,
        11,
        LeadDiagnosisConfigReviseRequest(
            schedule_datetimes=[past_key, future_key],
        ),
    )
    assert lead.lead_context_json.get("schedule_datetimes") == [past_key, future_key]
