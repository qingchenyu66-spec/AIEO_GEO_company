"""P2 platform family + citation filter helpers."""

from app.core.platform_order import expand_platform_codes, platform_code_family, platforms_compatible
from app.services.monitor_service import _is_valid_citation_source, matrix_platform_visible
from app.services.lead_diagnosis_analytics import names_match


def test_platform_family_pairs_deepseek() -> None:
    assert platform_code_family("deepseek") == {"deepseek", "deepseek_mobile"}
    assert platform_code_family("deepseek_mobile") == {"deepseek", "deepseek_mobile"}
    assert platforms_compatible("deepseek", "deepseek_mobile")
    assert "deepseek_mobile" in expand_platform_codes(["deepseek"])


def test_matrix_visible_includes_mobile_sibling() -> None:
    assert matrix_platform_visible("deepseek_mobile", ["deepseek"]) is True
    assert matrix_platform_visible("wenxinyiyan", ["deepseek"]) is False


def test_citation_filters_css_cdn() -> None:
    assert _is_valid_citation_source({"title": "ok", "url": "https://example.com/a"}) is True
    assert _is_valid_citation_source({"title": "x", "url": "https://cdn.example.com/a.css"}) is False
    assert _is_valid_citation_source({"title": "x", "url": "https://lf3-static.bytedance.net/x"}) is False


def test_names_match_requires_shared_prefix_stem() -> None:
    assert names_match("艾迪亚传媒", "艾迪亚控股集团")
    assert not names_match("华视传媒", "华铁传媒")
    # 中缀撞词干不应再命中（旧逻辑 stem in a and stem in b）
    assert not names_match("西南艾迪亚控股", "东北艾迪亚传媒")
