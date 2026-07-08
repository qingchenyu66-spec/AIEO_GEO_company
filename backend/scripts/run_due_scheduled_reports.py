"""手动触发周期报告生成（补跑或测试）。"""

from __future__ import annotations

import argparse
from datetime import date

from app.core.database import SessionLocal
from app.services.report_period_service import due_scheduled_report_types
from app.services.report_schedule_service import run_due_scheduled_reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate due scheduled GEO reports")
    parser.add_argument("--at", type=str, help="Anchor date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--type",
        action="append",
        dest="types",
        choices=["weekly", "monthly", "quarterly", "annual"],
        help="Force report type(s); default: types due on anchor date",
    )
    args = parser.parse_args()
    anchor = date.fromisoformat(args.at) if args.at else date.today()
    report_types = args.types or due_scheduled_report_types(anchor)

    db = SessionLocal()
    try:
        result = run_due_scheduled_reports(db, anchor=anchor, report_types=report_types or None)
    finally:
        db.close()

    print(f"anchor={result['anchor']} due_types={result['due_types']}")
    print(f"generated={result['generated']} skipped={result['skipped']} errors={len(result['errors'])}")
    for item in result.get("errors") or []:
        print("ERROR", item)


if __name__ == "__main__":
    main()
