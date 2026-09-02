"""驳回审批：销售原单复活重新提交。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.approval_service import (
    find_rejected_resubmit_candidate,
    resubmit_approval,
)


def test_resubmit_rejected_lead_diagnosis(monkeypatch) -> None:
    record = SimpleNamespace(
        id=12,
        status="rejected",
        operation_key="lead_diagnosis.create",
        module="lead_diagnosis",
        action="create",
        deleted=False,
        summary="新建售前诊断：测试品牌",
        tenant_id=None,
        target_id=None,
        requester_user_id=5,
        reviewer_user_id=9,
        reviewer_identity_id=2,
        review_comment="请补全竞品",
        reviewed_at=None,
        executed_result_json=None,
        created_at=__import__("datetime").datetime(2026, 9, 1),
        payload_json={
            "body": {
                "brand_name": "测试品牌",
                "prompts": ["问题一"],
                "competitors": [],
                "platforms": ["doubao"],
                "region_codes": [],
                "schedule_days": 3,
                "start_immediately": True,
            },
            "original_body": {
                "brand_name": "测试品牌",
                "prompts": ["问题一"],
                "competitors": [],
                "platforms": ["doubao"],
                "region_codes": [],
                "schedule_days": 3,
                "start_immediately": True,
            },
        },
    )
    db = MagicMock()
    db.scalar.return_value = record

    monkeypatch.setattr(
        "app.services.approval_service.requires_sales_approval",
        lambda db, current: True,
    )
    monkeypatch.setattr(
        "app.services.approval_service._notify_approval_resubmitted",
        lambda db, rec: None,
    )
    monkeypatch.setattr(
        "app.services.approval_service.approval_to_dict",
        lambda db, rec: {"id": rec.id, "status": rec.status, "payload": rec.payload_json},
    )

    current = SimpleNamespace(user=SimpleNamespace(id=5), identity=SimpleNamespace(id=1))
    out = resubmit_approval(
        db,
        current,
        12,
        {
            "body": {
                "brand_name": "测试品牌",
                "prompts": ["问题一", "问题二"],
                "competitors": ["竞品A"],
                "platforms": ["doubao"],
                "region_codes": [],
                "schedule_days": 4,
                "start_immediately": True,
            }
        },
    )
    assert record.status == "pending"
    assert record.reviewer_user_id is None
    assert record.review_comment is None
    assert record.payload_json["body"]["prompts"] == ["问题一", "问题二"]
    assert record.payload_json["resubmit_count"] == 1
    assert len(record.payload_json["rejection_history"]) == 1
    assert out["pending_approval"] is True
    assert out["resubmitted"] is True


def test_resubmit_rejects_non_requester(monkeypatch) -> None:
    record = SimpleNamespace(
        id=1,
        status="rejected",
        operation_key="lead_diagnosis.create",
        deleted=False,
        requester_user_id=5,
        payload_json={"body": {"brand_name": "A", "prompts": ["q"], "platforms": ["doubao"]}},
    )
    db = MagicMock()
    db.scalar.return_value = record
    monkeypatch.setattr("app.services.approval_service.requires_sales_approval", lambda *a, **k: True)
    current = SimpleNamespace(user=SimpleNamespace(id=99), identity=SimpleNamespace(id=1))
    with pytest.raises(PermissionError, match="原提交人"):
        resubmit_approval(db, current, 1, {"body": {"brand_name": "A", "prompts": ["q"], "platforms": ["doubao"]}})


def test_find_rejected_resubmit_candidate_by_brand_name(monkeypatch) -> None:
    record = SimpleNamespace(
        id=3,
        status="rejected",
        operation_key="lead_diagnosis.create",
        requester_user_id=7,
        tenant_id=None,
        target_id=None,
        payload_json={"body": {"brand_name": "唯品牌"}},
    )
    db = MagicMock()
    db.scalars.return_value = [record]
    current = SimpleNamespace(user=SimpleNamespace(id=7))
    found = find_rejected_resubmit_candidate(
        db,
        current,
        operation_key="lead_diagnosis.create",
        tenant_id=None,
        target_id=None,
        payload={"body": {"brand_name": "唯品牌", "prompts": ["q"], "platforms": ["doubao"]}},
    )
    assert found is record
