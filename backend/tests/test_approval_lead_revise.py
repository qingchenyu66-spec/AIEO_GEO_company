"""售前诊断新建审批：保存修改与原文快照。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.approval_service import (
    normalize_lead_create_approval_payload,
    revise_lead_diagnosis_create_approval,
)


def test_normalize_lead_create_approval_payload_freezes_original() -> None:
    payload = normalize_lead_create_approval_payload(
        {"body": {"brand_name": "A", "platforms": ["doubao"]}},
        refresh_original=True,
    )
    assert payload["body"]["brand_name"] == "A"
    assert payload["original_body"]["brand_name"] == "A"
    payload["body"]["platforms"] = ["kimi"]
    assert payload["original_body"]["platforms"] == ["doubao"]


def test_revise_lead_diagnosis_keeps_brand_and_original(monkeypatch) -> None:
    original = {
        "brand_name": "SAB伟星拉链",
        "competitors": ["YKK"],
        "platforms": ["doubao"],
        "region_codes": [],
        "schedule_days": 3,
        "prompts": ["问题一"],
        "contact_note": "旧",
        "start_immediately": True,
    }
    record = SimpleNamespace(
        id=47,
        status="pending",
        operation_key="lead_diagnosis.create",
        deleted=False,
        summary="新建售前诊断：SAB伟星拉链",
        payload_json={"body": dict(original), "original_body": dict(original)},
    )
    db = MagicMock()
    db.scalar.return_value = record

    monkeypatch.setattr(
        "app.services.approval_service.ensure_can_review",
        lambda db, current: None,
    )
    monkeypatch.setattr(
        "app.services.approval_service.approval_to_dict",
        lambda db, rec: {"id": rec.id, "payload": rec.payload_json},
    )

    current = SimpleNamespace(user=SimpleNamespace(id=10), identity=SimpleNamespace(id=1))
    out = revise_lead_diagnosis_create_approval(
        db,
        current,
        47,
        {
            "competitors": ["YKK", "SBS"],
            "platforms": ["doubao", "chatgpt"],
            "schedule_days": 4,
            "prompts": ["问题一", "问题二"],
            "contact_note": "新备注",
            "region_codes": [],
        },
    )
    body = record.payload_json["body"]
    original_body = record.payload_json["original_body"]
    assert body["brand_name"] == "SAB伟星拉链"
    assert body["platforms"] == ["doubao", "chatgpt"]
    assert body["schedule_days"] == 4
    assert original_body["platforms"] == ["doubao"]
    assert original_body["contact_note"] == "旧"
    assert out["id"] == 47


def test_revise_lead_diagnosis_schedule_datetimes(monkeypatch) -> None:
    from datetime import datetime, timedelta

    original = {
        "brand_name": "测试诊断",
        "competitors": ["竞品A"],
        "platforms": ["doubao"],
        "region_codes": [],
        "schedule_days": 3,
        "prompts": ["问题一"],
        "contact_note": "备注",
        "start_immediately": True,
    }
    record = SimpleNamespace(
        id=48,
        status="pending",
        operation_key="lead_diagnosis.create",
        deleted=False,
        summary="新建售前诊断：测试诊断",
        payload_json={"body": dict(original), "original_body": dict(original)},
    )
    db = MagicMock()
    db.scalar.return_value = record

    monkeypatch.setattr("app.services.approval_service.ensure_can_review", lambda db, current: None)
    monkeypatch.setattr(
        "app.services.approval_service.approval_to_dict",
        lambda db, rec: {"id": rec.id, "payload": rec.payload_json},
    )

    base = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
    future = base.replace(hour=9, minute=30).strftime("%Y-%m-%dT%H:%M")
    future2 = base.replace(hour=14, minute=30).strftime("%Y-%m-%dT%H:%M")
    slots = [future, future2]

    current = SimpleNamespace(user=SimpleNamespace(id=10), identity=SimpleNamespace(id=1))
    revise_lead_diagnosis_create_approval(
        db,
        current,
        48,
        {"schedule_datetimes": slots},
    )
    body = record.payload_json["body"]
    assert body["lead_context"]["schedule_datetimes"] == slots
    assert body["schedule_days"] == 2


def test_revise_rejects_non_lead_operation(monkeypatch) -> None:
    record = SimpleNamespace(
        id=1,
        status="pending",
        operation_key="management.tenant.create",
        deleted=False,
        payload_json={"body": {}},
    )
    db = MagicMock()
    db.scalar.return_value = record
    monkeypatch.setattr("app.services.approval_service.ensure_can_review", lambda *a, **k: None)
    with pytest.raises(ValueError, match="售前诊断新建"):
        revise_lead_diagnosis_create_approval(db, SimpleNamespace(), 1, {})
