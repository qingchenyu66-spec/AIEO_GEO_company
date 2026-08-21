"""计划外历史 run 不应撑爆进度，也不应挡住正常收官。"""

from __future__ import annotations

from datetime import date, datetime

from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.services.lead_diagnosis_service import (
    _all_slots_completed,
    _completed_planned_run_count,
    _expected_schedule_keys,
)


def test_extra_completed_runs_do_not_block_or_inflate_progress() -> None:
    lead = LeadDiagnosis(
        brand_name="测试",
        diagnosis_date=date(2026, 8, 20),
        schedule_times_json=["09:30", "14:30", "20:30"],
        schedule_days=3,
        platforms_json=["doubao"],
        prompts_json=["q1"],
        status="collecting",
        created_at=datetime(2026, 8, 21, 11, 2, 42),
    )
    expected = sorted(_expected_schedule_keys(lead))
    assert len(expected) == 9

    # 计划外历史场次 + 计划内全完成
    runs = [
        LeadDiagnosisRun(schedule_key="20260820-1430", status="completed"),
        LeadDiagnosisRun(schedule_key="20260820-2030", status="completed"),
        LeadDiagnosisRun(schedule_key="20260821-0930", status="completed"),
    ]
    runs.extend(LeadDiagnosisRun(schedule_key=key, status="completed") for key in expected)
    lead.runs = runs

    assert _completed_planned_run_count(lead) == 9
    assert _all_slots_completed(lead) is True
