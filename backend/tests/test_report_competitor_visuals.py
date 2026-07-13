from __future__ import annotations

import pytest

from app.services.report_competitor_visuals import (
    build_competitor_analysis,
    classify_rank_risk,
    entity_visual_style,
)


def test_known_entities_have_fixed_distinct_styles() -> None:
    names = (
        "艾迪亚控股集团有限公司",
        "分众传媒",
        "白马户外媒体",
        "华铁传媒",
    )

    styles = [
        entity_visual_style(name, brand_name="艾迪亚控股集团有限公司")
        for name in names
    ]

    assert [item.color for item in styles] == [
        "#0057D9",
        "#F28E2B",
        "#009E73",
        "#C43C92",
    ]
    assert len({(item.line_style, item.marker) for item in styles}) == 4


def test_unknown_entity_style_is_deterministic() -> None:
    assert entity_visual_style("未知竞品A") == entity_visual_style("未知竞品A")
    assert entity_visual_style("未知竞品A") != entity_visual_style("未知竞品B")


@pytest.mark.parametrize(
    ("rank", "level"),
    [
        (1, "good"),
        (3, "good"),
        (3.1, "watch"),
        (5, "watch"),
        (6, "warning"),
        (7, "warning"),
        (8, "danger"),
        (None, "neutral"),
        ("", "neutral"),
        ("bad", "neutral"),
    ],
)
def test_rank_risk_boundaries(rank: object, level: str) -> None:
    assert classify_rank_risk(rank).level == level


def test_competitor_analysis_balances_management_and_operations() -> None:
    analysis = build_competitor_analysis(
        brand_name="艾迪亚控股集团有限公司",
        rows=[
            {"name": "艾迪亚控股集团有限公司", "avg_rank": 4.2, "mention_rate": 8.8, "is_brand": True},
            {"name": "分众传媒", "avg_rank": 1.4, "mention_rate": 93.8},
            {"name": "白马户外媒体", "avg_rank": 5.1, "mention_rate": 2.5},
        ],
        platform_stats=[
            {"name": "DeepSeek", "mention_rate": 6.2, "avg_rank": 5.1},
            {"name": "微博智搜", "mention_rate": 82.5, "avg_rank": 3.2},
        ],
        prompt_analytics=[
            {"prompt": "电梯广告公司哪家好", "brand_mention_rate": 8.8, "brand_avg_rank": 5.5},
        ],
    )

    assert analysis["brand_position"]["risk"]["level"] == "watch"
    assert analysis["head_competitor"]["name"] == "分众传媒"
    assert analysis["nearest_competitor"]["name"] == "白马户外媒体"
    assert analysis["chase_target"]["name"] == "分众传媒"
    assert analysis["defend_target"]["name"] == "白马户外媒体"
    assert analysis["gap_to_head"] == 2.8
    assert any("DeepSeek" in action for action in analysis["actions"])
    assert any("电梯广告公司哪家好" in action for action in analysis["actions"])


def test_competitor_analysis_does_not_invent_missing_dimensions() -> None:
    analysis = build_competitor_analysis(
        brand_name="品牌A",
        rows=[{"name": "品牌A", "avg_rank": None, "mention_rate": 0, "is_brand": True}],
    )

    assert analysis["head_competitor"] is None
    assert analysis["nearest_competitor"] is None
    assert any("需结合平台明细确认" in action for action in analysis["actions"])
