"""LLM 排名固定回归集：改 prompt 前先跑，通过才上线。

2026-08-24 - 口径冻结：不测正文正则二次计位，只测输入清理 + LLM JSON 解析契约。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.rank_llm_service import parse_llm_rank_payload, strip_pre_answer_noise_for_rank

_FIXTURE = Path(__file__).parent / "fixtures" / "rank_llm_regression_cases.json"


@pytest.fixture(name="regression_cases")
def _load_regression_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", json.loads(_FIXTURE.read_text(encoding="utf-8")), ids=lambda c: c["id"])
def test_rank_llm_regression_payload_contract(case: dict) -> None:
    """期望 LLM 应返回的 JSON 形态；parse 层自检必须通过。"""
    payload = dict(case["llm_payload"])
    result = parse_llm_rank_payload(payload, brand_terms=case["brand_terms"])
    assert result.rank == case["expect_rank"]
    if case.get("expect_rank_basis"):
        assert result.rank_basis == case["expect_rank_basis"]
    if case.get("expect_category_contains"):
        assert case["expect_category_contains"] in str(result.category or "")


def test_strip_yuanbao_inline_heading_for_llm_input() -> None:
    """送 LLM 前：粘行 ## 须拆行，不算排名规则。"""
    raw = """
## 一、一线枢纽
- **航美传媒**
适合快消 [citation:1]## 三、整合代理 / 性价比型
-**艾迪亚控股** 等
"""
    cleaned = strip_pre_answer_noise_for_rank(raw)
    assert cleaned.index("## 三、整合代理") > cleaned.index("航美")


def test_strip_thought_before_formal_table() -> None:
    """送 LLM 前：DeepSeek 思考区不得进正文。"""
    raw = """
Thought for 7 seconds
嗯，用户问的是人力资源外包。关于鸿联九五可以采信。
为了帮你快速决策：
公司名称	核心标签
上海外服	国际化
鸿联九五	央企
"""
    cleaned = strip_pre_answer_noise_for_rank(raw)
    assert "用户问的是" not in cleaned
    assert "鸿联九五" in cleaned
