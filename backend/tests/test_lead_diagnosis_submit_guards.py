"""售前诊断提交/语义词校验测试。"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.lead_diagnosis_config import DEFAULT_LEAD_SCHEDULE_TIMES
from app.core.lead_diagnosis_prompts import normalize_lead_prompts
from app.models.lead_diagnosis import LeadDiagnosis
from app.services.lead_diagnosis_service import (
    LEAD_MAX_PARALLEL_SUBMITS,
    _slot_is_future,
    submit_due_lead_run,
)


def test_normalize_lead_prompts_rejects_template() -> None:
    with pytest.raises(ValueError, match="例如"):
        normalize_lead_prompts(["例如：艾迪亚有哪些产品值得推荐？"])
    with pytest.raises(ValueError, match="XXX"):
        normalize_lead_prompts(["XXX在同类品牌里排名怎么样？"])


def test_slot_is_future() -> None:
    now = datetime(2026, 7, 10, 11, 0, 0)
    assert _slot_is_future(date(2026, 7, 10), "14:30", now) is True
    assert _slot_is_future(date(2026, 7, 10), "09:30", now) is False


def test_submit_rejects_future_force_slot() -> None:
    lead = LeadDiagnosis(
        id=5,
        brand_name="艾迪亚",
        prompts_json=["电梯广告公司推荐"],
        competitors_json=[],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        diagnosis_date=date(2026, 7, 10),
        status="collecting",
        created_at=datetime(2026, 7, 10, 10, 0, 0),
        runs=[],
    )
    db = MagicMock()
    db.scalar.return_value = lead
    current = SimpleNamespace(user=SimpleNamespace(id=1))

    with patch("app.services.lead_diagnosis_service.require_lead_diagnosis_access"), patch(
        "app.services.lead_diagnosis_service.ensure_lead_diagnosis_owner_access"
    ), patch("app.services.lead_diagnosis_service._load_lead_diagnosis", return_value=lead), patch(
        "app.services.lead_diagnosis_service._task_map", return_value={}
    ), patch(
        "app.services.lead_diagnosis_service.enumerate_due_lead_runs", return_value=iter([])
    ):
        with pytest.raises(ValueError, match="尚未到点"):
            submit_due_lead_run(
                db,
                current,
                5,
                schedule_key="20260710-1430",
                force=True,
            )


def test_submit_rejects_parallel_limit() -> None:
    lead = LeadDiagnosis(
        id=5,
        brand_name="艾迪亚",
        prompts_json=["电梯广告公司推荐"],
        competitors_json=[],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        diagnosis_date=date(2026, 7, 10),
        status="collecting",
        created_at=datetime(2026, 7, 10, 8, 0, 0),
        runs=[],
    )
    db = MagicMock()
    current = SimpleNamespace(user=SimpleNamespace(id=1))

    with patch("app.services.lead_diagnosis_service.require_lead_diagnosis_access"), patch(
        "app.services.lead_diagnosis_service.ensure_lead_diagnosis_owner_access"
    ), patch("app.services.lead_diagnosis_service._load_lead_diagnosis", return_value=lead), patch(
        "app.services.lead_diagnosis_service._task_map", return_value={}
    ), patch(
        "app.services.lead_diagnosis_service._active_inflight_run_count", return_value=LEAD_MAX_PARALLEL_SUBMITS
    ):
        with pytest.raises(ValueError, match=str(LEAD_MAX_PARALLEL_SUBMITS)):
            submit_due_lead_run(db, current, 5, force=True)
