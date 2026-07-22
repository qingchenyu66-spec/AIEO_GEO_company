"""词云快路径与正负面短语过滤。"""
from types import SimpleNamespace

from app.services.sentiment_keyword_service import (
    _brand_mentioned_light,
    _is_useful_sentiment_phrase,
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
