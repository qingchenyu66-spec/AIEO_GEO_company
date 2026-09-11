"""观察账号平台收窄自检。"""

from app.services.observer_account import (
    OBSERVER_USERNAME,
    clamp_platform_query,
    get_observer_platforms,
    is_observer_username,
    narrow_platform_codes,
    parse_observer_platforms,
    scope_asset_platforms_dict,
)


class _User:
    def __init__(self, username: str):
        self.username = username


class _Session:
    def __init__(self, username: str):
        self.user = _User(username)


def test_observer_username_and_narrow():
    assert is_observer_username(OBSERVER_USERNAME)
    assert not is_observer_username("idea")
    allow = parse_observer_platforms("qianwen,baiduai")
    assert narrow_platform_codes(
        ["doubao", "qianwen", "baiduai", "kimi"],
        allow,
    ) == ["baiduai", "qianwen"]  # sort_platform_codes 市场序：百度先于千问


def test_parse_observer_platforms_fallback():
    assert parse_observer_platforms("") == frozenset({"qianwen", "baiduai"})
    assert parse_observer_platforms(" kimi , yuanbao ") == frozenset({"kimi", "yuanbao"})


def test_clamp_platform_query_forces_allowlist(monkeypatch):
    allow = frozenset({"qianwen", "baiduai"})
    monkeypatch.setattr(
        "app.services.observer_account.get_observer_platforms",
        lambda db=None: allow,
    )
    obs = _Session(OBSERVER_USERNAME)
    platform, platforms = clamp_platform_query(obs, None, None)
    assert platform is None
    assert set(platforms.split(",")) == set(allow)

    platform, platforms = clamp_platform_query(obs, "doubao", None)
    assert platform is None
    assert set(platforms.split(",")) == set(allow)

    platform, platforms = clamp_platform_query(obs, "qianwen", None)
    assert platform == "qianwen"
    assert platforms is None

    other = _Session("idea")
    platform, platforms = clamp_platform_query(other, "doubao", None)
    assert platform == "doubao"
    assert platforms is None


def test_scope_asset_platforms_dict():
    allow = frozenset({"qianwen", "baiduai"})
    data = {
        "monitored_platforms": ["doubao", "qianwen", "baiduai"],
        "keyword_groups": [{"platforms": ["doubao", "qianwen"]}],
        "brand_word_groups": [{"platforms": ["baiduai", "kimi"]}],
    }
    scoped = scope_asset_platforms_dict(data, allow)
    assert scoped["monitored_platforms"] == ["baiduai", "qianwen"]
    assert scoped["keyword_groups"][0]["platforms"] == ["qianwen"]
    assert scoped["brand_word_groups"][0]["platforms"] == ["baiduai"]


def test_observer_hidden_menus():
    from app.services.observer_account import OBSERVER_HIDDEN_MENU_CODES

    assert "customer.links" in OBSERVER_HIDDEN_MENU_CODES
    assert "customer.diagnosis" in OBSERVER_HIDDEN_MENU_CODES


def test_get_observer_platforms_reads_settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.observer_account.settings.observer_platforms",
        "kimi,yuanbao",
    )

    def _boom(*_a, **_k):
        raise RuntimeError("no sys_config")

    monkeypatch.setattr(
        "app.services.system_config_service.get_runtime_config",
        _boom,
    )
    assert get_observer_platforms() == frozenset({"kimi", "yuanbao"})
