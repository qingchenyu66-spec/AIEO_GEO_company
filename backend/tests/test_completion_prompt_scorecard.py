# -*- coding: utf-8 -*-
"""结项词级成绩 / 风险 / 初峰末 / 建议骨架。"""

from app.services.report_completion_context_service import (
    build_lifecycle_milestones,
    build_next_actions,
    build_prompt_scorecard,
    classify_prompt_risks,
)


def test_prompt_scorecard_and_risks() -> None:
    candidates = []
    for _ in range(10):
        candidates.append({"prompt": "稳词A", "brand_rank": 1})
    for _ in range(10):
        candidates.append({"prompt": "差词B", "brand_rank": None})
    for i in range(8):
        candidates.append({"prompt": "差词B", "brand_rank": 5 if i < 2 else None})
    for _ in range(3):
        candidates.append({"prompt": "样本少C", "brand_rank": 2})

    scorecard = build_prompt_scorecard(candidates)
    by_prompt = {r["prompt"]: r for r in scorecard}
    assert by_prompt["稳词A"]["mention_rate"] == 100.0
    assert by_prompt["稳词A"]["avg_rank"] == 1.0
    assert by_prompt["差词B"]["completed"] == 18
    assert by_prompt["差词B"]["mention_rate"] < 40.0

    risks = {r["prompt"]: r for r in classify_prompt_risks(scorecard, min_samples=5)}
    assert risks["稳词A"]["risk_level"] == "P2"
    assert risks["差词B"]["risk_level"] == "P0"
    assert risks["样本少C"]["risk_level"] == "样本不足"

    actions = build_next_actions(list(risks.values()))
    assert any("稳词A" in x for x in actions["consolidate"])
    assert any("差词B" in x for x in actions["attack"])


def test_lifecycle_milestones_peak() -> None:
    trend = [
        {"date": "2026-06-01", "label": "06-01", "mention_rate": 20.0, "completed": 10},
        {"date": "2026-06-15", "label": "06-15", "mention_rate": 80.0, "completed": 12},
        {"date": "2026-06-30", "label": "06-30", "mention_rate": 50.0, "completed": 11},
    ]
    life = build_lifecycle_milestones(
        trend,
        {
            "available": True,
            "early_label": "06-01~06-07",
            "late_label": "06-24~06-30",
            "overall": {
                "early": {"mention_rate": 22.0},
                "late": {"mention_rate": 48.0},
            },
        },
    )
    assert life["available"] is True
    assert life["peak"]["date"] == "2026-06-15"
    assert life["peak"]["mention_rate"] == 80.0
    assert life["initial"]["mention_rate"] == 20.0
    assert life["final"]["mention_rate"] == 50.0
