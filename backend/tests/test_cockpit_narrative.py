"""驾驶舱叙事包归一化自检（不打真实 DeepSeek）。"""

from __future__ import annotations

from app.services.deepseek_client import _normalize_cockpit_narrative
from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context, render_diagnosis_cockpit_html


def test_normalize_cockpit_narrative_fills_p0_p1_p2():
    out = _normalize_cockpit_narrative(
        {
            "stage_copy": {
                "all": {"title": "测试标题", "summary": "摘要一段"},
            },
            "priority_items": [
                {"title": "弱场景", "body": "电梯短板"},
            ],
            "actions": [],
            "risk_rows": [],
        },
        brand="艾迪亚",
    )
    assert out["priority_items"][0]["level_class"] == "p0"
    assert out["priority_items"][1]["level_class"] == "p1"
    assert out["priority_items"][2]["level_class"] == "p2"
    assert len(out["actions"]) == 3
    assert out["stage_copy"]["all"]["summary"] == "摘要一段"


def test_cockpit_context_consumes_narrative():
    html = render_diagnosis_cockpit_html(
        {
            "brand_name": "艾迪亚",
            "kpis": {"mention_rate": 30, "avg_rank": 3, "top3_rate": 20},
            "prompt_analytics": [
                {"prompt": "电梯广告公司推荐", "brand_mention_rate": 8, "brand_avg_rank": 5, "sample_count": 4},
            ],
            "platform_stats": [],
            "diagnosis": {},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {
                        "label": "管理层摘要",
                        "title": "叙事标题<span>强调</span>",
                        "summary": "这是 DeepSeek 生成的摘要，用于驾驶舱 hero。",
                    },
                    "recognition": {"label": "品牌认知阶段", "title": "认知", "summary": "认知段"},
                    "selection": {"label": "技术选型阶段", "title": "选型", "summary": "选型段"},
                    "procurement": {"label": "项目采购阶段", "title": "采购", "summary": "采购段"},
                    "risk": {"label": "风险质疑阶段", "title": "风险", "summary": "风险段"},
                },
                "priority_items": [
                    {
                        "level_class": "p0",
                        "level": "P0 · 场景攻坚",
                        "tone": "status-risk",
                        "tone_label": "缺口明显",
                        "title": "DeepSeek-P0标题",
                        "body": "DeepSeek-P0正文",
                    },
                    {
                        "level_class": "p1",
                        "level": "P1 · 平台覆盖",
                        "tone": "status-gap",
                        "tone_label": "需结构化",
                        "title": "DeepSeek-P1标题",
                        "body": "DeepSeek-P1正文",
                    },
                    {
                        "level_class": "p2",
                        "level": "P2 · 优势放大",
                        "tone": "status-ok",
                        "tone_label": "基础较强",
                        "title": "DeepSeek-P2标题",
                        "body": "DeepSeek-P2正文",
                    },
                ],
                "risk_rows": [
                    {
                        "topic": "叙事风险",
                        "models": "多平台",
                        "impact": "影响入围",
                        "evidence": "案例",
                        "priority": "P0",
                        "pill": "risk-high",
                    }
                ],
                "actions": [
                    {
                        "level_class": "p0",
                        "level": "P0 · 30 天",
                        "impact": "夯实",
                        "title": "行动P0",
                        "body": "行动正文",
                        "bullets": ["a", "b", "c"],
                    },
                    {
                        "level_class": "p1",
                        "level": "P1 · 60 天",
                        "impact": "提升",
                        "title": "行动P1",
                        "body": "行动正文",
                        "bullets": ["a", "b", "c"],
                    },
                    {
                        "level_class": "p2",
                        "level": "P2 · 90 天",
                        "impact": "扩大",
                        "title": "行动P2",
                        "body": "行动正文",
                        "bullets": ["a", "b", "c"],
                    },
                ],
            },
        }
    )
    assert "DeepSeek-P0标题" in html
    # 2026-08-13 - 管理层摘要强制对齐当前 KPI null/0，不再原样透传 DeepSeek all.summary
    assert "这是 DeepSeek 生成的摘要" not in html
    assert "提及率" in html or "暂无数据" in html
    assert "认知段" in html
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB",
            "prompt_analytics": [],
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "管理层摘要", "title": "x<span>y</span>", "summary": "s"},
                    "recognition": {"label": "品牌认知阶段", "title": "t", "summary": "s"},
                    "selection": {"label": "技术选型阶段", "title": "t", "summary": "s"},
                    "procurement": {"label": "项目采购阶段", "title": "t", "summary": "s"},
                    "risk": {"label": "风险质疑阶段", "title": "t", "summary": "s"},
                },
                "priority_items": [
                    {"level_class": "p0", "level": "P0 · 场景攻坚", "tone": "status-risk", "tone_label": "缺口明显", "title": "a", "body": "b"},
                    {"level_class": "p1", "level": "P1 · 平台覆盖", "tone": "status-gap", "tone_label": "需结构化", "title": "a", "body": "b"},
                    {"level_class": "p2", "level": "P2 · 优势放大", "tone": "status-ok", "tone_label": "基础较强", "title": "a", "body": "b"},
                ],
            },
        }
    )
    assert ctx["priority_items"][0]["title"] == "a"
