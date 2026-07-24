"""展示位次读路径：mention_position 权威，矩阵不读 answer_content。"""
from types import SimpleNamespace

from app.services.monitor_service import (
    _read_display_brand_rank,
    _resolve_brand_rank_detail_matrix_light,
)


def _subtask(**kwargs):
    defaults = {
        "prompt": "电梯广告品牌推荐",
        "mention_position": None,
        "mention_context": None,
        "all_rankings_json": [],
        "answer_content": "不应被读取",
        "raw_result_json": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_display_rank_prefers_mention_position_over_structured():
    item = _subtask(
        all_rankings_json=[{"name": "艾迪亚控股集团", "rank": 2}],
        mention_position=9,
        raw_result_json={"source": "manual_snapshot"},
    )
    detail = _read_display_brand_rank(
        item,
        "电梯广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
        allow_full_parse=False,
    )
    assert detail.rank == 9
    assert detail.mentioned is True
    assert detail.source == "manual"


def test_kpi_rank_prefers_normalized_structured_over_dirty_auto_mention():
    from app.services.monitor_service import kpi_rank_for_subtask

    # 模力脏榜：全员 rank=1；规范化后按出场序重编号，品牌应在第 4
    item = _subtask(
        all_rankings_json=[
            {"name": "甲", "rank": 1},
            {"name": "乙", "rank": 1},
            {"name": "丙", "rank": 1},
            {"name": "艾迪亚控股集团有限公司", "rank": 1},
        ],
        mention_position=1,
        raw_result_json={},
    )
    rank = kpi_rank_for_subtask(
        item,
        "电梯广告",
        ["艾迪亚", "艾迪亚控股集团", "艾迪亚控股集团有限公司"],
        None,
    )
    assert rank == 4.0


def test_light_path_trusts_non_suspicious_mention_without_reconcile():
    """位次≠1 且榜单未扎堆时，轻量路径不强制结构化对账。"""
    item = _subtask(
        all_rankings_json=[
            {"name": "甲", "rank": 1},
            {"name": "艾迪亚控股集团", "rank": 2},
            {"name": "丙", "rank": 3},
        ],
        mention_position=2,
        raw_result_json={},
    )
    detail = _read_display_brand_rank(
        item,
        "电梯广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
        allow_full_parse=False,
    )
    assert detail.rank == 2
    assert detail.source == "stored"


def test_normalize_cache_reuses_same_rankings_payload():
    from app.services.monitor_service import _normalize_structured_rankings_cached

    raw = [
        {"name": "甲", "rank": 1},
        {"name": "乙", "rank": 1},
        {"name": "艾迪亚", "rank": 1},
    ]
    cache: dict = {}
    first = _normalize_structured_rankings_cached(raw, cache)
    second = _normalize_structured_rankings_cached(
        [
            {"name": "甲", "rank": 1},
            {"name": "乙", "rank": 1},
            {"name": "艾迪亚", "rank": 1},
        ],
        cache,
    )
    assert first is second
    assert len(cache) == 1
    assert [row["rank"] for row in first] == [1, 2, 3]


def test_display_rank_falls_back_to_structured_when_mention_missing():
    item = _subtask(
        all_rankings_json=[{"name": "艾迪亚控股集团", "rank": 2}],
        mention_position=None,
    )
    detail = _resolve_brand_rank_detail_matrix_light(
        item,
        "电梯广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 2.0
    assert detail.source == "structured"


def test_matrix_light_does_not_need_answer_content():
    item = SimpleNamespace(
        prompt="电梯广告品牌推荐",
        mention_position=1,
        mention_context="提及艾迪亚",
        all_rankings_json=[],
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail_matrix_light(item, None, ["艾迪亚"], None)
    assert detail.rank == 1
    assert detail.mentioned is True
    assert detail.source == "stored"
