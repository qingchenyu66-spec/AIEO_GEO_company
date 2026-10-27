"""含已下线词及平台：平台名单与热力归词。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.monitor_service import (
    _workspace_keyword_platform_light,
    canonicalize_platforms_to_display,
    split_retired_display_platforms,
)


def test_retired_platform_needs_samples_and_ignores_current_family() -> None:
    display, retired = split_retired_display_platforms(
        ["doubao", "deepseek"],
        ["kimi", "wenxinyiyan", "deepseek_mobile"],
        {"wenxinyiyan", "deepseek_mobile"},
    )
    assert display == ["doubao", "deepseek", "wenxinyiyan"]
    assert retired == ["wenxinyiyan"]


def test_inactive_platform_without_samples_is_not_shown() -> None:
    display, retired = split_retired_display_platforms(
        ["doubao"],
        ["kimi"],
        set(),
    )
    assert display == ["doubao"]
    assert retired == []


def test_observer_allow_drops_platforms_outside_whitelist() -> None:
    display, retired = split_retired_display_platforms(
        ["kimi"],
        ["doubao", "wenxinyiyan"],
        {"doubao", "wenxinyiyan", "kimi"},
        observer_allow=frozenset({"kimi"}),
    )
    assert display == ["kimi"]
    assert retired == []


def test_canonicalize_collapses_mobile_onto_display_code() -> None:
    assert canonicalize_platforms_to_display(
        ["deepseek_mobile", "wenxinyiyan", "unknown"],
        ["deepseek", "wenxinyiyan"],
    ) == ["deepseek", "wenxinyiyan"]


def test_heatmap_retired_rows_do_not_absorb_fuzzy_prompts() -> None:
    db = MagicMock()
    db.scalars.side_effect = [
        iter(["task-a"]),
        iter([
            SimpleNamespace(
                platform="doubao",
                prompt="儿童DHA品牌推荐",
                task=SimpleNamespace(monitor_keywords="儿童DHA品牌推荐"),
                status="completed",
            ),
            SimpleNamespace(
                platform="doubao",
                prompt="育鹏LED大屏广告公司哪家好",
                task=SimpleNamespace(monitor_keywords="育鹏LED大屏广告公司哪家好"),
                status="completed",
            ),
            SimpleNamespace(
                platform="doubao",
                prompt="育鹏LED大屏哪家好",
                task=SimpleNamespace(monitor_keywords="育鹏LED大屏哪家好"),
                status="completed",
            ),
            SimpleNamespace(
                platform="wenxinyiyan",
                prompt="机场广告哪家好",
                task=SimpleNamespace(monitor_keywords="机场广告哪家好"),
                status="completed",
            ),
        ]),
    ]
    active = {
        "monitor_keywords": ["儿童DHA品牌推荐", "育鹏LED大屏广告公司哪家好"],
        "monitor_keyword": "儿童DHA品牌推荐",
        "status": True,
    }
    inactive = {
        "monitor_keywords": ["机场广告哪家好"],
        "monitor_keyword": "机场广告哪家好",
        "status": False,
    }

    with (
        patch("app.services.monitor_service._ranking_matrix_orphan_task_ids", return_value=[]),
        patch("app.services.monitor_service.get_brand_asset", return_value=SimpleNamespace()),
        patch("app.services.monitor_service.active_keyword_groups", return_value=[active]),
        patch("app.services.monitor_service._ranking_match_terms", return_value=["宝得聪"]),
        patch("app.services.monitor_service.kpi_rank_for_subtask", return_value=1),
        patch("app.services.monitor_service.prompt_monitor_intent", return_value="ranking"),
        patch("app.services.monitor_service._platform_display_names", return_value={
            "doubao": "豆包",
            "wenxinyiyan": "文心",
        }),
    ):
        out = _workspace_keyword_platform_light(
            db,
            tenant_id=1,
            keyword_group_rows=[active, inactive],
            keyword_groups=[active],
            purchased_platforms=["doubao", "wenxinyiyan"],
            trend_start=datetime(2026, 8, 7),
            trend_end=datetime(2026, 8, 13),
            range_end=datetime(2026, 8, 13, 23, 59, 59),
            include_retired=True,
            retired_platforms=["wenxinyiyan"],
        )

    hm = out["keyword_platform_heatmap"]
    assert hm["keywords"] == [
        "儿童DHA品牌推荐",
        "育鹏LED大屏广告公司哪家好",
        "育鹏LED大屏哪家好（已下线）",
        "机场广告哪家好（已下线）",
    ]
    assert hm["platform_labels"][1].endswith("（已下线）")
    assert hm["retired_keywords"] == ["育鹏LED大屏哪家好", "机场广告哪家好"]
    by_keyword = {}
    for x_index, y_index, score in hm["data"]:
        if score >= 0:
            by_keyword.setdefault(hm["keywords"][y_index], set()).add(hm["platforms"][x_index])
    assert by_keyword["儿童DHA品牌推荐"] == {"doubao"}
    assert by_keyword["育鹏LED大屏哪家好（已下线）"] == {"doubao"}
    assert by_keyword["机场广告哪家好（已下线）"] == {"wenxinyiyan"}
