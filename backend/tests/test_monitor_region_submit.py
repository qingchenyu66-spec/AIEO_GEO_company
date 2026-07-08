from app.schemas.monitor import FAST_MONITOR_MODE, MonitorTaskCreateRequest, PlatformConfig
from app.services.monitor_service import _build_submit_payload


def test_build_submit_payload_uses_single_region_code_string() -> None:
    payload = MonitorTaskCreateRequest(
        prompts=["问题A"],
        platforms=[PlatformConfig(platform="doubao", mode=FAST_MONITOR_MODE)],
        region_code=["330000"],
    )
    body = _build_submit_payload(payload, monitor_keywords="品牌A")
    assert body["regionCode"] == "330000"
