"""创建企业须接入 queue_or_run（销售走审批，非销售直接落库）。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.main import app


def test_create_tenant_uses_queue_or_run(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr(
        "app.api.v1.endpoints.management._require_platform_menu",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.management.validate_service_period",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.management.raise_if_live_tenant_name_or_code_conflict",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.management.raise_if_new_tenant_name_unavailable",
        MagicMock(),
    )
    captured: dict = {}

    def fake_queue_or_run(db, current, **kwargs):
        captured.update(kwargs)
        return False, {"id": 99, "name": kwargs["summary"]}

    monkeypatch.setattr(
        "app.api.v1.endpoints.management.queue_or_run",
        fake_queue_or_run,
    )
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/management/tenants",
            json={
                "name": "审批接线测企业",
                "code": None,
                "service_start_date": "2026-01-01",
                "service_end_date": "2026-12-31",
            },
        )
        assert response.status_code == 200, response.text
        assert captured.get("operation_key") == "management.tenant.create"
        assert captured.get("module") == "tenant"
        assert captured.get("action") == "create"
        assert "审批接线测企业" in str(captured.get("summary") or "")
    finally:
        app.dependency_overrides.clear()


def test_restore_tenant_uses_queue_or_run(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    tenant = SimpleNamespace(id=12, name="停服企业", service_end_date=None, deleted=False)
    fake_db = MagicMock()
    fake_db.scalar.return_value = tenant
    def override_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.api.v1.endpoints.management._require_platform_menu", MagicMock())
    monkeypatch.setattr("app.api.v1.endpoints.management.guard_sales_tenant", MagicMock())
    captured: dict = {}

    def fake_queue_or_run(db, current, **kwargs):
        captured.update(kwargs)
        return True, {"pending_approval": True, "id": 8}

    monkeypatch.setattr("app.api.v1.endpoints.management.queue_or_run", fake_queue_or_run)
    client = TestClient(app)
    try:
        response = client.patch("/api/v1/management/tenants/12/restore")
        assert response.status_code == 200, response.text
        assert captured.get("operation_key") == "management.tenant.restore"
        assert captured.get("action") == "restore"
        assert captured.get("tenant_id") == 12
        assert "停服企业" in str(captured.get("summary") or "")
    finally:
        app.dependency_overrides.clear()


def test_brand_asset_bootstrap_queues_without_tenant_id(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr("app.api.v1.endpoints.brand.require_any_update_permission", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.sanitize_brand_asset_payload_for_grants",
        lambda db, current, payload: payload,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.raise_if_new_tenant_name_unavailable",
        MagicMock(),
    )
    captured: dict = {}

    def fake_queue_or_run(db, current, **kwargs):
        captured.update(kwargs)
        return True, {"pending_approval": True, "id": 9}

    monkeypatch.setattr("app.api.v1.endpoints.brand.queue_or_run", fake_queue_or_run)
    client = TestClient(app)
    try:
        response = client.put(
            "/api/v1/brand/asset",
            json={
                "tenant_id": None,
                "company_full_name": "草稿企业有限公司",
                "brand_name": "草稿企业有限公司",
                "service_start_date": "2026-01-01",
                "service_end_date": "2026-12-31",
            },
        )
        assert response.status_code == 200, response.text
        assert captured.get("operation_key") == "brand.asset.upsert"
        assert captured.get("action") == "create"
        assert captured.get("tenant_id") is None
        assert str(captured.get("summary") or "").startswith("新增企业：")
        body = (captured.get("payload") or {}).get("body") or {}
        assert body.get("company_full_name") == "草稿企业有限公司"
        assert body.get("service_start_date") == "2026-01-01"
    finally:
        app.dependency_overrides.clear()


def test_restore_and_bootstrap_preview():
    from app.services.approval_preview_service import build_approval_preview

    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(name="鸿联九五")
    restore = SimpleNamespace(
        operation_key="management.tenant.restore",
        tenant_id=3,
        target_id=3,
        payload_json={"tenant_id": 3},
    )
    restore_preview = build_approval_preview(db, restore)
    restore_text = " ".join(str(row.get("after") or "") for row in restore_preview["changes"])
    assert "恢复企业服务" in restore_text
    assert "鸿联九五" in restore_text

    bootstrap = SimpleNamespace(
        operation_key="brand.asset.upsert",
        tenant_id=None,
        target_id=None,
        payload_json={
            "body": {
                "company_full_name": "草稿企业有限公司",
                "service_start_date": "2026-01-01",
                "service_end_date": "2026-12-31",
                "official_url": "https://example.com",
                "description": "",
                "keyword_groups": [
                    {
                        "name": "词组 1",
                        "monitor_keywords": ["品牌词"],
                        "exposure_terms": ["露出甲"],
                        "platforms": [{"code": "doubao", "mode": "reasoning_search"}],
                    }
                ],
                "competitors": [{"name": "竞品甲"}],
                "brand_word_groups": [
                    {
                        "name": "品牌词组 1",
                        "monitor_keywords": ["测试"],
                        "run_mode": "once",
                        "platforms": [{"code": "kimi", "mode": "search"}],
                    }
                ],
            }
        },
    )
    boot_preview = build_approval_preview(db, bootstrap)
    boot_text = " ".join(str(row.get("after") or "") for row in boot_preview["changes"])
    boot_fields = [str(row.get("field") or "") for row in boot_preview["changes"]]
    assert "新增企业" in boot_text
    assert "草稿企业有限公司" in boot_text
    assert "官网 / 主站" in boot_fields
    assert "https://example.com" in boot_text
    assert "品牌说明" in boot_fields
    assert any(row.get("field") == "品牌说明" and row.get("after") == "（空）" for row in boot_preview["changes"])
    assert "竞品" in boot_fields
    assert "竞品甲" in boot_text
    assert "直接竞品" in boot_text
    by_field = {str(row.get("field") or ""): str(row.get("after") or "") for row in boot_preview["changes"]}
    assert by_field.get("监测词组「词组 1」监测词") == "品牌词"
    assert by_field.get("监测词组「词组 1」平台") == "豆包(深度思考)"
    assert by_field.get("监测词组「词组 1」露出词") == "露出甲"
    assert by_field.get("品牌词组「品牌词组 1」运行") == "仅本次"
    assert by_field.get("品牌词组「品牌词组 1」平台") == "Kimi(快速)"
    assert by_field.get("品牌词组「品牌词组 1」品牌词") == "测试"
    assert "监测词组「词组 1」" not in by_field


def test_new_tenant_name_blocks_live():
    from app.services.management_service import raise_if_new_tenant_name_unavailable

    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(
        name="鸿联九五",
        status=True,
        service_start_date=None,
        stop_reason=None,
    )
    try:
        raise_if_new_tenant_name_unavailable(db, "鸿联九五")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "已存在" in str(exc)


def test_new_tenant_name_blocks_others_pending_allows_own():
    from app.services.management_service import raise_if_new_tenant_name_unavailable

    db = MagicMock()
    db.scalar.return_value = None
    pending = SimpleNamespace(
        requester_user_id=2,
        operation_key="brand.asset.upsert",
        payload_json={"body": {"company_full_name": "鸿联九五"}},
    )
    db.scalars.return_value = [pending]
    try:
        raise_if_new_tenant_name_unavailable(db, "鸿联九五", allow_own_pending_user_id=1)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "待审批" in str(exc)

    db.scalars.return_value = [
        SimpleNamespace(
            requester_user_id=1,
            operation_key="brand.asset.upsert",
            payload_json={"body": {"company_full_name": "鸿联九五"}},
        )
    ]
    raise_if_new_tenant_name_unavailable(db, "鸿联九五", allow_own_pending_user_id=1)


def test_brand_asset_bootstrap_rejects_duplicate_name(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr("app.api.v1.endpoints.brand.require_any_update_permission", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.sanitize_brand_asset_payload_for_grants",
        lambda db, current, payload: payload,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.raise_if_new_tenant_name_unavailable",
        MagicMock(side_effect=ValueError("企业「草稿企业有限公司」已存在且服务中，请勿重复创建")),
    )
    queued = {"called": False}

    def fake_queue_or_run(db, current, **kwargs):
        queued["called"] = True
        return True, {"pending_approval": True, "id": 9}

    monkeypatch.setattr("app.api.v1.endpoints.brand.queue_or_run", fake_queue_or_run)
    client = TestClient(app)
    try:
        response = client.put(
            "/api/v1/brand/asset",
            json={
                "tenant_id": None,
                "company_full_name": "草稿企业有限公司",
                "brand_name": "草稿企业有限公司",
            },
        )
        assert response.status_code == 400, response.text
        assert "已存在" in (response.json().get("detail") or "")
        assert queued["called"] is False
    finally:
        app.dependency_overrides.clear()


def test_tenant_name_check_endpoint(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=1, display_name="tester"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr("app.api.v1.endpoints.management._require_platform_menu", MagicMock())
    monkeypatch.setattr("app.api.v1.endpoints.management.raise_if_new_tenant_name_unavailable", MagicMock())
    client = TestClient(app)
    try:
        ok = client.get("/api/v1/management/tenants/name-check", params={"name": "新企业有限公司"})
        assert ok.status_code == 200, ok.text
        assert ok.json().get("data", {}).get("available") is True

        monkeypatch.setattr(
            "app.api.v1.endpoints.management.raise_if_new_tenant_name_unavailable",
            MagicMock(side_effect=ValueError("企业「新企业有限公司」已存在且服务中，请勿重复创建")),
        )
        blocked = client.get("/api/v1/management/tenants/name-check", params={"name": "新企业有限公司"})
        assert blocked.status_code == 400, blocked.text
        assert "已存在" in (blocked.json().get("detail") or "")
    finally:
        app.dependency_overrides.clear()
