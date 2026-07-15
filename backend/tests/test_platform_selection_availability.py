"""Self-check for platform selection normalize + availability formal gate."""

from app.services.platform_availability_service import (
    FORMAL_MIN_SAMPLES,
    SUCCESS_RATE_THRESHOLD,
    _availability_from_formal,
)
from app.services.platform_selection import normalize_platform_selections, selection_codes


def test_normalize_legacy_string_platforms():
    rows = normalize_platform_selections(["doubao", "kimi", "doubao"])
    assert selection_codes(rows) == ["doubao", "kimi"]
    assert rows[0]["mode"] == "standard"
    assert rows[0]["screenshot"] == 1


def test_normalize_object_platforms():
    rows = normalize_platform_selections([
        {"code": "yuanbao", "mode": "reasoning", "screenshot": 0},
        {"platform": "qianwen"},
    ])
    assert rows[0] == {"code": "yuanbao", "mode": "reasoning", "screenshot": 0}
    assert rows[1]["code"] == "qianwen"
    assert rows[1]["mode"] == "standard"


def test_formal_availability_thresholds():
    assert _availability_from_formal(None) is None
    assert _availability_from_formal({"total": FORMAL_MIN_SAMPLES - 1, "success": 5, "failed": 0}) is None
    assert _availability_from_formal({"total": 10, "success": 10, "failed": 0}) is True
    assert _availability_from_formal({"total": 10, "success": 0, "failed": 10}) is False
    soft_fail = int(FORMAL_MIN_SAMPLES * SUCCESS_RATE_THRESHOLD) - 1
    assert _availability_from_formal({"total": FORMAL_MIN_SAMPLES, "success": soft_fail, "failed": 1}) is False
