"""售前诊断审批通过后，创建人应记申请人而非审批人。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.dependencies import CurrentSession
from app.services.approval_executor import _exec_lead_create


def test_exec_lead_create_uses_requester_as_actor(monkeypatch) -> None:
    requester = SimpleNamespace(id=259, username="hanxinyan", display_name="韩鑫焱")
    requester_identity = SimpleNamespace(id=99, user_id=259, deleted=False, status=True)
    approver = SimpleNamespace(id=10, username="Xin", display_name="人间客")
    approver_identity = SimpleNamespace(id=1, user_id=10, deleted=False, status=True)
    record = SimpleNamespace(
        requester_user_id=259,
        requester_identity_id=99,
        target_id=None,
    )
    captured: dict = {}

    def _fake_create(db, current, payload, **kwargs):  # noqa: ANN001
        captured["user_id"] = current.user.id
        captured["identity_id"] = current.identity.id
        captured["enforce_position_platforms"] = kwargs.get("enforce_position_platforms", True)
        return {"id": 7, "created_by_user_id": current.user.id}

    monkeypatch.setattr(
        "app.services.approval_executor._requester_actor",
        lambda db, rec: (requester, requester_identity),
    )
    monkeypatch.setattr(
        "app.services.approval_executor.create_lead_diagnosis",
        _fake_create,
    )
    monkeypatch.setattr(
        "app.services.approval_executor.LeadDiagnosisCreateRequest.model_validate",
        lambda body: SimpleNamespace(brand_name="SAB伟星拉链"),
    )

    result = _exec_lead_create(
        MagicMock(),
        CurrentSession(user=approver, identity=approver_identity),
        record,  # type: ignore[arg-type]
        {"body": {"brand_name": "SAB伟星拉链"}},
    )
    assert captured["user_id"] == 259
    assert captured["identity_id"] == 99
    assert captured["enforce_position_platforms"] is False
    assert result["created_by_user_id"] == 259
