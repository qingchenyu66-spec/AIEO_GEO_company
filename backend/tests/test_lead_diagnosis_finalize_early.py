"""售前诊断提前收官生成报告。"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.lead_diagnosis_config import DEFAULT_LEAD_SCHEDULE_TIMES
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.tenant import Tenant
from app.models.user import User
from app.services.lead_diagnosis_service import (
    ACTIVE_STATUSES,
    finalize_lead_diagnosis_early,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Tenant.__table__, LeadDiagnosis.__table__, LeadDiagnosisRun.__table__],
    )
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def _patch_access(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.require_lead_diagnosis_access",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.ensure_lead_diagnosis_owner_access",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service._sync_lead_run_statuses_from_tasks",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service._task_map",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service._kick_lead_export_pregenerate",
        lambda *a, **k: None,
    )


def test_finalize_lead_diagnosis_early_skips_remaining_and_ready(db_session, monkeypatch) -> None:
    lead = LeadDiagnosis(
        brand_name="提前收官",
        prompts_json=["问题1"],
        competitors_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        schedule_days=3,
        diagnosis_date=date(2026, 8, 10),
        status="collecting",
        created_by_user_id=1,
        created_at=datetime(2026, 8, 10, 8, 0, 0),
    )
    lead.runs = [
        LeadDiagnosisRun(
            schedule_key="20260810-0930",
            schedule_label="2026-08-10 09:30",
            status="completed",
            task_id="task-done",
            prompt_count=1,
            platform_count=1,
        ),
        LeadDiagnosisRun(
            schedule_key="20260810-1430",
            schedule_label="2026-08-10 14:30",
            status="pending",
            prompt_count=1,
            platform_count=1,
        ),
    ]
    db_session.add(lead)
    db_session.commit()

    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", tenant_id=None, position_id=None),
        user=SimpleNamespace(id=1, display_name="运营", username="ops"),
    )
    _patch_access(monkeypatch)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service._load_subtasks_by_task_ids",
        lambda db, task_ids: [
            SimpleNamespace(
                status="completed",
                answer_content="答",
                mention_position=2,
                sentiment="positive",
                task_id="task-done",
                platform="doubao",
                prompt="问题1",
            )
        ],
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.aggregate_lead_diagnosis",
        lambda *a, **k: {"diagnosis": {"health_score": 88}, "kpis": {"health_score": 88}},
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.get_lead_diagnosis",
        lambda db, lead_id, current=None: {
            "id": lead_id,
            "status": db.get(LeadDiagnosis, lead_id).status,
            "health_score": db.get(LeadDiagnosis, lead_id).health_score,
        },
    )

    result = finalize_lead_diagnosis_early(db_session, current, lead.id)
    assert result["status"] == "ready"
    assert lead.status == "ready"
    assert lead.status not in ACTIVE_STATUSES
    assert lead.health_score == 88
    assert lead.diagnosis_result_json is not None
    statuses = {run.schedule_key: run.status for run in lead.runs}
    assert statuses["20260810-0930"] == "completed"
    assert statuses["20260810-1430"] == "skipped"
    assert any(run.status == "skipped" and run.schedule_key != "20260810-1430" for run in lead.runs)

    with pytest.raises(ValueError, match="无法提前收官"):
        finalize_lead_diagnosis_early(db_session, current, lead.id)


def test_finalize_lead_diagnosis_early_requires_completed(db_session, monkeypatch) -> None:
    lead = LeadDiagnosis(
        brand_name="无完成场次",
        prompts_json=["问题1"],
        competitors_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        schedule_days=3,
        diagnosis_date=date(2026, 8, 10),
        status="collecting",
        created_by_user_id=1,
        created_at=datetime(2026, 8, 10, 8, 0, 0),
    )
    lead.runs = [
        LeadDiagnosisRun(
            schedule_key="20260810-0930",
            schedule_label="2026-08-10 09:30",
            status="pending",
            prompt_count=1,
            platform_count=1,
        )
    ]
    db_session.add(lead)
    db_session.commit()
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", tenant_id=None, position_id=None),
        user=SimpleNamespace(id=1, display_name="运营", username="ops"),
    )
    _patch_access(monkeypatch)
    with pytest.raises(ValueError, match="至少需要完成一场"):
        finalize_lead_diagnosis_early(db_session, current, lead.id)
