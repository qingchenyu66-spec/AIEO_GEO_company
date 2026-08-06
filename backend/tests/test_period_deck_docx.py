"""周期 deck Word 导出 smoke test。"""

from __future__ import annotations

from datetime import date

from app.services.report_period_deck_docx_service import render_period_deck_docx_from_bundle


def test_period_deck_docx_minimal_bundle() -> None:
    bundle = {
        "brand_name": "测试品牌",
        "report_type": "monthly",
        "period_lbl": "2026年07月",
        "generated": date(2026, 8, 6),
        "comparison": {
            "previous_period_label": "2026年06月",
            "kpis": {
                "health_score": {"current": 78, "text": "+2"},
                "mention_rate": {"current": 79.0, "text": "↑"},
                "avg_rank": {"current": 2.3, "text": "—"},
                "top3_rate": {"current": 67.6, "text": "—"},
            },
            "highlights": ["综合健康分 78 分。"],
            "platform_rows": [],
        },
        "snapshot": {"kpis": {"completed_count": 524}},
        "preface": {
            "sample_description": "本期累计完成 524 条有效监测样本。",
            "report_title": "监测月报",
            "publisher": "GEO Monitor",
            "monitor_tool": "GEO Monitor 品牌监测平台",
            "period_range": "2026.07.01-2026.07.31",
            "monitor_keywords": "词A、词B",
            "competitors": "竞品A",
            "core_dimensions": ["品牌提及率", "平均排名"],
            "purpose": "品牌传播分析参考。",
        },
        "content_modules": {
            "disclaimer": {"notes": ["本报告仅供内部参考。"]},
        },
        "trend": {
            "title": "趋势分析",
            "summary": "提及率走高。",
            "points": [
                {"label": "7月第1周", "sub": "07-01~07-05", "completed": 30, "mention_rate": 60.0, "avg_rank": 2.4, "top3_rate": 50.0},
            ],
        },
        "keyword_analytics": {"rows": [], "highlights": []},
        "competitor_analytics": {"rows": [], "highlights": [], "analysis": {}},
        "competitors": [],
        "platform_codes": ["deepseek"],
    }
    data = render_period_deck_docx_from_bundle(bundle)
    assert data[:2] == b"PK"
    assert len(data) > 8000
