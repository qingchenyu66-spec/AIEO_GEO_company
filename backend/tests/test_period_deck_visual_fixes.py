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
    long_title = "2026年地铁广告投放指南：五大优质地铁广告公司推荐与投放策略完整解读"
    html = render_source_influence_html(
        {
            "conclusion": "测试",
            "rows": [
                {"index": 1, "title": long_title, "count": 57, "value_analysis": "—"},
                {"index": 2, "title": "赋能品牌高空声量", "count": 36, "value_analysis": "—"},
            ],
        },
        presentation=True,
    )
    assert "source-deck-list" in html
    assert "source-deck-item" in html
    assert "source-deck-analysis" in html
    assert long_title in html
    assert "sourceBarChart" not in html
    assert "source-conclusion" in html
    assert "source-table-box" not in html


def test_trim_rank_trend_empty_edges() -> None:
    from app.services.report_period_comparison_service import _trim_rank_trend_empty_edges

    trimmed = _trim_rank_trend_empty_edges(
        {
            "categories": ["第1周", "第2周", "第3周", "第4周", "第5周"],
            "fullCategories": ["1", "2", "3", "4", "5"],
            "series": [
                {"name": "品牌", "data": [None, None, None, 2.1, 2.3]},
                {"name": "竞品", "data": [None, None, None, 3.0, 2.8]},
            ],
        }
    )
    assert trimmed["categories"] == ["第4周", "第5周"]
    assert trimmed["series"][0]["data"] == [2.1, 2.3]


def test_competitor_trend_presentation_fonts() -> None:
    from app.services.report_period_comparison_service import render_competitor_html

    metric = {"current": 2.1, "previous": 2.2, "direction": "up", "text": "↑"}
    html = render_competitor_html(
        {
            "rows": [
                {
                    "name": "品牌",
                    "is_brand": True,
                    "mention_rate": metric,
                    "avg_rank": metric,
                    "style": {"color": "#1677ff"},
                    "risk": {"level": "good", "label": "达标"},
                    "gap_mention_text": "—",
                    "gap_rank_text": "—",
                }
            ],
            "highlights": [],
            "analysis": {"management_summary": "x", "actions": []},
            "rank_trend": {
                "categories": ["第4周", "第5周"],
                "fullCategories": ["4", "5"],
                "series": [
                    {
                        "name": "品牌",
                        "is_brand": True,
                        "data": [2.1, 2.3],
                        "style": {"symbol": "circle", "line_type": "solid", "color": "#1677ff"},
                    }
                ],
            },
        },
        report_type="monthly",
        presentation=True,
    )
    assert "fontSize: 34" in html
    assert "fontSize: 30" in html
