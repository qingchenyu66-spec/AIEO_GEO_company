"""样本口径、诊断批次键、实体严格匹配。"""

from datetime import datetime
from types import SimpleNamespace

from app.services.lead_diagnosis_analytics import (
    _build_date_prompt_matrix,
    _execution_key_from_run,
    names_match,
)
from app.services.monitor_sample_metrics import compute_brand_rank_rates, is_success_status


def test_failed_status_not_in_success_denominator():
    rows = [
        SimpleNamespace(status="completed", mention_position=1),
        SimpleNamespace(status="failed", mention_position=2),
        SimpleNamespace(status="partial_completed", mention_position=None),
    ]
    rates = compute_brand_rank_rates(rows)
    assert rates["success_count"] == 2
    assert rates["mentioned_count"] == 1
    assert rates["mention_rate"] == 50.0
    assert rates["avg_rank"] == 1.0
    assert not is_success_status("failed")


def test_names_match_rejects_two_char_prefix_collision():
    assert names_match("艾迪亚控股", "艾迪亚")
    assert names_match("艾迪亚传媒", "艾迪亚控股集团有限公司")
    assert not names_match("华视传媒", "华铁传媒")
    assert not names_match("北京", "北京巴士传媒")
    assert names_match("儒思HR", "儒思")


def test_execution_key_keeps_minute_from_schedule_key():
    run = SimpleNamespace(
        schedule_key="20260709133000",
        schedule_label="2026-07-09",
        finished_at=None,
        updated_at=None,
    )
    assert _execution_key_from_run(run) == "2026-07-09 13:30"


def test_date_prompt_matrix_aggregates_same_day_rounds_to_daily_mean():
    matrix = _build_date_prompt_matrix(
        [
            {
                "prompt": "电梯广告公司推荐",
                "round_trend": [
                    {"schedule_label": "2026-07-09 09:30", "avg_rank": 1},
                    {"schedule_label": "2026-07-09 13:30", "avg_rank": 2},
                    {"schedule_label": "2026-07-09 16:30", "avg_rank": 3},
                ],
            }
        ]
    )
    assert len(matrix["rows"]) == 1
    assert matrix["rows"][0]["label"] == "2026-07-09"
    assert matrix["rows"][0]["cells"] == [2.0]
