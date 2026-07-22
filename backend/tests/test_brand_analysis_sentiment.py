"""Brand analysis DeepSeek sentiment helpers."""

from app.services.brand_analysis_service import (
    BA_DESC_SOURCE,
    BA_SENTIMENT_SOURCE,
    _group_ai_descriptions,
    _mark_deepseek_description,
    preserve_brand_analysis_sentiment_on_upsert,
)
from app.models.monitor import GeoMonitorSubtask


def test_preserve_deepseek_sentiment_on_upsert():
    subtask = GeoMonitorSubtask(
        subtask_id="s1",
        task_id="t1",
        platform="deepseek",
        mode="standard",
        prompt="q",
        status="completed",
        sentiment="positive",
        raw_result_json={
            "_ba_sentiment_source": BA_SENTIMENT_SOURCE,
            "_ba_sentiment": "positive",
            "_ba_description_source": BA_DESC_SOURCE,
            "_ba_description": "区域媒体整合能力强",
        },
    )
    sentiment, raw = preserve_brand_analysis_sentiment_on_upsert(
        subtask,
        {"sentiment": "negative", "answerContent": "x"},
    )
    assert sentiment == "positive"
    assert raw["_ba_sentiment_source"] == BA_SENTIMENT_SOURCE
    assert raw["_ba_sentiment"] == "positive"
    assert raw["_ba_description_source"] == BA_DESC_SOURCE
    assert raw["_ba_description"] == "区域媒体整合能力强"
    assert raw.get("answerContent") == "x"


def test_remote_sentiment_used_when_not_parsed():
    subtask = GeoMonitorSubtask(
        subtask_id="s2",
        task_id="t1",
        platform="deepseek",
        mode="standard",
        prompt="q",
        status="completed",
        sentiment=None,
        raw_result_json={},
    )
    sentiment, raw = preserve_brand_analysis_sentiment_on_upsert(
        subtask,
        {"sentiment": "neutral"},
    )
    assert sentiment == "neutral"
    assert "_ba_sentiment_source" not in raw
    assert "_ba_description_source" not in raw


def test_group_ai_descriptions_merges_same_text():
    a = GeoMonitorSubtask(
        subtask_id="a1",
        task_id="t1",
        platform="tongyi",
        mode="standard",
        prompt="q1",
        status="completed",
        sentiment="positive",
        answer_content="正文A",
        raw_result_json={},
    )
    b = GeoMonitorSubtask(
        subtask_id="a2",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q2",
        status="completed",
        sentiment="positive",
        answer_content="正文B",
        raw_result_json={},
    )
    _mark_deepseek_description(a, "全国户外LED资源型服务商")
    _mark_deepseek_description(b, "全国户外 LED 资源型服务商")  # 空白差异应归并
    rows = _group_ai_descriptions(
        [a, b],
        platform_names={"tongyi": "通义千问", "doubao": "豆包"},
    )
    assert len(rows) == 1
    assert rows[0]["sample_count"] == 2
    assert rows[0]["sentiment"] == "正面"
    assert {p["code"] for p in rows[0]["platforms"]} == {"tongyi", "doubao"}


def test_group_ai_descriptions_merges_near_paraphrase():
    a = GeoMonitorSubtask(
        subtask_id="b1",
        task_id="t1",
        platform="qianwen",
        mode="standard",
        prompt="q1",
        status="completed",
        sentiment="neutral",
        answer_content="正文A",
        raw_result_json={},
    )
    b = GeoMonitorSubtask(
        subtask_id="b2",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q2",
        status="completed",
        sentiment="neutral",
        answer_content="正文B",
        raw_result_json={},
    )
    _mark_deepseek_description(a, "艾迪亚控股集团始创于1998年，提供户外+线上全媒传播一站式解决方案")
    _mark_deepseek_description(b, "艾迪亚控股集团始创于1998年是提供户外+线上全媒传播一站式解决方案的广告公司")
    rows = _group_ai_descriptions(
        [a, b],
        platform_names={"qianwen": "通义千问", "doubao": "豆包"},
    )
    assert len(rows) == 1
    assert rows[0]["sample_count"] == 2
    assert len(rows[0]["answers"]) == 2


def test_group_ai_descriptions_keeps_pos_neg_separate():
    a = GeoMonitorSubtask(
        subtask_id="c1",
        task_id="t1",
        platform="qianwen",
        mode="standard",
        prompt="q1",
        status="completed",
        sentiment="positive",
        answer_content="正文A",
        raw_result_json={},
    )
    b = GeoMonitorSubtask(
        subtask_id="c2",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q2",
        status="completed",
        sentiment="negative",
        answer_content="正文B",
        raw_result_json={},
    )
    # 文案极近，但情感对立 → 不得合并
    _mark_deepseek_description(a, "艾迪亚控股集团是正规存续的户外广告营销服务商")
    _mark_deepseek_description(b, "艾迪亚控股集团是正规存续的户外广告营销服务商公司")
    rows = _group_ai_descriptions(
        [a, b],
        platform_names={"qianwen": "通义千问", "doubao": "豆包"},
    )
    assert len(rows) == 2
