"""Premium 报告 8 大模块测试。"""

from app.services.report_period_content_service import (
    REPORT_MODULE_SCHEMA_VERSION,
    build_premium_content,
    build_report_modules,
    format_diagnosis_display_title,
    normalize_sentiment_counts,
    sanitize_report_modules_for_type,
)
from app.services.report_premium_context_service import build_premium_report_context


def _demo_kpis() -> dict:
    return {
        "mention_rate": 57.1,
        "avg_rank": 2.8,
        "top3_rate": 42.5,
        "positive_rate": 68.2,
        "completed_count": 1920,
        "source_count": 18,
        "health_score": 75,
    }


def _demo_platforms() -> list[dict]:
    return [
        {"platform": "doubao", "completed": 640, "total": 640, "mention_rate": 62.0, "avg_rank": 2.2},
        {"platform": "kimi", "completed": 640, "total": 640, "mention_rate": 57.5, "avg_rank": 2.6},
        {"platform": "deepseek", "completed": 640, "total": 640, "mention_rate": 54.0, "avg_rank": 3.1},
    ]


def test_annual_report_modules_have_eight_blocks() -> None:
    modules = build_report_modules(
        brand_name="艾迪亚控股集团有限公司",
        company_name="艾迪亚控股集团有限公司",
        report_type="annual",
        period_label="2025 年度",
        kpis=_demo_kpis(),
        platform_stats=_demo_platforms(),
        sentiment_counts={"正面": 1305, "中性": 422, "负面": 153},
        top_sources=[
            {"title": "知乎 - 行业选购指南", "count": 12},
            {"title": "官方网站品牌介绍", "count": 9},
        ],
        competitor_names=["竞品A"],
    )
    assert modules["schema_version"] == REPORT_MODULE_SCHEMA_VERSION
    assert modules["preface"]["publisher"]
    assert len(modules["overview"]["interpretations"]) == 4
    assert len(modules["sentiment"]["layers"]) == 3
    assert len(modules["platform_benchmark"]["rows"]) == 3
    assert modules["platform_benchmark"]["rows"][0]["is_leading"]
    assert len(modules["risk_and_strategy"]["dimensions"]) == 4
    assert modules["action_plan"]["goals"]
    assert len(modules["disclaimer"]["notes"]) == 4
    assert len(modules["toc"]) == 8


def test_weekly_action_plan_differs_from_annual() -> None:
    weekly = build_report_modules(
        brand_name="测试品牌",
        company_name="测试企业",
        report_type="weekly",
        period_label="2026-W10",
        kpis={"completed_count": 42, "mention_rate": 61.9, "avg_rank": 2.4, "top3_rate": 47.6, "positive_rate": 72, "health_score": 78},
        platform_stats=_demo_platforms(),
        sentiment_counts={"正面": 30, "中性": 10, "负面": 2},
        top_sources=[],
        competitor_names=[],
    )
    annual = build_report_modules(
        brand_name="测试品牌",
        company_name="测试企业",
        report_type="annual",
        period_label="2025 年度",
        kpis=_demo_kpis(),
        platform_stats=_demo_platforms(),
        sentiment_counts={"正面": 1305, "中性": 422, "负面": 153},
        top_sources=[],
        competitor_names=[],
    )
    assert weekly["action_plan"]["title"] != annual["action_plan"]["title"]
    assert "周" in weekly["preface"]["sample_description"] or "本周" in weekly["preface"]["sample_description"]


def test_diagnosis_report_modules() -> None:
    modules = build_report_modules(
        brand_name="测试品牌",
        company_name="测试企业",
        report_type="diagnosis",
        period_label="截至 2026-03-08",
        kpis={"completed_count": 120, "mention_rate": 45, "avg_rank": 3.5, "top3_rate": 30, "positive_rate": 55, "health_score": 68},
        platform_stats=_demo_platforms(),
        sentiment_counts={"正面": 60, "中性": 40, "负面": 20},
        top_sources=[{"title": "知乎", "count": 5}],
        competitor_names=["竞品B"],
        diagnosis={"weakness_points": "价格端套餐区分不够清晰"},
    )
    assert "诊断" in modules["preface"]["purpose"]
    assert modules["action_plan"] is None
    assert len(modules["toc"]) == 7
    assert "30 天" not in " ".join(item["title"] for item in modules["toc"])


def test_diagnosis_sanitize_strips_legacy_cover_title_suffix() -> None:
    legacy_title = "GEO企业诊断报告（2026-06-30 至 2026-07-02 · 三天九次均值（8/9 次有效抓取））"
    modules = {
        "schema_version": REPORT_MODULE_SCHEMA_VERSION,
        "preface": {"report_title": legacy_title, "period_range": "2026-06-30 至 2026-07-02"},
        "action_plan": {"title": "30 天行动规划"},
        "toc": [{"page": 2, "title": "x"}] * 8,
    }
    cleaned = sanitize_report_modules_for_type(modules, "diagnosis")
    assert cleaned["preface"]["report_title"] == "GEO企业诊断报告"
    assert cleaned["action_plan"] is None


