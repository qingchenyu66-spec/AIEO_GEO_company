"""Tests for brand exposure term collection."""

from types import SimpleNamespace

from app.services.brand_service import brand_exposure_terms


def test_brand_exposure_terms_keeps_industry_group_exposure():
    asset = SimpleNamespace(
        brand_name="艾迪亚控股集团有限公司",
        brand_short_name="艾迪亚",
        company_full_name="艾迪亚控股集团有限公司",
        aliases_json=[],
    )
    groups = [{
        "status": True,
        "monitor_keyword": "电梯广告公司推荐",
        "monitor_keywords": ["电梯广告公司推荐", "机场广告公司哪家好"],
        "exposure_terms": ["艾迪亚", "AIDIYA", "艾迪亚控股集团有限公司"],
    }]
    terms = brand_exposure_terms(asset, groups)
    assert "艾迪亚" in terms
    assert "AIDIYA" in terms


def test_brand_exposure_terms_falls_back_to_brand_name():
    asset = SimpleNamespace(
        brand_name="万唯",
        brand_short_name="",
        company_full_name="",
        aliases_json=["万唯中考"],
    )
    assert brand_exposure_terms(asset, [{"status": True, "monitor_keywords": ["初一同步"], "exposure_terms": []}]) == [
        "万唯",
        "万唯中考",
    ]
