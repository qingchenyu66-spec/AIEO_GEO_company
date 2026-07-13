from types import SimpleNamespace

from app.services.monitor_service import (
    _filter_matrix_columns_for_scope,
    _filter_subtasks_by_exposure_term,
    _keyword_groups_for_exposure_term,
    _resolve_brand_rank,
)


def test_filter_matrix_columns_for_scope_keeps_only_prompt_set() -> None:
    columns = [
        {"prompt": "LED广告公司推荐", "monitor_keyword": "LED广告公司推荐"},
        {"prompt": "地铁广告公司推荐", "monitor_keyword": "地铁广告公司推荐"},
    ]
    prompt_set = {"LED广告公司推荐": "词组A"}
    filtered = _filter_matrix_columns_for_scope(
        columns,
        prompt_set,
        keyword_group=None,
        monitor_keyword="LED广告公司推荐",
        exposure_term=None,
    )
    assert len(filtered) == 1
    assert filtered[0]["monitor_keyword"] == "LED广告公司推荐"


def test_filter_matrix_columns_for_scope_no_filter_keeps_all() -> None:
    columns = [{"prompt": "a"}, {"prompt": "b"}]
    assert _filter_matrix_columns_for_scope(columns, {"a": None}, keyword_group=None, monitor_keyword=None, exposure_term=None) == columns


def test_exposure_term_filter_matches_keyword_group_not_prompt_substring() -> None:
    from types import SimpleNamespace

    groups = [
        {
            "status": True,
            "monitor_keyword": "地铁广告公司推荐",
            "monitor_keywords": ["地铁广告公司推荐"],
            "exposure_terms": ["艾迪亚"],
        },
        {
            "status": True,
            "monitor_keyword": "LED广告公司推荐",
            "monitor_keywords": ["LED广告公司推荐"],
            "exposure_terms": ["另一品牌"],
        },
    ]
    matched = _keyword_groups_for_exposure_term("艾迪亚", groups)
    assert len(matched) == 1
    subtasks = [
        SimpleNamespace(prompt="地铁广告公司推荐"),
        SimpleNamespace(prompt="LED广告公司推荐"),
    ]
    filtered = _filter_subtasks_by_exposure_term(subtasks, "艾迪亚", groups)
    assert len(filtered) == 1
    assert filtered[0].prompt == "地铁广告公司推荐"


def test_resolve_brand_rank_trusts_manual_snapshot_rank() -> None:
    subtask = SimpleNamespace(
        prompt="地铁广告公司推荐",
        answer_content="1. 某竞品\n2. 另一竞品",
        mention_context=None,
        all_rankings_json=[{"name": "某竞品", "rank": 1}],
        mention_position=1,
        raw_result_json={"source": "manual_snapshot"},
    )
    rank, mentioned = _resolve_brand_rank(subtask, "综合", ["艾迪亚"], asset=None)
    assert rank == 1
    assert mentioned is True


def test_resolve_brand_rank_ignores_industry_list_without_brand() -> None:
    text = """
### 主要地铁广告运营商

1. 分众传媒
- 中国最大的楼宇媒体和户外视频广告运营商之一

2. 华视传媒
- 专注于地铁、公交移动电视广告

3. 雅仕维
4. 德高中国
5. 百灵时代
6. 各城市地铁集团自有广告公司
"""
    subtask = SimpleNamespace(
        prompt="地铁广告公司哪家好",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=2,
        raw_result_json={},
    )
    brand_terms = ["艾迪亚控股集团有限公司", "艾迪亚", "艾迪亚集团"]

    rank, mentioned = _resolve_brand_rank(subtask, "电梯广告", brand_terms, asset=None)
    assert rank is None
    assert mentioned is False
