"""展示位次读路径：mention_position 权威，矩阵不读 answer_content。"""
from types import SimpleNamespace
from unittest.mock import patch

from app.services.monitor_service import (
    _read_display_brand_rank,
    _resolve_brand_rank_detail_matrix_light,
    _structured_reconcile_override_ok,
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
        answer_content="推荐顺序：甲、乙、丙、艾迪亚控股集团有限公司。",
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
        answer_content="榜单里有艾迪亚控股集团。",
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


def test_matrix_unloaded_raw_skips_reconcile_trusts_mention():
    """A′：矩阵未 load raw_result_json 时不对账，避免补录第1被文末产品改成22。"""
    item = _subtask(
        answer_content="首选推荐万唯教辅。",
        all_rankings_json=[
            {"name": "甲", "rank": 1},
            {"name": "乙", "rank": 2},
            {"name": "万唯《小四门速记手册》", "rank": 22},
        ],
        mention_position=1,
        raw_result_json={"source": "manual_snapshot"},
    )

    def _loaded(obj, key):
        if key == "raw_result_json":
            return False
        return True

    with patch("app.services.monitor_service._orm_attr_loaded", side_effect=_loaded):
        detail = _read_display_brand_rank(
            item,
            "教辅",
            ["万唯"],
            None,
            allow_full_parse=False,
        )
    assert detail.rank == 1
    assert detail.source == "stored"


def test_structured_reconcile_rejects_late_product_jump():
    """B：库内前列被对账拉到文末衍生品时拒覆盖。"""
    assert _structured_reconcile_override_ok(1, 22) is False
    assert _structured_reconcile_override_ok(1, 4) is True
    assert _structured_reconcile_override_ok(2, 7) is False  # |Δ|>=5


def test_reconcile_guard_keeps_mention_when_list_rank_jumps():
    item = _subtask(
        answer_content="首选推荐万唯。",
        all_rankings_json=[
            {"name": "甲", "rank": 1},
            {"name": "乙", "rank": 2},
            {"name": "万唯《大小卷》", "rank": 27},
        ],
        mention_position=1,
        raw_result_json={},  # loaded but not manual → would reconcile without guard
    )
    detail = _read_display_brand_rank(
        item,
        "教辅",
        ["万唯"],
        None,
        allow_full_parse=False,
    )
    assert detail.rank == 1
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
        answer_content="本段推荐艾迪亚控股集团。",
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


def test_detail_full_parse_does_not_override_stored_mention():
    """2026-08-12 - 有库内位次时详情不得全文重算成别的数，否则展开会 7→2。"""
    item = _subtask(
        prompt="初一同步辅导书推荐",
        answer_content="""
## 四、分学科专项补充
### 小四门（道法、历史、地理、生物）
1. 日常同步：教材帮即可。
2. 背诵：**《万唯小四门》**，考点速记。
""",
        all_rankings_json=[],
        mention_position=7,
        raw_result_json={"rank_resolution": {"source": "appearance", "rank": 7}},
    )
    detail = _read_display_brand_rank(
        item,
        "万唯",
        ["万唯", "万唯小四门"],
        None,
        allow_full_parse=True,
    )
    assert detail.rank == 7
    assert detail.source == "stored"
