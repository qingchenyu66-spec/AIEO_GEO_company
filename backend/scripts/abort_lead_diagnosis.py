"""中止进行中的售前诊断抓取（本地标记 failed/stopped）。"""

from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.services.lead_diagnosis_service import abort_lead_diagnosis


def main() -> None:
    parser = argparse.ArgumentParser(description="Abort in-flight lead diagnosis runs")
    parser.add_argument("--lead-id", type=int, required=True)
    parser.add_argument("--reason", default="管理员重置：请修正语义词后新建诊断")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        lead = abort_lead_diagnosis(db, args.lead_id, reason=args.reason)
        print(f"aborted lead_id={lead.id} brand={lead.brand_name} status={lead.status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
