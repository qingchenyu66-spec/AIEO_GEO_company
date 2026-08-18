# -*- coding: utf-8 -*-
"""B3+ entity daily KPI resolve rules."""

from types import SimpleNamespace

from app.services.entity_daily_kpi import MENTION_WITHOUT_RANK, resolve_entity_rank_for_kpi


def test_non_ranking_prompt_counts_for_nobody() -> None:
    sub = SimpleNamespace(
        prompt="这家公司口碑评价怎么样",
        mention_position=1,
        answer_content="天然博士很好",
        mention_context="",
        all_rankings_json=[{"name": "竞品A", "rank": 1}],
    )
    assert resolve_entity_rank_for_kpi(sub, ["品牌"], None, is_brand=True) is None
    assert resolve_entity_rank_for_kpi(sub, ["天然博士"], None, is_brand=False) is None


def test_competitor_answer_mention_without_rank() -> None:
    sub = SimpleNamespace(
        prompt="推荐哪家品牌",
        mention_position=1,
        answer_content="可以看看天然博士和健敏思",
        mention_context="",
        all_rankings_json=[],
    )
    assert (
        resolve_entity_rank_for_kpi(sub, ["天然博士"], None, is_brand=False)
        == MENTION_WITHOUT_RANK
    )


def test_competitor_explicit_rank_preferred() -> None:
    sub = SimpleNamespace(
        prompt="推荐哪家品牌",
        mention_position=1,
        answer_content="天然博士不错",
        mention_context="",
        all_rankings_json=[{"name": "天然博士", "rank": 3}],
    )
    assert resolve_entity_rank_for_kpi(sub, ["天然博士"], None, is_brand=False) == 3.0
