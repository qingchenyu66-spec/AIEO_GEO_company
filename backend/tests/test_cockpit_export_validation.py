"""驾驶舱 HTML 出厂校验：行业词不硬拦，旧客户壳仍拦。"""

from app.services.report_diagnosis_cockpit_service import validate_cockpit_html_export


def test_intent_mode_allows_industry_terms_in_content():
    html = (
        'const __COCKPIT__ = {"platformData":{"all":{"primary_kpi_available":true}}};\n'
        "高铁站场景投放与电梯媒介对比。nonbrand_rank_sum brand_rank_sum"
    )
    issues = validate_cockpit_html_export(html, brand="某户外媒介", filter_mode="intent")
    assert not any(i.startswith("industry_pollution:") for i in issues)


def test_shell_pollution_still_blocks_aidiya():
    html = "艾迪亚控股案例 nonbrand_rank_sum brand_rank_sum"
    issues = validate_cockpit_html_export(html, brand="不白吃有文化中心", filter_mode="intent")
    assert "shell_pollution:艾迪亚" in issues
