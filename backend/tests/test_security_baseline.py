"""安全基线校验。"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.security_baseline import validate_flower_auth


def test_flower_auth_required_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "flower_enabled", True)
    monkeypatch.setattr(settings, "flower_basic_auth", "")
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="FLOWER_BASIC_AUTH"):
        validate_flower_auth()


def test_flower_auth_accepts_user_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "flower_enabled", True)
    monkeypatch.setattr(settings, "flower_basic_auth", "admin:secret")
    monkeypatch.setattr(settings, "app_env", "production")
    validate_flower_auth()


def test_flower_auth_rejects_invalid_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "flower_enabled", True)
    monkeypatch.setattr(settings, "flower_basic_auth", "invalid-no-colon")
    with pytest.raises(RuntimeError, match="user:password"):
        validate_flower_auth()
