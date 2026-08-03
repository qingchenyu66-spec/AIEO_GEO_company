"""批量刷新已发布周期报告（保留 id/period_key，重算正文与预览 HTML）。

用法（生产机）::

  cd /opt/geo/AIEO_GEO/backend
  PYTHONPATH=. .venv/bin/python scripts/refresh_period_reports.py \\
    --weekly-anchor 2026-08-03 --monthly 2026-07
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.report import GeoReport
from app.models.tenant import Tenant
from app.services.report_period_service import bounds_from_period_key, period_bounds, period_key
from app.services.report_service import refresh_scheduled_report_for_tenant


def _resolve_bounds(report_type: str, report: GeoReport) -> tuple[date, date] | None:
    content = dict(report.report_content_json or {})
    start: date | None = None
    end: date | None = None
    for field, target in (("period_start", "start"), ("period_end", "end")):
        raw = content.get(field)
        if not raw:
            continue
        try:
            parsed = date.fromisoformat(str(raw)[:10])
        except ValueError:
            parsed = None
        if target == "start":
            start = parsed
        else:
            end = parsed
    if start is None or end is None:
        return bounds_from_period_key(report_type, str(report.period_key or ""))
    return start, end


def refresh_by_period_keys(
    db,
    *,
    keys: set[str],
    dry_run: bool = False,
) -> dict[str, int | list]:
    rows = list(
        db.scalars(
            select(GeoReport)
            .where(
                GeoReport.deleted.is_(False),
                GeoReport.status == "published",
                GeoReport.period_key.in_(tuple(keys)),
            )
            .order_by(GeoReport.tenant_id.asc(), GeoReport.id.asc())
        )
    )
    refreshed = 0
    skipped = 0
    errors: list[dict] = []
    for report in rows:
        bounds = _resolve_bounds(report.report_type, report)
        if bounds is None:
            skipped += 1
            errors.append({"id": report.id, "period_key": report.period_key, "error": "cannot resolve bounds"})
            continue
        start, end = bounds
        tenant = db.scalar(select(Tenant.name).where(Tenant.id == report.tenant_id))
        label = f"id={report.id} tenant={report.tenant_id} {tenant or '?'} {report.report_type} {report.period_key}"
        if dry_run:
            print(f"DRY {label}")
            refreshed += 1
            continue
        try:
            row = refresh_scheduled_report_for_tenant(
                db,
                report_id=report.id,
                period_start=start,
                period_end=end,
                generated_at=datetime.combine(end, time(hour=20, minute=0)),
            )
            if row is None:
                skipped += 1
                print(f"SKIP {label} (no data)")
            else:
                refreshed += 1
                print(f"OK {label}")
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append({"id": report.id, "period_key": report.period_key, "error": str(exc)})
            print(f"ERR {label} {exc}")
    return {"matched": len(rows), "refreshed": refreshed, "skipped": skipped, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh published periodic reports in-place")
    parser.add_argument("--weekly-anchor", type=str, help="Anchor date YYYY-MM-DD → previous natural week")
    parser.add_argument("--monthly", action="append", help="Month YYYY-MM (repeatable)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    keys: set[str] = set()
    if args.weekly_anchor:
        anchor = date.fromisoformat(args.weekly_anchor)
        start, end = period_bounds("weekly", anchor)
        keys.add(period_key("weekly", start, end))
    for item in args.monthly or []:
        year_text, month_text = item.split("-", 1)
        start = date(int(year_text), int(month_text), 1)
        end = bounds_from_period_key("monthly", f"monthly:{item}")
        if end is None:
            raise SystemExit(f"invalid monthly: {item}")
        start, end = end
        keys.add(period_key("monthly", start, end))
    if not keys:
        raise SystemExit("specify --weekly-anchor and/or --monthly")

    db = SessionLocal()
    try:
        print("period_keys:", sorted(keys))
        result = refresh_by_period_keys(db, keys=keys, dry_run=args.dry_run)
    finally:
        db.close()
    print(
        f"matched={result['matched']} refreshed={result['refreshed']} "
        f"skipped={result['skipped']} errors={len(result['errors'])}"
    )


if __name__ == "__main__":
    main()
