from __future__ import annotations

from pathlib import Path

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
