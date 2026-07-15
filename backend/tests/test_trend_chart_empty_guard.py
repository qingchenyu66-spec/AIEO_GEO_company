"""空样本时趋势图 JSON 不得导致前端 Math.min(...[]) 炸掉（用坐标默认档兜底）。"""


def test_render_trend_html_all_empty_still_emits_safe_script():
    from app.services.report_period_comparison_service import render_trend_html

    html = render_trend_html(
        {
            "title": "季趋势",
            "unit": "季",
            "summary": "",
            "points": [
                {"key": "2025-Q1", "label": "Q1", "completed": 0, "mention_rate": None, "avg_rank": None, "top3_rate": None},
                {"key": "2025-Q2", "label": "Q2", "completed": 0, "mention_rate": None, "avg_rank": None, "top3_rate": None},
                {"key": "2025-Q3", "label": "Q3", "completed": 0, "mention_rate": None, "avg_rank": None, "top3_rate": None},
                {"key": "2025-Q4", "label": "Q4", "completed": 0, "mention_rate": None, "avg_rank": None, "top3_rate": None},
            ],
        }
    )
    assert "trend-empty-note" in html
    assert "mentionVals.length" in html
    assert '"mention": [null, null, null, null]' in html or '"mention":[null,null,null,null]' in html.replace(" ", "")
