"""Monitor task purpose isolation helpers."""

from app.core.monitor_purpose import (
    PURPOSE_BRAND_WORD,
    PURPOSE_GEO,
    normalize_task_purpose,
)


def test_normalize_task_purpose():
    assert normalize_task_purpose(None) == PURPOSE_GEO
    assert normalize_task_purpose("geo") == PURPOSE_GEO
    assert normalize_task_purpose("brand_word") == PURPOSE_BRAND_WORD
    assert normalize_task_purpose("weird") == PURPOSE_GEO


def test_monitor_task_create_request_purpose_default():
    from app.schemas.monitor import MonitorTaskCreateRequest, PlatformConfig

    payload = MonitorTaskCreateRequest(
        prompts=["测试问题"],
        platforms=[PlatformConfig(platform="deepseek")],
    )
    assert payload.purpose == PURPOSE_GEO
    brand = MonitorTaskCreateRequest(
        prompts=["品牌词"],
        platforms=[PlatformConfig(platform="deepseek")],
        purpose="brand_word",
    )
    assert brand.purpose == PURPOSE_BRAND_WORD
