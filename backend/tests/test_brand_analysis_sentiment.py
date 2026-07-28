"""Brand analysis DeepSeek sentiment helpers."""

from app.services.brand_analysis_service import (
    BA_DESC_HARD_MAX,
    BA_DESC_SOURCE,
    BA_SENTIMENT_SOURCE,
    _ba_descriptions,
    _group_ai_descriptions,
    _mark_deepseek_description,
    _mark_deepseek_descriptions,
    _normalize_description_list,
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
            "_ba_descriptions": ["区域媒体整合能力强", "防火涂料为核心优势"],
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
    assert raw["_ba_descriptions"] == ["区域媒体整合能力强", "防火涂料为核心优势"]
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


def test_descriptions_similar_merges_paraphrase_not_different_biz():
    from app.services.brand_analysis_service import _descriptions_similar

    assert _descriptions_similar(
        "高铁业务覆盖全国300+核心站点",
        "高铁广告覆盖全国300多个核心高铁站及列车内部",
    )
    assert _descriptions_similar(
        "总部位于北京",
        "2008年成立总部位于北京",
    )
    assert not _descriptions_similar(
        "艾迪亚传媒主营业务包括短视频自媒体运营",
        "艾迪亚传媒核心业务包括户外媒体资源运营与投放",
    )


def test_group_merges_near_paraphrase_across_snapshots():
    a = GeoMonitorSubtask(
        subtask_id="e1",
        task_id="t1",
        platform="tongyi",
        mode="standard",
        prompt="q1",
        status="completed",
        sentiment="positive",
        answer_content="A",
        raw_result_json={},
    )
    b = GeoMonitorSubtask(
        subtask_id="e2",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q2",
        status="completed",
        sentiment="positive",
        answer_content="B",
        raw_result_json={},
    )
    _mark_deepseek_description(a, "是一二线城市交通户外媒体的一级代理")
    _mark_deepseek_description(b, "艾迪亚传媒是一二线城市户外传播的一级代理服务商")
    rows = _group_ai_descriptions(
        [a, b],
        platform_names={"tongyi": "通义千问", "doubao": "豆包"},
    )
    assert len(rows) == 1
    assert rows[0]["sample_count"] == 2


def test_normalize_description_list_hard_cap():
    items = [f"独立有用要点编号{i:02d}内容" for i in range(20)]
    cleaned = _normalize_description_list(items)
    assert len(cleaned) == BA_DESC_HARD_MAX


def test_ba_descriptions_compat_single_field():
    subtask = GeoMonitorSubtask(
        subtask_id="d0",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q",
        status="completed",
        sentiment="positive",
        answer_content="正文",
        raw_result_json={
            "_ba_description_source": BA_DESC_SOURCE,
            "_ba_description": "防火涂料为核心优势",
        },
    )
    assert _ba_descriptions(subtask) == ["防火涂料为核心优势"]


def test_group_ai_descriptions_one_snapshot_many_points():
    """一个快照拆多条要点 → 多组；同快照可出现在多组。"""
    subtask = GeoMonitorSubtask(
        subtask_id="d1",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="金隅涂料怎么样",
        status="completed",
        sentiment="positive",
        answer_content="长文",
        raw_result_json={},
    )
    _mark_deepseek_descriptions(
        subtask,
        [
            "国企背景的防火涂料企业",
            "服务大兴机场等重点工程",
            "具备ISO与消防认证资质",
        ],
    )
    assert len(_ba_descriptions(subtask)) == 3
    rows = _group_ai_descriptions(
        [subtask],
        platform_names={"doubao": "豆包"},
    )
    assert len(rows) == 3
    assert all(r["sample_count"] == 1 for r in rows)
    assert all(r["answers"][0]["subtask_id"] == "d1" for r in rows)
