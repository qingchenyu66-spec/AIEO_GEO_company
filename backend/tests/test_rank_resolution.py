from types import SimpleNamespace

from app.services.monitor_service import (
    BrandRankResolution,
    _brand_appears_in_text,
    _name_matches_brand,
    _resolve_brand_rank_detail,
)
from app.services.rank_llm_service import (
    LlmBrandRankResult,
    apply_llm_rank_fallback,
    should_trigger_llm_fallback,
)


def test_name_matches_brand_rejects_city_prefix_of_alias() -> None:
    """「北京」「北」不得命中别名「北京艾迪亚」。"""
    terms = ["艾迪亚", "AIDIYA", "艾迪亚集团", "北京艾迪亚", "艾迪亚控股集团有限公司"]
    assert _name_matches_brand("北京", terms) is False
    assert _name_matches_brand("北", terms) is False
    assert _name_matches_brand("艾迪亚", terms) is True
    assert _name_matches_brand("艾迪亚传媒", terms) is True
    assert _name_matches_brand("北京艾迪亚控股", terms) is True


def test_brand_appears_in_text_rejects_city_only_line() -> None:
    terms = ["北京艾迪亚", "艾迪亚"]
    assert _brand_appears_in_text("北京：信时光传媒", terms) is False
    assert _brand_appears_in_text("推荐艾迪亚控股", terms) is True


def test_resolve_no_structured_rank_when_brand_absent_from_answer() -> None:
    """正文无品牌时，即使榜里脏匹配到地名，也不写 structured 名次。"""
    subtask = SimpleNamespace(
        prompt="电梯广告公司推荐",
        answer_content="## 区域优质服务商\n### 1. 北京\n- 信时光传媒",
        mention_context=None,
        all_rankings_json=[{"name": "北京", "rank": 1, "category": "区域优质服务商"}],
        mention_position=None,
        raw_result_json={},
    )
    terms = ["艾迪亚", "北京艾迪亚", "艾迪亚控股集团有限公司"]
    detail = _resolve_brand_rank_detail(subtask, "艾迪亚控股集团有限公司", terms, asset=None)
    assert detail.rank is None
    assert detail.mentioned is False


def test_resolve_appearance_beyond_top3_kept_under_scheme_x(monkeypatch) -> None:
    """方案 X：点名序第5也作为候选，不再丢成仅提及。"""
    monkeypatch.setattr(
        "app.services.monitor_service._find_brand_in_rankings",
        lambda *args, **kwargs: (None, False, None),
    )
    monkeypatch.setattr("app.services.monitor_service._appearance_order_rank", lambda *args, **kwargs: 5)
    monkeypatch.setattr("app.services.monitor_service._brand_appears_in_text", lambda *args, **kwargs: True)

    subtask = SimpleNamespace(
        prompt="LED广告公司推荐",
        answer_content="艾迪亚出现在长名单深处",
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "LED广告公司推荐", ["艾迪亚"], asset=None)
    assert detail.mentioned is True
    assert detail.rank == 5
    assert detail.source == "appearance"
    assert detail.rank_basis == "appearance_beyond_top3"


def test_resolve_appearance_top3_still_kept(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.monitor_service._find_brand_in_rankings",
        lambda *args, **kwargs: (None, False, None),
    )
    monkeypatch.setattr("app.services.monitor_service._appearance_order_rank", lambda *args, **kwargs: 2)
    monkeypatch.setattr("app.services.monitor_service._brand_appears_in_text", lambda *args, **kwargs: True)

    subtask = SimpleNamespace(
        prompt="LED广告公司推荐",
        answer_content="艾迪亚在前三",
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "LED广告公司推荐", ["艾迪亚"], asset=None)
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.source == "appearance"


