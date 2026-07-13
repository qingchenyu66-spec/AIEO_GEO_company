from __future__ import annotations

import pytest

from app.services.report_competitor_visuals import (
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
