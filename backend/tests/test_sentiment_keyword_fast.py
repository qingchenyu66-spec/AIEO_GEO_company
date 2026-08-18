# -*- coding: utf-8 -*-
"""词云快路径与正负面短语过滤。"""
from types import SimpleNamespace

from app.services.sentiment_keyword_service import (
    _brand_adjacent_text,
    _brand_mentioned_light,
    _is_useful_sentiment_phrase,
    _phrase_matches_polarity,
    _phrase_polarity,
    _snippet_for_subtask,
)


def test_brand_mentioned_light_uses_mention_position():
    item = SimpleNamespace(mention_position=2, mention_context="", answer_content="")
    assert _brand_mentioned_light(item, {"艾迪亚"})


def test_brand_mentioned_light_matches_context_text():
    item = SimpleNamespace(
        mention_position=None,
        mention_context="推荐艾迪亚传媒",
        answer_content="",
    )
    assert _brand_mentioned_light(item, {"艾迪亚"})
    assert not _brand_mentioned_light(item, {"分众传媒"})


def test_useful_phrase_keeps_evaluative_text():
    blocked = {"艾迪亚控股集团", "分众传媒", "德高中国"}
    assert _is_useful_sentiment_phrase("落地执行力强", blocked)
    assert _is_useful_sentiment_phrase("报价偏高不透明", blocked)


def test_useful_phrase_drops_entities_and_meta():
    blocked = {"艾迪亚控股集团", "分众传媒", "德高中国", "中国平安"}
    assert not _is_useful_sentiment_phrase("艾迪亚控股集团", blocked)
    assert not _is_useful_sentiment_phrase("分众传媒", blocked)
    assert not _is_useful_sentiment_phrase("覆盖全国", blocked)
    assert not _is_useful_sentiment_phrase("篇资料作为参考", blocked)
    assert not _is_useful_sentiment_phrase("上海浦东", blocked)
    assert not _is_useful_sentiment_phrase("娃哈哈等", blocked)
    assert not _is_useful_sentiment_phrase("兆讯传媒", blocked)


def test_phrase_polarity_gates_neutral_selling_points():
    from app.services.sentiment_keyword_service import _accept_phrase_for_polarity

    assert _phrase_polarity("隐藏成本") == "negative"
    assert _phrase_matches_polarity("报价偏高不透明", "negative")
    assert not _phrase_matches_polarity("一手资源", "negative")
    assert not _accept_phrase_for_polarity("一手资源", "negative", from_llm=True)
    assert not _phrase_matches_polarity("全球户外老大", "negative")
    assert _phrase_matches_polarity("落地执行力强", "positive")
    # 正面 LLM：词表未覆盖但非负向 → 放行（勿用含「精准」等已扩词表项的样例）
    assert _accept_phrase_for_polarity("品牌知名度较高", "positive", from_llm=True)
    # 规则路径仍要求正向线索
    assert not _accept_phrase_for_polarity("品牌知名度较高", "positive", from_llm=False)
    # 2026-08-04 - 「头部」不再当正线索，「头部品牌」营销应被噪声丢掉
    assert _phrase_polarity("头部品牌") is None
    assert _phrase_polarity("已服务超500家头部品牌") is None
    assert _phrase_polarity("行业头部地位稳固") == "positive"


def test_useful_phrase_drops_head_brand_marketing_noise():
    """2026-08-04 - 方案A：头部品牌/已服务超N家刷屏。"""
    blocked = {"艾迪亚控股集团", "分众传媒"}
    assert not _is_useful_sentiment_phrase("头部品牌", blocked)
    assert not _is_useful_sentiment_phrase("已服务超500家头部品牌", blocked)
    assert not _is_useful_sentiment_phrase("服务超500家头部品牌", blocked)
    assert not _is_useful_sentiment_phrase("娃哈哈等500+头部品牌", blocked)
    assert not _is_useful_sentiment_phrase("长城葡萄酒", blocked)
    assert not _is_useful_sentiment_phrase("合作品牌包括平安等", blocked)
    # 仍保留真评价
    assert _is_useful_sentiment_phrase("落地执行力强", blocked)
    assert _is_useful_sentiment_phrase("综合实力首选", blocked)


def test_normalize_phrase_strips_list_and_brand_prefix():
    from app.services.sentiment_keyword_service import _normalize_phrase_text

    brands = {"艾迪亚控股集团", "艾迪亚"}
    assert _normalize_phrase_text("1. 艾迪亚控股集团 —— 综合实力首选", brands) == "综合实力首选"
    assert _normalize_phrase_text(";首选艾迪亚", brands) == "首选艾迪亚"
    assert _normalize_phrase_text("2.艾迪亚控股集团核心优势", brands) == ""


def test_collapse_drops_truncated_prefix():
    from app.services.sentiment_keyword_service import _collapse_substring_phrases

    bucket = {
        "精准投放到数据监测的全流程闭环服务": {
            "count": 3,
            "subtask_ids": ["a"],
            "task_ids": ["t"],
        },
        "精准投放到数据监测的全流": {
            "count": 2,
            "subtask_ids": ["b"],
            "task_ids": ["t"],
        },
    }
    out = _collapse_substring_phrases(bucket)
    assert "精准投放到数据监测的全流" not in out
    assert out["精准投放到数据监测的全流程闭环服务"]["count"] == 5


def test_extract_skips_sliding_window_stubs():
    from app.services.sentiment_keyword_service import _extract_phrases

    blocked = {"艾迪亚"}
    text = "艾迪亚可提供精准投放到数据监测的全流程闭环服务，综合实力首选。"
    phrases = _extract_phrases(
        text, blocked=blocked, polarity="positive", brand_names={"艾迪亚"}
    )
    assert "精准投放到数据监测的全流" not in phrases
    assert "综合实力首选" in phrases
    assert not any(p.startswith("以下是") for p in phrases)


def test_brand_adjacent_text_keeps_near_brand_only():
    text = (
        "行业里有很多玩家。艾迪亚存在隐藏成本问题，需要重点关注。"
        "另外一线核心线路资源强，这是行业共性。"
    )
    window = _brand_adjacent_text(text, {"艾迪亚"})
    assert "隐藏成本" in window
    assert "一线核心线路资源强" not in window


def test_snippet_prefers_mention_context_over_full_answer():
    item = SimpleNamespace(
        mention_context="艾迪亚报价不透明",
        answer_content="艾迪亚报价不透明。同时全国一手资源很多，全球户外老大也有布局。",
    )
    assert _snippet_for_subtask(item, {"艾迪亚"}) == "艾迪亚报价不透明"
