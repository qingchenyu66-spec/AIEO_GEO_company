"""余额接口权限：有运营总览即可查，不绑系统配置。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.v1.endpoints import platforms


def test_balance_endpoints_require_dashboard_not_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_require(_db, _current, menu_code: str, _action: str, *, detail: str | None = None) -> None:
        seen.append(menu_code)

    monkeypatch.setattr(platforms, "require_platform", lambda _c: None)
    monkeypatch.setattr(platforms, "require_platform_menu_permission", fake_require)
    monkeypatch.setattr(platforms, "fetch_molizhishu_balance", lambda: {"available": True})
    monkeypatch.setattr(platforms, "fetch_deepseek_balance", lambda: {"available": True})

    current = SimpleNamespace()
    db = MagicMock()
    platforms.molizhishu_balance(current=current, db=db)
    platforms.deepseek_balance(current=current, db=db)

    assert seen == ["platform.dashboard", "platform.dashboard"]
