"""重新聚合指定售前诊断并写回 diagnosis_result_json。"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.lead_diagnosis import LeadDiagnosis
from app.services.lead_diagnosis_service import (
    _load_subtasks,
    _task_region_map_for_task_ids,
    aggregate_lead_diagnosis,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh lead diagnosis aggregation")
    parser.add_argument("--lead-id", type=int, required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        lead = db.scalar(
            select(LeadDiagnosis)
            .where(LeadDiagnosis.id == args.lead_id, LeadDiagnosis.deleted.is_(False))
            .options(selectinload(LeadDiagnosis.runs))
        )
        if lead is None:
            raise SystemExit(f"lead {args.lead_id} not found")
        subtasks = _load_subtasks(db, lead)
        task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
        result = aggregate_lead_diagnosis(
            lead,
            subtasks,
            task_region_map=_task_region_map_for_task_ids(db, task_ids),
            db=db,
        )
        lead.diagnosis_result_json = result
        lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get(
            "health_score"
        )
        lead.status = "ready"
        db.commit()
        print(
            f"refreshed lead_id={lead.id} brand={lead.brand_name} "
            f"competitors={len(result.get('competitors') or [])} "
            f"prompts={len(result.get('prompt_analytics') or [])}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
