"""Logo 进审批：端到端回归，确认不破坏既有品牌/审批链路。"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.main import app
from app.services import tenant_logo_service as logo_svc
from app.services.approval_preview_service import _brand_changes, brand_asset_has_changes, build_approval_preview


@pytest.fixture
def logo_client(monkeypatch, tmp_path):
    monkeypatch.setattr(logo_svc, "STORAGE_ROOT", tmp_path / "logos")
    monkeypatch.setattr(logo_svc, "STAGING_ROOT", tmp_path / "staging")
    session = CurrentSession(
        user=MagicMock(id=42, display_name="销售甲"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr("app.api.v1.endpoints.brand.require_any_update_permission", lambda *a, **k: None)
    client = TestClient(app)
    yield client, session
    app.dependency_overrides.clear()


def test_upload_logo_staging_and_fetch(logo_client):
    client, _session = logo_client
    png = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    upload = client.post(
        "/api/v1/brand/logo-staging",
        files={"file": ("logo.png", png, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    key = upload.json()["data"]["staging_key"]
    assert len(key) == 32

    fetch = client.get(f"/api/v1/brand/logo-staging/{key}")
    assert fetch.status_code == 200
    assert fetch.headers["content-type"].startswith("image/")


def test_brand_preview_shows_logo_change(monkeypatch):
    key = "c" * 32
    monkeypatch.setattr(
        "app.services.approval_preview_service.get_brand_asset",
        lambda db, tenant_id: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.list_keyword_groups",
        lambda db, tenant_id: [],
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.asset_to_dict",
        lambda asset, groups: {
            "company_full_name": "旧企业",
            "brand_name": "旧企业",
            "official_url": "",
            "description": "",
            "region_codes": [],
            "schedule_times": ["09:30"],
            "keyword_groups": [],
        },
    )
    tenant = SimpleNamespace(logo_path="1/logo.png")
    db = MagicMock()
    db.get.return_value = tenant

    rows = _brand_changes(db, 1, {"company_full_name": "旧企业", "schedule_times": ["09:30"], "logo_staging_key": key})
    logo_rows = [row for row in rows if row.get("field") == "企业 Logo"]
    assert len(logo_rows) == 1
    assert logo_rows[0]["after_image_url"] == f"/api/v1/brand/logo-staging/{key}"
    assert logo_rows[0]["before_image_url"] == "/api/v1/management/tenants/1/logo"


def test_brand_asset_queue_carries_logo_staging_key(monkeypatch):
    session = CurrentSession(
        user=MagicMock(id=42, display_name="销售甲"),
        identity=MagicMock(id=10, identity_type="PLATFORM", position_id=1),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr("app.api.v1.endpoints.brand.require_any_update_permission", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.sanitize_brand_asset_payload_for_grants",
        lambda db, current, payload: payload,
    )
    monkeypatch.setattr("app.api.v1.endpoints.brand.requires_sales_approval", lambda db, current: True)
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.get_brand_asset",
        lambda db, tenant_id: SimpleNamespace(tenant_id=1),
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.brand.brand_asset_has_changes",
        lambda db, tenant_id, body: True,
    )
    captured: dict = {}

    def fake_queue_or_run(db, current, **kwargs):
        captured.update(kwargs)
        return True, {"pending_approval": True, "id": 99}

    monkeypatch.setattr("app.api.v1.endpoints.brand.queue_or_run", fake_queue_or_run)
    client = TestClient(app)
    key = "d" * 32
    try:
        response = client.put(
            "/api/v1/brand/asset",
            json={
                "tenant_id": 1,
                "company_full_name": "测试企业",
                "brand_name": "测试企业",
                "logo_staging_key": key,
            },
        )
        assert response.status_code == 200, response.text
        body = (captured.get("payload") or {}).get("body") or {}
        assert body.get("logo_staging_key") == key
        assert captured.get("operation_key") == "brand.asset.upsert"
    finally:
        app.dependency_overrides.clear()


def test_exec_brand_asset_applies_staging(monkeypatch, tmp_path):
    monkeypatch.setattr(logo_svc, "STORAGE_ROOT", tmp_path / "logos")
    monkeypatch.setattr(logo_svc, "STAGING_ROOT", tmp_path / "staging")
    key = "e" * 32
    owner_id = 42
    staging_dir = tmp_path / "staging" / str(owner_id) / key
    staging_dir.mkdir(parents=True)
    (staging_dir / "logo.png").write_bytes(b"png-data")

    tenant = SimpleNamespace(id=6, name="t", code="t", status=True, deleted=False, logo_path=None, logo_updated_at=None)
    asset = SimpleNamespace(tenant_id=6, brand_name="测试企业")
    db = MagicMock()
    db.get.return_value = tenant

    monkeypatch.setattr(
        "app.services.approval_executor.save_brand_asset_maybe_bootstrap",
        lambda db, payload, current, owner_user_id: asset,
    )
    from app.services.approval_executor import _exec_brand_asset

    record = SimpleNamespace(requester_user_id=owner_id)
    result = _exec_brand_asset(
        db,
        MagicMock(),
        record,
        {
            "body": {
                "tenant_id": 6,
                "company_full_name": "测试企业",
                "brand_name": "测试企业",
                "logo_staging_key": key,
            }
        },
    )
    assert result["tenant_id"] == 6
    assert tenant.logo_path == "6/logo.png"
    assert (tmp_path / "logos" / "6" / "logo.png").read_bytes() == b"png-data"
    assert not staging_dir.exists()


def test_reject_approval_cleans_logo_staging(monkeypatch, tmp_path):
    monkeypatch.setattr(logo_svc, "STAGING_ROOT", tmp_path / "staging")
    key = "f" * 32
    owner_id = 42
    staging_dir = tmp_path / "staging" / str(owner_id) / key
    staging_dir.mkdir(parents=True)
    (staging_dir / "logo.png").write_bytes(b"x")

    record = SimpleNamespace(
        id=9,
        status="pending",
        requester_user_id=owner_id,
        payload_json={"body": {"logo_staging_key": key}},
        reviewer_user_id=None,
        reviewer_identity_id=None,
        review_comment=None,
        reviewed_at=None,
        summary="修改企业配置",
    )
    db = MagicMock()
    db.scalar.return_value = record
    db.commit = MagicMock()
    db.refresh = MagicMock()

    monkeypatch.setattr("app.services.approval_service.ensure_can_review", lambda db, current: None)
    monkeypatch.setattr(
        "app.services.approval_service.approval_to_dict",
        lambda db, rec: {"id": rec.id, "status": rec.status},
    )
    monkeypatch.setattr(
        "app.services.system_notification_service.resolve_approval_pending_notification",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.system_notification_service.upsert_approval_result_notification",
        lambda *a, **k: None,
    )

    from app.services.approval_service import reject_approval

    reject_approval(db, MagicMock(), 9, comment="驳回")
    assert not staging_dir.exists()


def test_identical_brand_without_logo_still_skips_approval(monkeypatch):
    """仅 logo_staging_key 才算变更；无 key 时与旧逻辑一致。"""
    class FakeAsset:
        pass

    current = {
        "company_full_name": "戮望保研",
        "brand_name": "戮望保研",
        "brand_short_name": "",
        "official_url": "",
        "description": "",
        "region_codes": [],
        "schedule_type": "daily_times",
        "schedule_times": ["09:30"],
        "schedule_frequency": 1,
        "schedule_weekdays": [],
        "schedule_month_days": [],
        "aliases": ["品牌"],
        "keyword_groups": [
            {
                "id": 1,
                "name": "综合",
                "monitor_keywords": ["品牌"],
                "exposure_terms": ["品牌"],
                "platforms": [{"code": "doubao", "mode": "standard", "screenshot": 1}],
                "status": True,
            }
        ],
    }
    monkeypatch.setattr(
        "app.services.approval_preview_service.get_brand_asset",
        lambda db, tenant_id: FakeAsset(),
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.list_keyword_groups",
        lambda db, tenant_id: [],
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.asset_to_dict",
        lambda asset, groups: current,
    )
    assert brand_asset_has_changes(None, 1, dict(current)) is False
    assert brand_asset_has_changes(None, 1, {**current, "logo_staging_key": "a" * 32}) is True


def test_bootstrap_preview_with_logo_staging(monkeypatch):
    key = "1" * 32
    db = MagicMock()
    record = SimpleNamespace(
        operation_key="brand.asset.upsert",
        tenant_id=None,
        target_id=None,
        payload_json={
            "body": {
                "company_full_name": "新企业有限公司",
                "logo_staging_key": key,
                "keyword_groups": [],
            }
        },
    )
    preview = build_approval_preview(db, record)
    logo_rows = [row for row in preview["changes"] if row.get("field") == "企业 Logo"]
    assert len(logo_rows) == 1
    assert logo_rows[0]["after_image_url"] == f"/api/v1/brand/logo-staging/{key}"


def test_bootstrap_extras_applies_logo_staging(monkeypatch):
    """2026-08-27 - 新建企业保存时 Logo 须随 bootstrap 落库。"""
    from app.schemas.brand import BrandAssetSaveRequest
    from app.services.brand_service import _apply_bootstrap_extras

    key = "c" * 32
    calls: list[dict] = []

    def _fake_apply(**kwargs):
        calls.append(kwargs)
        return {"tenant_id": kwargs["tenant_id"]}

    monkeypatch.setattr(
        "app.services.tenant_logo_service.maybe_apply_logo_staging_from_body",
        lambda db, **kwargs: _fake_apply(**kwargs) or None,
    )
    monkeypatch.setattr("app.services.brand_service.save_competitor", lambda *a, **k: None)
    monkeypatch.setattr("app.services.brand_service.save_brand_word_groups", lambda *a, **k: None)

    payload = BrandAssetSaveRequest(
        company_full_name="自助测试企业",
        brand_name="自助测试企业",
        logo_staging_key=key,
        keyword_groups=[],
    )
    current = CurrentSession(
        user=MagicMock(id=7),
        identity=MagicMock(id=1, identity_type="PLATFORM"),
    )
    _apply_bootstrap_extras(MagicMock(), 457, payload, current)
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == 457
    assert calls[0]["owner_user_id"] == 7
