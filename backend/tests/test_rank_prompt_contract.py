"""排名 LLM prompt 契约：瘦身时不得删掉硬约束片段。"""

from __future__ import annotations

from app.services.deepseek_client import RANK_PROMPT_CONTRACT_MARKERS, _build_brand_rank_prompts


def test_brand_rank_prompt_contract_markers_present() -> None:
    system, user = _build_brand_rank_prompts(
        monitor_keyword="测试词",
        prompt="推荐品牌",
        aliases="测试品牌",
        answer_text="## 一档\n1. A\n2. B",
        truncate_note="",
    )
    combined = system + user
    missing = [m for m in RANK_PROMPT_CONTRACT_MARKERS if m not in combined]
    assert not missing, f"prompt 缺少硬约束片段: {missing}"


def test_brand_rank_user_prompt_no_duplicate_teaching() -> None:
    """user 不再重复 system 里的进口/地铁长案例。"""
    _, user = _build_brand_rank_prompts(
        monitor_keyword="x",
        prompt="y",
        aliases="z",
        answer_text="正文",
        truncate_note="",
    )
    assert "地铁/公交例" not in user
    assert "禁止混入进口档或 rank=6" not in user
    assert "按 system 规则 A→B→C" in user


def test_brand_rank_prompt_slimmer_than_legacy_shape() -> None:
    """固定模板应明显短于旧版（user 去重复案例）。"""
    system, user = _build_brand_rank_prompts(
        monitor_keyword="词",
        prompt="问",
        aliases="品牌",
        answer_text="",
        truncate_note="",
    )
    # 旧版 user 固定尾巴约 450+ 字；新版应明显更短
    assert len(user) < 350
    # 旧版 system 约 1350+ 字；合并后应 < 1100
    assert len(system) < 1100
    assert len(system) + len(user) < 1400
