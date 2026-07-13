"""模力指数风格售前诊断报告模板测试。"""

from datetime import datetime

from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows
from app.services.report_molizhishu_context_service import build_molizhishu_report_context
from app.services.report_molizhishu_fragments import (
    render_competitor_landscape_table,
    render_matrix_table,
    render_mention_table,
    render_prompt_platform_matrix,
)
from app.services.report_molizhishu_pdf_service import render_molizhishu_report_html


class _SubtaskStub:
    def __init__(self, *, task_id: str, prompt: str, rankings: list, updated_at: datetime) -> None:
        self.task_id = task_id
        self.prompt = prompt
        self.status = "completed"
        self.answer_content = "ok"
        self.all_rankings_json = rankings
        self.mention_position = None
        self.updated_at = updated_at


class _RunStub:
    def __init__(self, schedule_key: str, schedule_label: str, task_id: str) -> None:
        self.schedule_key = schedule_key
        self.schedule_label = schedule_label
        self.task_id = task_id


def _demo_payload() -> dict:
    return {
        "title": "春全合珠宝 售前品牌诊断报告",
        "report_type": "diagnosis",
        "brand_name": "春全合珠宝",
        "tenant_name": "春全合珠宝",
        "contact_phone": "13031099925",
        "competitors": [],
        "period_label": "2026-07-02 至 2026-07-09 · 三天九次均值",
        "generated_at": "2026-07-09T14:58:05",
        "platform_stats": [{"platform": "deepseek", "mention_rate": 60.0, "completed": 9, "total": 9}],
        "rank_trend": [
            {
                "schedule_key": "r1",
                "schedule_label": "2026-07-03 09:30",
                "avg_rank": 2.0,
                "entities": {"春全合珠宝": 2.0},
            }
        ],
        "tracked_entities": ["春全合珠宝"],
        "health_score": 72,
        "mention_rate": 36.9,
        "avg_rank": 4.2,
        "top3_rate": 19.2,
        "completed_count": 120,
        "source_count": 48,
        "executive_summary": "监测期内品牌在部分语义词表现稳定，但分平台差异显著。",
        "highlights": [
            "高铁广告推荐语义词平均排名第 3.8，为当前最优场景",
            "微博智搜提及率显著高于夸克与 DeepSeek",
        ],
        "platform_stats": [
            {"platform": "deepseek", "completed": 40, "mention_rate": 6.2, "avg_rank": 5.1},
            {"platform": "weibo_zhisou", "completed": 40, "mention_rate": 82.5, "avg_rank": 3.2},
        ],
        "matrix_rows": [
            {"prompt": "北京冰种翡翠手镯品牌哪家好", "platform": "deepseek", "mention_rate": 10.0, "avg_rank": 4.0},
        ],
        "sentiment_counts": {"positive": 90, "neutral": 8, "negative": 2},
        "positive_rate": 98.0,
        "diagnosis": {
            "strength_points": "口碑与提及率表现稳定",
            "weakness_points": "部分语义词未进 Top3",
            "recommendation": "补充垂直内容并强化引用布局",
        },
        "brand_date_matrix": {
            "prompts": ["北京冰种翡翠手镯品牌哪家好"],
            "rows": [{"label": "2026-07-09", "cells": [1.0]}],
        },
        "brand_city_matrix": {
            "prompts": ["北京冰种翡翠手镯品牌哪家好"],
            "rows": [{"label": "上海", "cells": [1.3]}],
        },
        "prompt_analytics": [
            {
                "prompt": "北京冰种翡翠手镯品牌哪家好",
                "round_trend": [{"schedule_label": "2026-07-09 14:00", "avg_rank": 1.0}],
                "molizhishu_ranking_rows": [
                    {
                        "name": "春全合珠宝",
                        "type_label": "最近",
                        "type_muted": False,
                        "category": "性价比与专业度",
                        "rank_display": "1",
                        "collected_at": "26-07-09 13:40",
                        "is_brand": True,
                        "is_competitor": False,
                    }
                ],
                "mention_table": [
                    {
                        "name": "春全合珠宝",
                        "mention_count": 15,
                        "sample_count": 16,
                        "mention_rate": 93.8,
                        "is_brand": True,
                    }
                ],
            }
        ],
        "top_sources": [{"title": "知乎", "count": 3}],
        "source_analysis": {"domain_stats": [{"domain": "zhihu.com", "count": 3, "brand_related_count": 1}]},
        "report_sections": {
            "industry_analysis": "<p>行业聚焦<strong style=\"color:#ff6666;\">翡翠手镯</strong>。</p>",
            "ranking_analysis": "<p>排名分析</p>",
            "mention_analysis": "<p>提及率分析</p>",
            "source_analysis": "<p>引用网站分析</p>",
            "action_recommendations": "<p>采取措施建议</p>",
        },
    }


def test_molizhishu_ranking_rows_keep_same_day_executions_separate() -> None:
    from datetime import datetime

    from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows

    runs = {
        "t1": _RunStub("202607020930", "2026-07-02 09:30", "t1"),
        "t2": _RunStub("202607021430", "2026-07-02 14:30", "t2"),
    }
    subtasks = [
        _SubtaskStub(
            task_id="t1",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 4, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 2, 9, 40),
        ),
        _SubtaskStub(
            task_id="t2",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 2, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 2, 14, 40),
        ),
    ]
    rows = _build_molizhishu_ranking_rows(
        subtasks,
        brand="春全合珠宝",
        competitors=[],
        task_run_map=runs,
    )
    brand_rows = [row for row in rows if row["is_brand"] and row["type_label"] == "最近"]
    assert len(brand_rows) == 1
    assert brand_rows[0]["rank_display"] == "2"
    assert brand_rows[0]["collected_at"] == "2026-07-02 14:30"


