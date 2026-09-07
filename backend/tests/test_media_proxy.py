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


def test_absolute_public_screenshot_hides_vendor_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    monkeypatch.setattr(mps.settings, "wechat_h5_base_url", "https://www.aieokj.com/h5/diagnosis/")
    raw = "https://img.molizhishu.com/screenshots/2026/07/20/demo.png"
    absolute = mps.public_screenshot_url_absolute(raw)
    assert absolute is not None
    assert absolute.startswith("https://www.aieokj.com/api/v1/media/shot/")
    assert "molizhishu" not in absolute


def test_proxy_snapshot_evidence_for_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    monkeypatch.setattr(mps.settings, "wechat_h5_base_url", "https://www.aieokj.com/h5/diagnosis/")
    from app.services.lead_diagnosis_service import _proxy_snapshot_evidence_for_export

    evid = {
        "问法||doubao": {
            "screenshot_url": "https://img.molizhishu.com/screenshots/a.png",
            "page_screenshot": "https://img.molizhishu.com/screenshots/a.png",
            "runs": [
                {
                    "run_no": 1,
                    "screenshot_url": "https://img.molizhishu.com/screenshots/a.png",
                    "share_url": "https://www.doubao.com/share/x",
                }
            ],
        }
    }
    out = _proxy_snapshot_evidence_for_export(evid)
    shot = out["问法||doubao"]["screenshot_url"]
    assert "molizhishu" not in shot
    assert shot.startswith("https://www.aieokj.com/api/v1/media/shot/")
    assert out["问法||doubao"]["runs"][0]["share_url"] == "https://www.doubao.com/share/x"
    assert "molizhishu" not in out["问法||doubao"]["runs"][0]["screenshot_url"]


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


def test_media_shot_endpoint_allows_anonymous_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """下载/转发 HTML 无登录态也能出图。"""
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    raw = "https://img.molizhishu.com/screenshots/anon-ok.png"
    token = mps.seal_shot_url(raw)

    def _fake_fetch(url: str) -> tuple[bytes, str]:
        assert url == raw
        return b"\x89PNG\r\n\x1a\n", "image/png"

    # 勿 monkeypatch httpx.Client：TestClient 也用同一套 httpx
    import app.api.v1.endpoints.media as media_ep

    monkeypatch.setattr(media_ep, "fetch_shot_response", _fake_fetch)
    monkeypatch.setattr(media_ep, "unseal_shot_token", mps.unseal_shot_token)

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get(f"/api/v1/media/shot/{token}")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    assert "image/png" in (response.headers.get("content-type") or "")


def test_media_shot_endpoint_rejects_bad_token_without_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mps.settings, "secret_key", "unit-test-secret-key")
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/media/shot/not-a-real-token")
    assert response.status_code == 404


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
