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
    # 文案极近，但情感对立 → 不得合并（显式正负，避免继承纠偏把负改中性）
    _mark_deepseek_descriptions(
        a,
        [{"text": "艾迪亚控股集团是正规存续的户外广告营销服务商", "sentiment": "positive"}],
    )
    _mark_deepseek_descriptions(
        b,
        [{"text": "艾迪亚控股集团是正规存续的户外广告营销服务商公司", "sentiment": "negative"}],
    )
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


def test_descriptions_similar_keeps_risk_away_from_founding():
    """2026-07-29 - 同主体「吊销」不得与「成立」因长前缀误并。"""
    from app.services.brand_analysis_service import _brand_aliases, _descriptions_similar

    aliases = _brand_aliases("艾迪亚控股集团有限公司", "艾迪亚")
    assert not _descriptions_similar(
        "艾迪亚（北京）控股集团有限公司吊销日期为2024年8月14日",
        "艾迪亚（北京）控股集团有限公司成立于2021年",
        brand_aliases=aliases,
    )
    assert not _descriptions_similar(
        "艾迪亚（北京）控股集团有限公司吊销日期为2024年8月14日",
        "艾迪亚控股集团有限公司2008年成立",
        brand_aliases=aliases,
    )


def test_group_risk_point_negative_even_if_parent_positive():
    """整段正面、要点含吊销 → 该组必须负面，且不与成立类并组。"""
    from app.services.brand_analysis_service import _brand_aliases

    a = GeoMonitorSubtask(
        subtask_id="r1",
        task_id="t1",
        platform="deepseek",
        mode="standard",
        prompt="q1",
        status="completed",
        sentiment="positive",
        answer_content="长文含吊销",
        raw_result_json={},
    )
    b = GeoMonitorSubtask(
        subtask_id="r2",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q2",
        status="completed",
        sentiment="positive",
        answer_content="长文成立",
        raw_result_json={},
    )
    _mark_deepseek_descriptions(
        a,
        [
            {"text": "艾迪亚（北京）控股集团有限公司吊销日期为2024年8月14日", "sentiment": "negative"},
            {"text": "1998年起深耕营销传播领域", "sentiment": "positive"},
        ],
    )
    _mark_deepseek_descriptions(
        b,
        [{"text": "艾迪亚（北京）控股集团有限公司成立于2021年", "sentiment": "neutral"}],
    )
    rows = _group_ai_descriptions(
        [a, b],
        platform_names={"deepseek": "DeepSeek", "doubao": "豆包"},
        brand_aliases=_brand_aliases("艾迪亚控股集团有限公司", "艾迪亚"),
    )
    by_desc = {r["description"]: r for r in rows}
    risk = next(r for r in rows if "吊销" in r["description"])
    assert risk["sentiment"] == "负面"
    assert risk["sample_count"] == 1
    founding = next(r for r in rows if "成立于2021" in r["description"])
    assert founding["sentiment"] != "负面" or "吊销" not in founding["description"]
    assert risk["description"] != founding["description"]
    assert len(by_desc) >= 3


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


def test_legacy_risk_string_falls_back_negative():
    """旧 v2 仅字符串列表、父情感正面时，含吊销要点读路径仍回退负面。"""
    from app.services.brand_analysis_service import _ba_description_items

    subtask = GeoMonitorSubtask(
        subtask_id="legacy1",
        task_id="t1",
        platform="deepseek",
        mode="standard",
        prompt="q",
        status="completed",
        sentiment="positive",
        answer_content="正文",
        raw_result_json={
            "_ba_description_source": "deepseek-v2",
            "_ba_descriptions": [
                "艾迪亚（北京）控股集团有限公司吊销日期为2024年8月14日",
                "1998年起深耕营销传播领域",
            ],
        },
    )
    items = _ba_description_items(subtask)
    by_text = {row["text"]: row["sentiment"] for row in items}
    assert by_text["艾迪亚（北京）控股集团有限公司吊销日期为2024年8月14日"] == "negative"
    assert by_text["1998年起深耕营销传播领域"] == "positive"


