"""审批 API 回归：query 参数 status 不得遮蔽 fastapi.status；列表分页结构。"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import CurrentSession, get_current_session
from app.main import app


@pytest.fixture
def approval_client(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )

    def _current():
        return session

    app.dependency_overrides[get_current_session] = _current
    monkeypatch.setattr(
        "app.api.v1.endpoints.approvals.list_approvals",
        MagicMock(side_effect=PermissionError("当前账号无权查看审批单")),
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_approval_list_permission_error_returns_403_not_500(approval_client):
    response = approval_client.get("/api/v1/approvals", params={"status": "pending"})
    assert response.status_code == 403
    assert "无权" in response.json()["detail"]


def test_approval_list_returns_paginated_payload(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr(
        "app.api.v1.endpoints.approvals.list_approvals",
        MagicMock(
            return_value={
                "items": [{"id": 1, "summary": "demo", "status": "pending"}],
                "total": 21,
                "page": 2,
                "page_size": 20,
            }
        ),
    )
    client = TestClient(app)
    try:
        response = client.get("/api/v1/approvals", params={"status": "pending", "page": 2, "page_size": 20})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 21
        assert data["page"] == 2
        assert data["page_size"] == 20
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == 1
    finally:
        app.dependency_overrides.clear()
