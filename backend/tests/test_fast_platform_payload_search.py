"""快速 mode 提交为 search；深度提交为 reasoning_search。"""

from app.schemas.monitor import PlatformConfig
from app.services.monitor_service import _fast_platform_payload


def test_fast_platform_payload_maps_standard_to_search():
    payload = _fast_platform_payload(PlatformConfig(platform="deepseek", mode="standard", screenshot=0))
    assert payload["mode"] == "search"
    assert payload["screenshot"] == 1


def test_fast_platform_payload_maps_reasoning_to_reasoning_search():
    payload = _fast_platform_payload(PlatformConfig(platform="doubao", mode="reasoning", screenshot=1))
    assert payload["mode"] == "reasoning_search"
    assert payload["screenshot"] == 1


def test_fast_platform_payload_keeps_reasoning_search():
    payload = _fast_platform_payload(PlatformConfig(platform="kimi", mode="reasoning_search", screenshot=1))
    assert payload["mode"] == "reasoning_search"
