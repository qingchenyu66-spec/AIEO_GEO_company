"""售前诊断取消停跑。"""

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
    cancel_lead_diagnosis,
    enumerate_due_lead_runs,
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


def test_cancel_lead_diagnosis_stops_due_enumeration(db_session, monkeypatch) -> None:
    lead = LeadDiagnosis(
        brand_name="取消测试",
        prompts_json=["问题1"],
        competitors_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        schedule_days=3,
        diagnosis_date=date(2026, 8, 4),
        status="collecting",
        created_by_user_id=1,
        created_at=datetime(2026, 8, 4, 8, 0, 0),
    )
    lead.runs = [
        LeadDiagnosisRun(
            schedule_key="20260804-0930",
            schedule_label="2026-08-04 09:30",
            status="submitted",
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
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.require_lead_diagnosis_access",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.ensure_lead_diagnosis_owner_access",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.get_lead_diagnosis",
        lambda db, lead_id, current=None: {"id": lead_id, "status": db.get(LeadDiagnosis, lead_id).status},
    )

    before = list(enumerate_due_lead_runs(db_session, lead_id=lead.id, force=True))
    assert before

    result = cancel_lead_diagnosis(db_session, current, lead.id)
    assert result["status"] == "canceled"
    assert lead.status == "canceled"
    assert lead.status not in ACTIVE_STATUSES
    assert lead.runs[0].status == "skipped"
    assert list(enumerate_due_lead_runs(db_session, lead_id=lead.id, force=True)) == []

    with pytest.raises(ValueError, match="无法再取消"):
        cancel_lead_diagnosis(db_session, current, lead.id)
