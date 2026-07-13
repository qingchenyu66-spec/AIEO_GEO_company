"""Production smoke: HTML preview + PDF for each template report type."""
from __future__ import annotations

from sqlalchemy import desc, select

from app.core.database import SessionLocal
from app.models.report import GeoReport
from app.models.tenant import Tenant
from app.services.report_export_service import build_report_export, build_report_html_preview
from app.services.report_period_service import HTML_TEMPLATE_REPORT_TYPES
from app.services.report_service import (
    _sanitize_report_content,
    _serialize_report_row,
    _tenant_brand_name,
)


def main() -> int:
    db = SessionLocal()
    results: list[dict] = []
    pdf_ok = False
    try:
        for rtype in sorted(HTML_TEMPLATE_REPORT_TYPES):
            row = db.scalar(
                select(GeoReport)
                .where(
                    GeoReport.deleted.is_(False),
                    GeoReport.report_type == rtype,
                    GeoReport.status == "published",
                )
                .order_by(desc(GeoReport.id))
                .limit(1)
            )
            if row is None:
                results.append({"type": rtype, "status": "skip", "detail": "no published report"})
                continue

            tenant = db.scalar(select(Tenant).where(Tenant.id == row.tenant_id))
            payload = _serialize_report_row(row, tenant.name if tenant else None)
            brand = str((row.report_content_json or {}).get("brand_name") or _tenant_brand_name(db, row.tenant_id))
            payload["report_content"] = _sanitize_report_content(
                row.report_content_json,
                brand_name=brand,
                report_type=row.report_type,
            )
            html = build_report_html_preview(db, payload)
            ok = len(html) > 5000 and "<html" in html.lower()
            results.append(
                {
                    "type": rtype,
                    "id": row.id,
                    "status": "ok" if ok else "fail",
                    "html_bytes": len(html),
                    "title": str(payload.get("report_title") or "")[:40],
                }
            )
            if rtype == "weekly" and ok and not pdf_ok:
                pdf, fname, mime = build_report_export(payload, "pdf", db=db)
                pdf_ok = len(pdf) > 1000 and mime == "application/pdf"
                results.append(
                    {
                        "type": "weekly_pdf",
                        "status": "ok" if pdf_ok else "fail",
                        "pdf_bytes": len(pdf),
                        "filename": fname,
                    }
                )
    finally:
        db.close()

    print("=== REPORT SMOKE TEST ===")
    for item in results:
        print(item)
    failed = [item for item in results if item.get("status") == "fail"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
