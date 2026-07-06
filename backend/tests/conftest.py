"""pytest 全局 fixture：测试环境放宽 Cookie/CSRF 策略。"""

from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _relax_auth_for_tests() -> None:
    """保留 JSON access_token 供 TestClient 使用 Bearer；关闭 CSRF 避免每个用例重复带头。"""
    settings.auth_expose_token_in_body = True
    settings.auth_csrf_enabled = False
