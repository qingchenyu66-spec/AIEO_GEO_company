"""Competitor secondary sentiment helpers."""

from app.models.monitor import GeoMonitorSubtask
from app.services.brand_analysis_service import (
    BA_SENTIMENT_RULE_SOURCE,
    BA_SENTIMENT_SOURCE,
    effective_monitor_sentiment,
    rule_classify_brand_sentiment,
    _mark_rule_sentiment,
)


def test_rule_classify_risk_and_praise():
    assert rule_classify_brand_sentiment("艾迪亚控股因吊销营业执照存在风险", "艾迪亚") == "negative"
    assert rule_classify_brand_sentiment("艾迪亚传媒是行业推荐首选品牌", "艾迪亚") == "positive"
    assert rule_classify_brand_sentiment("成立于2008年注册资本1000万", "艾迪亚") == "neutral"


def test_effective_prefers_secondary_over_molizhishu_neutral():
    subtask = GeoMonitorSubtask(
        subtask_id="s1",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q",
        status="completed",
        sentiment="neutral",
        raw_result_json={},
    )
    assert effective_monitor_sentiment(subtask) == "neutral"
    _mark_rule_sentiment(subtask, "positive")
    assert subtask.raw_result_json["_ba_sentiment_source"] == BA_SENTIMENT_RULE_SOURCE
    assert effective_monitor_sentiment(subtask) == "positive"
    subtask.raw_result_json = {
        "_ba_sentiment_source": BA_SENTIMENT_SOURCE,
        "_ba_sentiment": "negative",
    }
    subtask.sentiment = "neutral"
    assert effective_monitor_sentiment(subtask) == "negative"
