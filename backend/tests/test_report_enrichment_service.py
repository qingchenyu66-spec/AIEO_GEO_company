from app.services.report_enrichment_service import (
    build_competitor_landscape,
    canonical_ranking_name,
    merge_priority_actions,
    merge_prompt_commentaries,
)


def test_canonical_ranking_name_merges_variants() -> None:
    brand = "艾迪亚控股集团有限公司"
    competitors = ["分众传媒"]
    assert canonical_ranking_name("分众传媒(Focus Media)", brand, competitors) == "分众传媒"
    assert canonical_ranking_name("艾迪亚传媒", brand, competitors) == brand


def test_competitor_landscape_orders_by_mention_rate() -> None:
    analytics = [
        {
            "prompt": "p1",
            "sample_count": 10,
            "mention_table": [
                {"name": "儒思HR", "mention_count": 8, "mention_rate": 80.0, "avg_rank": 2.0, "is_brand": True},
                {"name": "北森", "mention_count": 9, "mention_rate": 90.0, "avg_rank": 1.0, "is_competitor": True},
            ],
        }
    ]
    rows = build_competitor_landscape(analytics, brand="儒思HR", competitors=["北森"])
    assert rows[0]["name"] == "北森"
    assert rows[0]["mention_rate"] == 90.0


def test_merge_priority_actions_prefers_ai() -> None:
    rule = [{"priority": "P2", "title": "规则项", "timeline": "90天"}]
    ai = [{"priority": "P0", "title": "AI 行动", "timeline": "30天"}]
    assert merge_priority_actions(rule, ai)[0]["title"] == "AI 行动"


def test_merge_priority_actions_falls_back_to_rule() -> None:
    rule = [{"priority": "P1", "title": "规则项", "timeline": "60天"}]
    assert merge_priority_actions(rule, None) == rule
