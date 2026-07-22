"""媒体快照代理：密封 token + 白名单 host。"""

from __future__ import annotations

import pytest

from app.services import media_proxy_service as mps


def test_seal_roundtrip_hides_vendor_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    raw = "https://img.molizhishu.com/screenshots/2026/07/20/demo.png"
    public = mps.public_screenshot_url(raw)
    assert public is not None
    assert public.startswith("/api/v1/media/shot/")
    assert "molizhishu" not in public
    token = public.rsplit("/", 1)[-1]
    assert mps.unseal_shot_token(token) == raw


def test_rejects_non_allowlisted_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    assert mps.is_allowed_shot_url("https://evil.example/x.png") is False
    # 非白名单原样透出，避免误伤运营补录分享链
    assert mps.public_screenshot_url("https://www.doubao.com/share/x") == "https://www.doubao.com/share/x"


def test_tampered_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    raw = "https://img.molizhishu.com/a.png"
    token = mps.seal_shot_url(raw)
    bad = token[:-4] + ("0000" if not token.endswith("0000") else "1111")
    with pytest.raises(ValueError):
        mps.unseal_shot_token(bad)


def test_fetch_blocks_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")

    class _Resp:
        status_code = 302
        is_redirect = True
        headers = {"content-type": "text/html"}
        content = b""

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _Resp()

    monkeypatch.setattr(mps.httpx, "Client", _Client)
    with pytest.raises(ValueError, match="跳转"):
        mps.fetch_shot_response("https://img.molizhishu.com/a.png")
