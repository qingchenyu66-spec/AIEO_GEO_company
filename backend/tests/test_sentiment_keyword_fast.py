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
    assert _phrase_polarity("隐藏成本") == "negative"
    assert _phrase_matches_polarity("报价偏高不透明", "negative")
    assert not _phrase_matches_polarity("一手资源", "negative")
    assert not _phrase_matches_polarity("全球户外老大", "negative")
    assert _phrase_matches_polarity("落地执行力强", "positive")


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