def test_resolve_scheme_x_picks_frontmost_among_rules(monkeypatch) -> None:
    """结构化12 + 库内1 → 取最前1。"""
    monkeypatch.setattr(
        "app.services.monitor_service._find_brand_in_rankings",
        lambda *args, **kwargs: (12, True, "单元/同步试卷"),
    )
    monkeypatch.setattr("app.services.monitor_service._appearance_order_rank", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.monitor_service._brand_appears_in_text", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.services.monitor_service._matched_brand_category", lambda *a, **k: "单元/同步试卷")

    subtask = SimpleNamespace(
        prompt="初一同步辅导书推荐",
        answer_content="正文含万唯",
        mention_context=None,
        all_rankings_json=[{"name": "万唯大小卷", "rank": 12}],
        mention_position=1,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "万唯", ["万唯"], asset=None)
    assert detail.rank == 1
    assert detail.source == "api"


def test_resolve_scheme_x_structured_beats_worse_api(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.monitor_service._find_brand_in_rankings",
        lambda *args, **kwargs: (1, True, "单元/同步试卷"),
    )
    monkeypatch.setattr("app.services.monitor_service._appearance_order_rank", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.monitor_service._brand_appears_in_text", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.services.monitor_service._matched_brand_category", lambda *a, **k: "单元/同步试卷")

    subtask = SimpleNamespace(
        prompt="初一同步辅导书推荐",
        answer_content="正文含万唯",
        mention_context=None,
        all_rankings_json=[],
        mention_position=12,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "万唯", ["万唯"], asset=None)
    assert detail.rank == 1
    assert detail.source == "structured"


def test_resolve_manual_lock_not_overridden_by_frontmost(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.monitor_service._find_brand_in_rankings",
        lambda *args, **kwargs: (1, True, "段"),
    )
    subtask = SimpleNamespace(
        prompt="初一同步辅导书推荐",
        answer_content="万唯第一",
        mention_context=None,
        all_rankings_json=[],
        mention_position=8,
        raw_result_json={"source": "manual_snapshot", "manual_rank_locked": True},
    )
    detail = _resolve_brand_rank_detail(subtask, "万唯", ["万唯"], asset=None)
    assert detail.source == "manual"
    assert detail.rank == 8


def test_resolve_brand_rank_detail_prefers_persisted_llm() -> None:
    subtask = SimpleNamespace(
        prompt="LED广告公司推荐",
        answer_content="1. 竞品A\n2. 竞品B",
        mention_context=None,
        all_rankings_json=[],
        mention_position=4,
        raw_result_json={
            "rank_resolution": {
                "source": "llm",
                "rank": 4,
                "mentioned": True,
                "confidence": 0.91,
                "category": "区域优质工程商",
                "rank_basis": "section_bullet",
                "evidence": "西南：艾迪亚控股",
            }
        },
    )
    detail = _resolve_brand_rank_detail(subtask, "LED广告公司推荐", ["艾迪亚"], asset=None)
    assert detail.source == "llm"
    assert detail.rank == 4
    assert detail.category == "区域优质工程商"


def test_should_trigger_llm_fallback_for_null_rank_with_mention() -> None:
    resolution = BrandRankResolution(rank=None, mentioned=True, source="none", confidence=0.3)
    assert should_trigger_llm_fallback(resolution, is_industry_task=True) is True


def test_apply_llm_rank_fallback_replaces_appearance_rank() -> None:
    resolution = BrandRankResolution(rank=29, mentioned=True, source="appearance", confidence=0.55)
    llm = LlmBrandRankResult(
        rank=4,
        mentioned=True,
        category="区域优质工程商",
        rank_basis="section_bullet",
        confidence=0.9,
        evidence="西南：艾迪亚控股",
    )
    merged = apply_llm_rank_fallback(resolution, llm)
    assert merged.source == "llm"
    assert merged.rank == 4


def test_apply_llm_rank_fallback_keeps_high_confidence_structured_rank() -> None:
    resolution = BrandRankResolution(rank=2, mentioned=True, source="structured", confidence=0.95)
    llm = LlmBrandRankResult(
        rank=5,
        mentioned=True,
        category="其他",
        rank_basis="section_list",
        confidence=0.9,
        evidence="...",
    )
    merged = apply_llm_rank_fallback(resolution, llm)
    assert merged.source == "structured"
    assert merged.rank == 2
