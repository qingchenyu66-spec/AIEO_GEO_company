"""词×平台 light 热力与综合露出同用 kpi_rank。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.monitor_service import _workspace_keyword_platform_light


def test_light_heatmap_counts_kpi_rank_not_raw_mention_position():
    """2026-08-14 - 方案 A：裸 mention_position=3 但 kpi_rank=None 不得抬高格子。"""
    db = MagicMock()
    # schedule task ids
    db.scalars.side_effect = [
        iter(["task-a"]),  # schedule runs
        iter(  # subtasks
            [
                SimpleNamespace(
                    platform="doubao",
                    prompt="儿童DHA品牌推荐",
                    mention_position=3,
                    task=SimpleNamespace(monitor_keywords="儿童DHA品牌推荐"),
                    status="completed",
                    task_id="task-a",
                ),
                SimpleNamespace(
                    platform="doubao",
                    prompt="儿童DHA品牌推荐",
                    mention_position=1,
                    task=SimpleNamespace(monitor_keywords="儿童DHA品牌推荐"),
                    status="completed",
                    task_id="task-a",
                ),
            ]
        ),
    ]

    group = {
        "monitor_keywords": ["儿童DHA品牌推荐"],
        "monitor_keyword": "儿童DHA品牌推荐",
        "name": "g1",
    }

    with (
        patch(
            "app.services.monitor_service._ranking_matrix_orphan_task_ids",
            return_value=[],
        ),
        patch("app.services.monitor_service.get_brand_asset", return_value=SimpleNamespace()),
        patch("app.services.monitor_service.active_keyword_groups", return_value=[group]),
        patch("app.services.monitor_service._ranking_match_terms", return_value=["宝得聪"]),
        patch(
            "app.services.monitor_service.kpi_rank_for_subtask",
            side_effect=[None, 1],
        ),
        patch(
            "app.services.monitor_service._workspace_match_monitor_keyword",
            return_value="儿童DHA品牌推荐",
        ),
        patch(
            "app.services.monitor_service.prompt_monitor_intent",
            return_value="ranking",
        ),
    ):
        out = _workspace_keyword_platform_light(
            db,
            tenant_id=124,
            keyword_group_rows=[group],
            keyword_groups=[group],
            purchased_platforms=["doubao"],
            trend_start=datetime(2026, 8, 7),
            trend_end=datetime(2026, 8, 13),
            range_end=datetime(2026, 8, 13, 23, 59, 59),
        )

    hm = out["keyword_platform_heatmap"]
    # 2 条样本，仅 1 条 kpi_rank 有效 → 50.0；若误用 mention_position 会是 100
    assert hm["data"] == [[0, 0, 50.0]]
