"""recompute_subtask_rank_from_answer must not keep stale api/llm ranks."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import BrandRankResolution, recompute_subtask_rank_from_answer


def test_recompute_clears_stale_mention_before_auto_parse(monkeypatch) -> None:
    """2026-07-29 - 留空补录仍吃旧位次4 - 自动解析前清 mention_position / rank_resolution。"""
    subtask = SimpleNamespace(
        mention_position=4,
        raw_result_json={
            "source": "manual_snapshot",
            "manual_rank_locked": False,
            "rank_resolution": {"rank": 4, "source": "api", "mentioned": True, "confidence": 0.6},
        },
        answer_content="二、选型建议\n首选推荐\t备选\n大国品牌\t君智",
        all_rankings_json=[],
        prompt="打造头部品牌的服务商推荐",
    )
    task = SimpleNamespace(tenant_id=None, monitor_keywords="大国品牌", raw_request_json={})
    seen: dict = {}

    def fake_normalize(st) -> None:
        return None

    def fake_resolve(st, monitor_keywords, brand_terms, asset=None):
        seen["mp_during_resolve"] = st.mention_position
        seen["raw"] = dict(st.raw_result_json or {})
        return BrandRankResolution(rank=1, mentioned=True, source="llm", confidence=0.95)

    def fake_optional_llm(*, subtask, task, resolution, brand_terms, asset):
        return resolution

    def fake_persist(st, resolution) -> None:
        raw = dict(st.raw_result_json or {})
        raw["rank_resolution"] = {
            "rank": resolution.rank,
            "source": resolution.source,
            "mentioned": resolution.mentioned,
            "confidence": resolution.confidence,
        }
        st.raw_result_json = raw

    monkeypatch.setattr("app.services.monitor_service._normalize_subtask_rankings_on_write", fake_normalize)
    monkeypatch.setattr("app.services.monitor_service._resolve_brand_rank_detail", fake_resolve)
    monkeypatch.setattr("app.services.rank_llm_service.resolve_rank_with_optional_llm", fake_optional_llm)
    monkeypatch.setattr("app.services.rank_llm_service.persist_rank_resolution", fake_persist)

    recompute_subtask_rank_from_answer(MagicMock(), subtask, task, override_mention_position=None)

    assert seen["mp_during_resolve"] is None
    assert "rank_resolution" not in seen["raw"]
    assert seen["raw"].get("manual_rank_locked") is False
    assert subtask.mention_position == 1
    assert subtask.raw_result_json.get("rank_resolution", {}).get("rank") == 1


def test_preferred_column_table_rank_first_row() -> None:
    from app.services.monitor_service import _preferred_column_table_rank, _resolve_brand_rank_detail

    answer = (
        "二、按企业需求场景的选型建议\n"
        "企业发展阶段\t核心品牌目标\t首选推荐\t备选\n"
        "行业龙头/千亿级企业\t巩固领导地位\t大国品牌（国家级平台型）+ 奥美（国际4A）\t君智\n"
        "成长型头部企业（10-100亿）\t突破区域限制\t君智战略咨询\t华与华 / 松鼠跃动\n"
        "细分领域隐形冠军（B2B）\t从B端走向大众\t中网B2B战略咨询\t大国品牌\n"
    )
    assert _preferred_column_table_rank(answer, ["大国品牌"]) == 1

    subtask = SimpleNamespace(
        prompt="打造头部品牌的服务商推荐",
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "大国品牌（kimi）", ["大国品牌"], asset=None)
    assert detail.rank == 1
    assert detail.rank_basis == "preferred_column"
