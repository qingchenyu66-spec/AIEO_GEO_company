# -*- coding: utf-8 -*-
"""门店括号双钥匹配：头+店同在一行，勿误伤南市场店 / 国别括号。"""

from app.services.lead_brand_match import (
    exact_configured_term_in_text,
    parse_venue_paren_term,
    text_has_configured_brand_term,
)


def test_venue_paren_dual_key_matches_shorthand_same_line() -> None:
    """2026-09-03 - 配置长店名，正文「千里马（市妇婴店）」仍命中。"""
    term = "千里马泥炉烤肉店(市妇婴店）"
    assert parse_venue_paren_term(term) == ("千里马泥炉烤肉店", "市妇婴店")
    assert exact_configured_term_in_text("#### 2. 千里马（市妇婴店）｜总店", term)
    assert exact_configured_term_in_text("千里马泥炉烤肉(市妇婴店)", term)
    assert text_has_configured_brand_term(
        "游客认准原版总店 → 千里马（市妇婴店）",
        [term],
    )


def test_venue_paren_dual_key_does_not_match_other_branch() -> None:
    """南市场店行只有千里马、没有市妇婴 → 不中。"""
    term = "千里马泥炉烤肉店(市妇婴店）"
    assert not exact_configured_term_in_text(
        "#### 1. 千里马烧烤(南市场店)｜首选老店",
        term,
    )


def test_country_paren_not_treated_as_venue_dual_key() -> None:
    """爱格(奥地利) 不是门店括号，不走双钥放宽。"""
    assert parse_venue_paren_term("爱格(奥地利)") is None
    assert not exact_configured_term_in_text("爱格 EGGER 进口板", "爱格(奥地利)")


def test_plain_brand_still_exact_only() -> None:
    """无门店括号的普通露出词仍整段匹配，不做公司名切片。"""
    assert exact_configured_term_in_text("推荐艾迪亚控股集团", "艾迪亚")
    # 配置很长全称时，正文只有短词 → 不命中（也无门店双钥）
    assert not exact_configured_term_in_text(
        "推荐广东菜",
        "广东菜多多餐饮管理有限公司",
    )
