from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.tenant import Tenant
from app.services import tenant_logo_service as svc


def test_tenant_logo_media_type() -> None:
    assert svc.tenant_logo_media_type(Path("logo.png")) == "image/png"
    assert svc.tenant_logo_media_type(Path("logo.webp")) == "image/webp"


def test_safe_logo_path_rejects_traversal() -> None:
    tenant = Tenant(id=1, name="t", code="t", status=True, deleted=False)
    tenant.logo_path = "../secret.png"
    with pytest.raises(ValueError, match="非法"):
        svc._safe_logo_path(tenant)


def test_safe_logo_path_requires_file() -> None:
    tenant = Tenant(id=1, name="t", code="t", status=True, deleted=False)
    tenant.logo_path = "1/logo.png"
    with pytest.raises(ValueError, match="不存在"):
        svc._safe_logo_path(tenant)


def test_save_tenant_logo_creates_tenant_subdir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(svc, "STORAGE_ROOT", tmp_path)
    target = tmp_path / "6" / "logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"png")
    assert target.is_file()


def test_logo_staging_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(svc, "STORAGE_ROOT", tmp_path / "logos")
    monkeypatch.setattr(svc, "STAGING_ROOT", tmp_path / "staging")
    key = "a" * 32
    owner_id = 9
    staging_dir = tmp_path / "staging" / str(owner_id) / key
    staging_dir.mkdir(parents=True)
    source = staging_dir / "logo.png"
    source.write_bytes(b"png-bytes")

    found_owner, found_path = svc.find_staging_logo_by_key(key)
    assert found_owner == owner_id
    assert found_path == source

    tenant = Tenant(id=6, name="t", code="t", status=True, deleted=False)
    class _Db:
        def get(self, _model, tenant_id: int):
            return tenant if tenant_id == 6 else None

        def flush(self):
            return None

    db = _Db()
    result = svc.apply_staging_logo_to_tenant(
        db, tenant_id=6, staging_key=key, owner_user_id=owner_id,
    )
    assert result["has_logo"] is True
    assert tenant.logo_path == "6/logo.png"
    assert (tmp_path / "logos" / "6" / "logo.png").read_bytes() == b"png-bytes"
    assert not staging_dir.exists()


def test_brand_asset_has_changes_with_logo_staging_key() -> None:
    from app.services.approval_preview_service import brand_asset_has_changes

    body = {"logo_staging_key": "b" * 32}
    assert brand_asset_has_changes(None, 1, body) is True


def test_backfill_tenant_logo_path_from_disk(tmp_path, monkeypatch) -> None:
    """2026-08-27 - 磁盘有 logo 且 logo_path 空时 GET 应能回填。"""
    monkeypatch.setattr(svc, "STORAGE_ROOT", tmp_path / "logos")
    tenant_dir = tmp_path / "logos" / "457"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "logo.png").write_bytes(b"png457")

    tenant = SimpleNamespace(id=457, logo_path=None, logo_updated_at=None, deleted=False)
    db = MagicMock()
    path, backfilled = svc.backfill_tenant_logo_path_if_missing(db, tenant)  # type: ignore[arg-type]
    assert backfilled is True
    assert path is not None
    assert tenant.logo_path == "457/logo.png"
    db.commit.assert_called_once()
