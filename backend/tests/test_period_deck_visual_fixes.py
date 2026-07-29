"""周期幻灯：平台中文名 / 季年轴补齐 / Y 轴整数刻度自检。"""

from datetime import date

from app.services.report_period_comparison_service import (
    _trend_bucket_slots,
    platform_display_name,
    render_source_influence_html,
    render_trend_html,
)


def test_platform_display_name_mobile_codes() -> None:
    assert platform_display_name("yuanbao_mobile") == "元宝移动端"
    assert platform_display_name("qianwen_mobile") == "通义千问移动端"
    assert platform_display_name("doubao") == "豆包"


def test_quarterly_slots_pad_full_quarter() -> None:
    # Q3 MTD 仅到 7/29，轴仍应有 7/8/9 月
    slots = _trend_bucket_slots("quarterly", date(2026, 7, 1), date(2026, 7, 29))
    assert [s["label"] for s in slots] == ["7月", "8月", "9月"]


def test_annual_slots_pad_all_quarters() -> None:
    slots = _trend_bucket_slots("annual", date(2026, 1, 1), date(2026, 7, 29))
    assert [s["label"] for s in slots] == ["Q1", "Q2", "Q3", "Q4"]


def test_trend_y_axis_uses_integer_ticks() -> None:
    html = render_trend_html(
        {
            "title": "月趋势",
            "points": [
                {"label": "7月", "sub": "07-01~07-29", "completed": 10, "mention_rate": 29.6, "avg_rank": 2.3, "top3_rate": 20},
                {"label": "8月", "sub": "08-01~08-31", "completed": 0, "mention_rate": 0, "avg_rank": None, "top3_rate": 0},
                {"label": "9月", "sub": "09-01~09-30", "completed": 0, "mention_rate": 0, "avg_rank": None, "top3_rate": 0},
            ],
        },
        presentation=True,
    )
    assert "minInterval: 1" in html
    assert "Math.round(Number(v))" in html
    assert "Math.ceil(Math.max(...ranks))" in html


def test_source_chart_deck_full_width_class() -> None:
    html = render_source_influence_html(
        {
            "conclusion": "测试",
            "rows": [
                {"index": 1, "title": "2026年地铁广告投放指南", "count": 57, "value_analysis": "—"},
                {"index": 2, "title": "赋能品牌高空声量", "count": 36, "value_analysis": "—"},
            ],
        },
        presentation=True,
    )
    assert "source-grid-deck" in html
    assert "width: 680" in html
    assert "overflow: 'none'" in html
