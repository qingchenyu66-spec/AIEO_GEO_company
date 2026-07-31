"""Brand word group helpers: run_mode keys and no exposure_terms."""

from datetime import datetime

from app.services.schedule_service import (
    brand_word_once_schedule_key,
    brand_word_weekly_schedule_key,
    is_brand_word_schedule_key,
)


def test_brand_word_schedule_key_helpers():
    now = datetime(2026, 7, 20, 9, 0, 0)  # Monday
    weekly = brand_word_weekly_schedule_key(now)
    once = brand_word_once_schedule_key(now)
    assert weekly == "bw20260720-0900"
    assert once.startswith("bwonce-202607200900")
    assert is_brand_word_schedule_key(f"{weekly}-kw12")
    assert is_brand_word_schedule_key(f"{once}-kw12")
    assert not is_brand_word_schedule_key("20260720-0930-kw12")


def test_keyword_group_platforms_accepts_brand_word_group():
    """审批执行 save_brand_word_groups 会把 BrandWordGroup ORM 传给平台 helper。"""
    from app.models.brand import BrandWordGroup
    from app.services.brand_service import keyword_group_monitor_keywords, keyword_group_platforms

    group = BrandWordGroup(
        tenant_id=1,
        brand_asset_id=1,
        name="品牌词组1",
        monitor_keyword="金隅涂料",
        monitor_keywords_json=["金隅涂料"],
        platforms_json=[{"code": "deepseek", "mode": "standard"}],
        run_mode="once",
    )
    assert keyword_group_platforms(group) == ["deepseek"]
    assert keyword_group_monitor_keywords(group) == ["金隅涂料"]


def test_brand_word_group_save_request_run_mode():
    from app.schemas.brand import BrandWordGroupSaveRequest

    once = BrandWordGroupSaveRequest(monitor_keywords=["品牌A"], run_mode="once", platforms=["deepseek"])
    weekly = BrandWordGroupSaveRequest(monitor_keywords=["品牌A"], run_mode="weekly", platforms=["deepseek"])
    assert once.run_mode == "once"
    assert weekly.run_mode == "weekly"
    assert "exposure_terms" not in BrandWordGroupSaveRequest.model_fields


def test_brand_word_match_terms_fallback_logic():
    """品牌词组无露出词时，应用非行业品牌词作为匹配别名（与 molizhishu_monitor_terms 一致）。"""
    from app.services.brand_service import _is_industry_monitor_keyword

    class _Asset:
        brand_name = "鸿联九五"
        brand_short_name = "鸿联"
        company_full_name = "鸿联九五信息产业股份有限公司"
        aliases_json = ["HL95"]

    asset = _Asset()
    group_keywords = ["鸿联九五", "鸿联"]
    group_exposure: list[str] = []
    match_terms = group_exposure or [
        kw for kw in group_keywords if kw and not _is_industry_monitor_keyword(kw, asset)
    ]
    assert match_terms == ["鸿联九五", "鸿联"]
    assert _is_industry_monitor_keyword("电梯广告投放", asset)


def test_save_brand_word_submit_filter_includes_weekly():
    """保存后立即提交候选：启用且有监测词即可，不限 run_mode=once。"""
    from app.services.brand_service import keyword_group_monitor_keywords

    class _G:
        def __init__(self, status: bool, run_mode: str, keywords: list[str]):
            self.status = status
            self.run_mode = run_mode
            self.monitor_keyword = keywords[0] if keywords else ""
            self.monitor_keywords_json = keywords

    rows = [
        _G(True, "weekly", ["艾迪亚"]),
        _G(True, "once", ["品牌B"]),
        _G(False, "weekly", ["停用"]),
        _G(True, "weekly", []),
    ]
    submit = [
        item
        for item in rows
        if item.status
        and keyword_group_monitor_keywords(
            {
                "monitor_keyword": item.monitor_keyword,
                "monitor_keywords": item.monitor_keywords_json or [],
            }
        )
    ]
    assert [g.run_mode for g in submit] == ["weekly", "once"]
    assert [g.monitor_keyword for g in submit] == ["艾迪亚", "品牌B"]