def test_molizhishu_ranking_rows_labels_recent_best_worst() -> None:
    runs = {
        "t1": _RunStub("202607020930", "2026-07-02 09:30", "t1"),
        "t2": _RunStub("202607090930", "2026-07-09 09:30", "t2"),
    }
    subtasks = [
        _SubtaskStub(
            task_id="t1",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 5, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 2, 9, 40),
        ),
        _SubtaskStub(
            task_id="t2",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 1, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 9, 9, 40),
        ),
    ]
    rows = _build_molizhishu_ranking_rows(
        subtasks,
        brand="春全合珠宝",
        competitors=[],
        task_run_map=runs,
    )
    labels = {row["type_label"] for row in rows if row["is_brand"]}
    assert "最近" in labels
    assert "最优" in labels
    assert "最差" in labels


def test_molizhishu_html_matches_reference_markers() -> None:
    html = render_molizhishu_report_html(_demo_payload())
    assert "品牌用户专属报表分析 - 专业版" in html
    assert "诊断概览" in html
    assert "kpi-grid" in html
    assert "情感与口碑" in html
    assert "竞品格局对比" in html
    assert "语义词 × 平台矩阵" in html
    assert "信源优化建议" in html
    assert "分平台表现" in html
    assert "语义词成绩单" in html
    assert "分析平台" in html
    assert 'id="t_divBrandRecent"' in html
    assert 'id="t_divBrandCityRank"' in html
    assert "分享链接导入" not in html
    assert "13031099925" in html
    assert "采集次数" in html
    assert "当天排名前三企业引用网站概览" in html
    assert "AI搜索平台品牌竞争力洞察" in html
    assert "progress-container" in html
    assert "report-theme-b" in html
    assert "#1677ff" in html
    assert 'background-color: #000000' not in html


def test_matrix_and_mention_fragment_markup() -> None:
    matrix = render_matrix_table("t_divBrandRecent", "日期", ["语义词A"], [{"label": "2026-07-09", "cells": [2]}])
    assert 'style="background-color:hsl(' in matrix
    mention = render_mention_table("report-list2-x", [{"name": "品牌", "sample_count": 16, "mention_count": 15, "mention_rate": 93.8, "is_brand": True}])
    assert "93.8%" in mention
    assert "brand-row-outline" in mention

    ctx = build_molizhishu_report_context(_demo_payload())
    assert ctx["competitor_text"] == "未指定竞品"
    assert ctx["platform_label"] == "DeepSeek 等 2 个平台"
    assert ctx["show_contact_meta"] is True

    no_contact = build_molizhishu_report_context({**_demo_payload(), "contact_phone": "", "contact_name": ""})
    assert no_contact["show_contact_meta"] is False

    matrix_html = render_prompt_platform_matrix(
        {
            "platforms": ["DeepSeek"],
            "rows": [{"prompt": "测试词", "cells": [{"mention_rate": 38, "avg_rank": 6.0}]}],
        }
    )
    assert "#6" not in matrix_html
    assert "38%" in matrix_html
    assert "6" in matrix_html


def test_competitor_landscape_has_entity_colors_and_visible_rank_risk() -> None:
    html = render_competitor_landscape_table(
        [
            {"name": "艾迪亚控股集团有限公司", "mention_rate": 8.8, "avg_rank": 4.2, "is_brand": True},
            {"name": "分众传媒", "mention_rate": 93.8, "avg_rank": 1.2},
            {"name": "白马户外媒体", "mention_rate": 3.8, "avg_rank": 6.1},
        ]
    )

    assert 'data-entity-color="#0057D9"' in html
    assert 'data-entity-color="#F28E2B"' in html
    assert 'data-entity-color="#009E73"' in html
    assert "rank-risk-good" in html
    assert "rank-risk-watch" in html
    assert "rank-risk-warning" in html
    assert "达标（前三）" in html


def test_mention_table_uses_company_color_for_each_progress_bar() -> None:
    html = render_mention_table(
        "competitor-bars",
        [
            {"name": "艾迪亚控股集团有限公司", "sample_count": 80, "mention_count": 7, "mention_rate": 8.8, "is_brand": True},
            {"name": "分众传媒", "sample_count": 80, "mention_count": 75, "mention_rate": 93.8, "is_competitor": True},
        ],
    )

    assert "--entity-color: #0057D9" in html
    assert "--entity-color: #F28E2B" in html


def test_report_adds_competitor_strategy_and_removes_answer_excerpts() -> None:
    payload = _demo_payload()
    payload["competitors"] = ["分众传媒", "白马户外媒体"]
    payload["report_enrichment"] = {
        "competitor_landscape": [
            {"name": "春全合珠宝", "avg_rank": 4.2, "mention_rate": 8.8, "is_brand": True},
            {"name": "分众传媒", "avg_rank": 1.4, "mention_rate": 93.8},
            {"name": "白马户外媒体", "avg_rank": 5.1, "mention_rate": 2.5},
        ],
        "answer_excerpts": [
            {"prompt": "测试问题", "platform": "deepseek", "rank": 4, "excerpt": "不应出现在报告中"},
        ],
    }

    html = render_molizhishu_report_html(payload)

    assert "竞争格局摘要" in html
    assert "运营建议动作" in html
    assert "排名风险说明" in html
    assert "AI 回答摘录" not in html
    assert "不应出现在报告中" not in html
    assert "excerpt-card" not in html
