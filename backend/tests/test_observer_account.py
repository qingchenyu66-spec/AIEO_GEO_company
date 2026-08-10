"""观察账号平台收窄自检。"""

from app.services.observer_account import (
    OBSERVER_PLATFORMS,
    OBSERVER_USERNAME,
    clamp_platform_query,
    is_observer_username,
    narrow_platform_codes,
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
    assert narrow_platform_codes(
        ["doubao", "kimi", "yuanbao", "kimi_mobile"],
        OBSERVER_PLATFORMS,
    ) == ["yuanbao", "kimi"]  # sort_platform_codes 市场序：元宝先于 kimi


def test_clamp_platform_query_forces_allowlist():
    obs = _Session(OBSERVER_USERNAME)
    platform, platforms = clamp_platform_query(obs, None, None)
    assert platform is None
    assert set(platforms.split(",")) == set(OBSERVER_PLATFORMS)

    platform, platforms = clamp_platform_query(obs, "doubao", None)
    assert platform is None
    assert set(platforms.split(",")) == set(OBSERVER_PLATFORMS)

    platform, platforms = clamp_platform_query(obs, "kimi", None)
    assert platform == "kimi"
    assert platforms is None

    other = _Session("idea")
    platform, platforms = clamp_platform_query(other, "doubao", None)
    assert platform == "doubao"
    assert platforms is None


def test_scope_asset_platforms_dict():
    data = {
        "monitored_platforms": ["doubao", "kimi", "yuanbao"],
        "keyword_groups": [{"platforms": ["doubao", "kimi"]}],
        "brand_word_groups": [{"platforms": ["yuanbao", "qianwen"]}],
    }
    scoped = scope_asset_platforms_dict(data, OBSERVER_PLATFORMS)
    assert scoped["monitored_platforms"] == ["yuanbao", "kimi"]
    assert scoped["keyword_groups"][0]["platforms"] == ["kimi"]
    assert scoped["brand_word_groups"][0]["platforms"] == ["yuanbao"]


def test_observer_hidden_menus():
    from app.services.observer_account import OBSERVER_HIDDEN_MENU_CODES

    assert "customer.links" in OBSERVER_HIDDEN_MENU_CODES
    assert "customer.diagnosis" in OBSERVER_HIDDEN_MENU_CODES
