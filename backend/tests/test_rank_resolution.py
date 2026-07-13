from types import SimpleNamespace

from app.services.monitor_service import (
    BrandRankResolution,
    _resolve_brand_rank_detail,
)
from app.services.rank_llm_service import (
    LlmBrandRankResult,
    apply_llm_rank_fallback,
    should_trigger_llm_fallback,
)


def test_resolve_brand_rank_detail_structured_source() -> None:
    subtask = SimpleNamespace(
        prompt="公交广告公司哪家好",
        answer_content="""
一、沧州本地推荐
1. 沧州市都市传媒公交广告有限公司
2. 艾迪亚控股集团
""",
        mention_context=None,
        all_rankings_json=[
            {"name": "沧州市都市传媒公交广告有限公司", "rank": 1, "category": "沧州本地推荐"},
            {"name": "艾迪亚控股集团", "rank": 2, "category": "沧州本地推荐"},
        ],
        mention_position=3,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "公交广告公司哪家好", ["艾迪亚"], asset=None)
    assert detail.source == "structured"
    assert detail.rank == 2
    assert detail.mentioned is True


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