def test_cleared_risk_not_forced_negative():
    """2026-08-04 - 「无行政处罚」不得因命中「行政处罚」强制负面。"""
    from app.services.brand_analysis_service import _normalize_description_items

    rows = _normalize_description_items(
        [{"text": "北京华兴星图教育科技股份有限公司无行政处罚记录", "sentiment": "negative"}],
        fallback_sentiment="negative",
    )
    assert len(rows) == 1
    assert rows[0]["sentiment"] == "neutral"


def test_non_risk_does_not_inherit_parent_negative():
    """2026-08-04 - 非风险要点勿继承整段负面。"""
    from app.services.brand_analysis_service import _normalize_description_items

    rows = _normalize_description_items(
        ["价格透明流程清晰服务响应快"],
        fallback_sentiment="negative",
    )
    assert rows[0]["sentiment"] == "neutral"


def test_entity_fact_llm_negative_downgraded():
    """2026-08-04 - 公司介绍被 LLM 标负 → 纠为中性。"""
    from app.services.brand_analysis_service import _normalize_description_items

    text = "艾迪亚控股集团核心主体为北京艾迪亚传媒科技集团有限公司，提供户外加线上全媒体传播一站式解决方案"
    rows = _normalize_description_items(
        [{"text": text, "sentiment": "negative"}],
        fallback_sentiment="negative",
    )
    assert rows[0]["sentiment"] == "neutral"


def test_group_non_risk_majority_not_any_negative():
    """2026-08-04 - 非风险组多数决；硬风险组仍有负即负。"""
    from app.services.brand_analysis_service import _brand_aliases

    a = GeoMonitorSubtask(
        subtask_id="m1",
        task_id="t1",
        platform="doubao",
        mode="standard",
        prompt="q1",
        status="completed",
        sentiment="neutral",
        answer_content="A",
        raw_result_json={},
    )
    b = GeoMonitorSubtask(
        subtask_id="m2",
        task_id="t1",
        platform="deepseek",
        mode="standard",
        prompt="q2",
        status="completed",
        sentiment="neutral",
        answer_content="B",
        raw_result_json={},
    )
    c = GeoMonitorSubtask(
        subtask_id="m3",
        task_id="t1",
        platform="kimi",
        mode="standard",
        prompt="q3",
        status="completed",
        sentiment="negative",
        answer_content="C",
        raw_result_json={},
    )
    # 同文案：2 中性 + 1 负面（非风险）→ 组标签中性
    for item, sent in ((a, "neutral"), (b, "neutral"), (c, "negative")):
        _mark_deepseek_descriptions(
            item,
            [{"text": "价格偏高但交付流程相对清晰", "sentiment": sent}],
        )
    rows = _group_ai_descriptions(
        [a, b, c],
        platform_names={"doubao": "豆包", "deepseek": "DeepSeek", "kimi": "Kimi"},
    )
    assert len(rows) == 1
    assert rows[0]["sentiment"] == "中性"
    assert rows[0]["sample_count"] == 3

    risk = GeoMonitorSubtask(
        subtask_id="m4",
        task_id="t1",
        platform="yuanbao",
        mode="standard",
        prompt="q4",
        status="completed",
        sentiment="positive",
        answer_content="D",
        raw_result_json={},
    )
    _mark_deepseek_descriptions(
        risk,
        [{"text": "艾迪亚（北京）控股集团有限公司吊销日期为2024年8月14日", "sentiment": "negative"}],
    )
    risk_rows = _group_ai_descriptions(
        [risk],
        platform_names={"yuanbao": "元宝"},
        brand_aliases=_brand_aliases("艾迪亚控股集团有限公司", "艾迪亚"),
    )
    assert risk_rows[0]["sentiment"] == "负面"


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