def test_format_diagnosis_display_title_nested_parentheses() -> None:
    raw = "GEO 企业诊断报告 (2026-06-30 至 2026-07-02 · 三天九次均值 (8/9 次有效抓取) )"
    assert format_diagnosis_display_title(raw) == "GEO 企业诊断报告"


def test_diagnosis_premium_context_omits_action_plan() -> None:
    ctx = build_premium_report_context(
        {
            "brand_name": "测试品牌",
            "report_type": "diagnosis",
            "title": "GEO企业诊断报告（2026-06-30 至 2026-07-02 · 三天九次均值（8/9 次有效抓取））",
            "period_label": "诊断",
            "completed_count": 120,
            "platform_stats": _demo_platforms(),
            "sentiment_counts": {"正面": 60, "中性": 40, "负面": 20},
            "report_modules": {
                "schema_version": REPORT_MODULE_SCHEMA_VERSION,
                "preface": {
                    "report_title": "GEO企业诊断报告（2026-06-30 至 2026-07-02 · 三天九次均值（8/9 次有效抓取））",
                },
            },
        }
    )
    assert ctx["title"] == "GEO企业诊断报告"
    assert ctx["preface"]["report_title"] == "GEO企业诊断报告"
    assert not ctx["action_plan"].get("title")
    assert len(ctx["toc"]) == 7


def test_premium_context_from_legacy_payload() -> None:
    ctx = build_premium_report_context(
        {
            "title": "GEO 监测年报（2025 年度）",
            "type_label": "监测年报",
            "report_type": "annual",
            "brand_name": "艾迪亚控股集团有限公司",
            "company_name": "艾迪亚控股集团有限公司",
            "period_label": "2025 年度",
            "health_score": 75,
            "mention_rate": 57.1,
            "avg_rank": 2.8,
            "top3_rate": 42.5,
            "positive_rate": 68.2,
            "completed_count": 1920,
            "platform_stats": _demo_platforms(),
            "sentiment_counts": {"正面": 1305, "中性": 422, "负面": 153},
            "top_sources": [{"title": "知乎 - 行业选购指南", "count": 12, "platforms": ["doubao"]}],
        }
    )
    assert ctx["modules"]["preface"]
    assert len(ctx["toc"]) == 8
    assert ctx["platform_benchmark"]["rows"]


def test_premium_content_wraps_modules() -> None:
    premium = build_premium_content(
        brand_name="艾迪亚",
        company_name="艾迪亚控股集团有限公司",
        report_type="annual",
        period_label="2025 年度",
        kpis=_demo_kpis(),
        platform_stats=_demo_platforms(),
        diagnosis={"health_score": 75},
        report_sections={},
        executive_summary=None,
        highlights=["样本 1920 条"],
        sentiment_counts={"正面": 1305, "中性": 422, "负面": 153},
        top_sources=[{"title": "知乎", "count": 12}],
    )
    assert premium["modules"]["action_plan"]["goals"]
    assert len(premium["strategies"]) == 4


def test_normalize_sentiment_counts_accepts_english_keys() -> None:
    counts = normalize_sentiment_counts({"positive": 268, "neutral": 525, "negative": 6, "unknown": 1})
    assert counts["正面"] == 268
    assert counts["中性"] == 525
    assert counts["负面"] == 6
    assert counts["未知"] == 1


def test_premium_context_sentiment_layers_from_english_keys() -> None:
    ctx = build_premium_report_context(
        {
            "brand_name": "艾迪亚控股",
            "report_type": "diagnosis",
            "period_label": "诊断",
            "completed_count": 800,
            "monitor_snapshot": {
                "sentiment_counts": {"positive": 268, "neutral": 525, "negative": 6, "unknown": 1},
            },
            "diagnosis": {
                "sentiment_summary": "正面情绪占比 99.1%，与真实分布不一致的 AI 文案",
            },
            "report_modules": {
                "schema_version": REPORT_MODULE_SCHEMA_VERSION,
                "sentiment": {
                    "total_samples": 800,
                    "layers": [
                        {"label": "正面", "count": 0, "percent": 0.0},
                        {"label": "中性", "count": 0, "percent": 0.0},
                        {"label": "负面", "count": 0, "percent": 0.0},
                    ],
                    "summary": "正面情绪占比 99.1%",
                },
            },
        }
    )
    layers = ctx["sentiment"]["layers"]
    assert layers[0]["count"] == 268
    assert layers[1]["count"] == 525
    assert layers[2]["count"] == 6
    assert "99.1%" not in ctx["sentiment"]["summary"]
    assert "33.5%" in ctx["sentiment"]["summary"] or "268" in ctx["sentiment"]["summary"]
