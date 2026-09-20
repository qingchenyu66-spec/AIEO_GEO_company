"""规则为空或位次大于公司数时才用模型. 正常位次不调模型."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import (
    BrandRankResolution,
    _enumerated_company_count,
    _rule_rank_unusable,
    recompute_subtask_rank_from_answer,
)
from app.services.rank_llm_service import LlmBrandRankResult, _evidence_in_answer


def _subtask(answer: str, prompt: str = "哪家靠谱") -> SimpleNamespace:
    return SimpleNamespace(
        mention_position=None,
        mention_context=None,
        raw_result_json={},
        answer_content=answer,
        all_rankings_json=[],
        prompt=prompt,
        platform="deepseek",
        status="completed",
        mode=None,
        subtask_id="t",
        task_id=None,
    )


def _task() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=None, monitor_keywords="鸿联九五", raw_request_json={})


def _patch_rules(monkeypatch, resolution: BrandRankResolution) -> None:
    monkeypatch.setattr(
        "app.services.monitor_service._normalize_subtask_rankings_on_write",
        lambda _st: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_service._resolve_brand_rank_detail",
        lambda *_a, **_k: resolution,
    )
    monkeypatch.setattr(
        "app.services.monitor_service._brand_in_answer_for_rank",
        lambda *_a, **_k: True,
    )


def test_company_count_blocks_rank_over_list() -> None:
    answer = "1. 泰盈科技\n2. 京北方\n3. 华道数据\n"
    assert _enumerated_company_count(answer) == 3
    assert _rule_rank_unusable(99, 3) is True
    assert _rule_rank_unusable(3, 3) is False
    assert _rule_rank_unusable(21, 30) is True
    assert _rule_rank_unusable(10, 0) is False


def test_evidence_must_occur_in_answer() -> None:
    answer = "京北方在银行项目中标, 鸿联九五是本土第一家。"
    assert _evidence_in_answer("京北方在银行项目中标", answer) is True
    assert _evidence_in_answer("**京北方** 在银行项目中标", answer) is True
    assert _evidence_in_answer("根本没写过这句话呀", answer) is False
    assert _evidence_in_answer("京北", answer) is False


def test_sane_rule_rank_does_not_call_llm(monkeypatch) -> None:
    calls = {"n": 0}

    def fail_llm(**_kwargs):
        calls["n"] += 1
        raise AssertionError("llm")

    _patch_rules(
        monkeypatch,
        BrandRankResolution(rank=2, mentioned=True, source="section_local", confidence=0.8),
    )
    monkeypatch.setattr("app.services.rank_llm_service.accept_llm_fallback", fail_llm)
    subtask = _subtask("1. 泰盈科技\n2. 鸿联九五\n")
    recompute_subtask_rank_from_answer(MagicMock(), subtask, _task(), force=True)
    assert calls["n"] == 0
    assert subtask.mention_position == 2


def test_rule_rank_over_company_count_uses_llm_when_evidence_matches(monkeypatch) -> None:
    _patch_rules(
        monkeypatch,
        BrandRankResolution(
            rank=99,
            mentioned=True,
            source="appearance",
            confidence=0.7,
            rank_basis="numbered_subheading",
        ),
    )

    def fake_llm(**_kwargs):
        return LlmBrandRankResult(
            rank=2,
            mentioned=True,
            category="本土",
            rank_basis="category_local",
            confidence=0.8,
            evidence="鸿联九五是第一家",
        )

    monkeypatch.setattr("app.services.rank_llm_service.extract_brand_rank_with_llm", fake_llm)
    subtask = _subtask("1. 泰盈科技\n2. 京北方\n3. 华道数据\n鸿联九五是第一家。")
    recompute_subtask_rank_from_answer(MagicMock(), subtask, _task(), force=True)
    saved = subtask.raw_result_json["rank_resolution"]
    assert subtask.mention_position == 2
    assert saved["source"] == "llm"
    assert saved["rules_rank"] == 99
    assert saved["llm_rank"] == 2


def test_bad_llm_evidence_drops_absurd_rule_rank(monkeypatch) -> None:
    _patch_rules(
        monkeypatch,
        BrandRankResolution(rank=99, mentioned=True, source="appearance", confidence=0.7),
    )

    def fake_llm(**_kwargs):
        return LlmBrandRankResult(
            rank=1,
            mentioned=True,
            category=None,
            rank_basis="category_local",
            confidence=0.9,
            evidence="这句话正文里没有",
        )

    monkeypatch.setattr("app.services.rank_llm_service.extract_brand_rank_with_llm", fake_llm)
    subtask = _subtask("1. 泰盈科技\n2. 京北方\n3. 华道数据\n")
    recompute_subtask_rank_from_answer(MagicMock(), subtask, _task(), force=True)
    saved = subtask.raw_result_json["rank_resolution"]
    assert subtask.mention_position is None
    assert saved["rules_rank"] == 99
    assert saved.get("source") != "llm"


def test_empty_rules_use_llm(monkeypatch) -> None:
    _patch_rules(
        monkeypatch,
        BrandRankResolution(rank=None, mentioned=True, source="none", confidence=0.4),
    )

    def fake_llm(**_kwargs):
        return LlmBrandRankResult(
            rank=1,
            mentioned=True,
            category=None,
            rank_basis="category_local",
            confidence=0.8,
            evidence="鸿联九五写在推荐里",
        )

    monkeypatch.setattr("app.services.rank_llm_service.extract_brand_rank_with_llm", fake_llm)
    subtask = _subtask("鸿联九五写在推荐里, 但没有编号。")
    recompute_subtask_rank_from_answer(MagicMock(), subtask, _task(), force=True)
    assert subtask.mention_position == 1
    assert subtask.raw_result_json["rank_resolution"]["source"] == "llm"


def test_negative_skip_does_not_call_llm(monkeypatch) -> None:
    def fail_llm(**_kwargs):
        raise AssertionError("negative mention must not call llm")

    _patch_rules(
        monkeypatch,
        BrandRankResolution(
            rank=None,
            mentioned=True,
            source="exposure",
            confidence=0.9,
            rank_basis="negative_context_skip",
        ),
    )
    monkeypatch.setattr("app.services.rank_llm_service.accept_llm_fallback", fail_llm)
    subtask = _subtask("假货才是鸿联九五。")
    recompute_subtask_rank_from_answer(MagicMock(), subtask, _task(), force=True)
    assert subtask.mention_position is None


def test_llm_over_cap_is_not_written(monkeypatch) -> None:
    _patch_rules(
        monkeypatch,
        BrandRankResolution(rank=99, mentioned=True, source="appearance", confidence=0.7),
    )

    def fake_llm(**_kwargs):
        return LlmBrandRankResult(
            rank=30,
            mentioned=True,
            category=None,
            rank_basis="category_local",
            confidence=0.9,
            evidence="鸿联九五是第一家",
        )

    monkeypatch.setattr("app.services.rank_llm_service.extract_brand_rank_with_llm", fake_llm)
    subtask = _subtask("1. 泰盈科技\n2. 京北方\n鸿联九五是第一家。")
    recompute_subtask_rank_from_answer(MagicMock(), subtask, _task(), force=True)
    assert subtask.mention_position is None
