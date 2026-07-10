"""周期报告自动生成——扫描到期类型并为活跃企业生成已发布报告。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.brand import BrandAsset
from app.models.report import GeoReport
from app.models.tenant import Tenant
from app.services.report_period_service import (
    due_scheduled_report_types,
    period_bounds,
    period_key,
)
from app.services.report_service import generate_scheduled_report_for_tenant

logger = logging.getLogger(__name__)


def list_active_report_tenant_ids(db: Session) -> list[int]:
    """与定时监测一致：启用企业且在服务期内。"""
    today = date.today()
    rows = db.scalars(
        select(BrandAsset.tenant_id)
        .join(Tenant, Tenant.id == BrandAsset.tenant_id)
        .where(
            BrandAsset.deleted.is_(False),
            BrandAsset.status.is_(True),
            Tenant.deleted.is_(False),
            Tenant.status.is_(True),
            or_(Tenant.service_start_date.is_(None), Tenant.service_start_date <= today),
            or_(Tenant.service_end_date.is_(None), Tenant.service_end_date >= today),
        )
        .order_by(BrandAsset.tenant_id.asc())
    )
    return list(dict.fromkeys(rows))


def report_already_generated(db: Session, *, tenant_id: int, report_type: str, key: str) -> bool:
    existing = db.scalar(
        select(GeoReport.id).where(
            GeoReport.tenant_id == tenant_id,
            GeoReport.report_type == report_type,
            GeoReport.period_key == key,
            GeoReport.deleted.is_(False),
        )
    )
    return existing is not None


def run_due_scheduled_reports(
    db: Session,
    *,
    anchor: date | None = None,
    report_types: list[str] | None = None,
) -> dict[str, Any]:
    today = anchor or date.today()
    due_types = report_types or due_scheduled_report_types(today)
    if not due_types:
        return {"anchor": today.isoformat(), "due_types": [], "generated": 0, "skipped": 0, "errors": []}

    tenant_ids = list_active_report_tenant_ids(db)
    generated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for report_type in due_types:
        start, end = period_bounds(report_type, today)
        key = period_key(report_type, start, end)
        for tenant_id in tenant_ids:
            if report_already_generated(db, tenant_id=tenant_id, report_type=report_type, key=key):
                skipped += 1
                continue
            try:
                created = generate_scheduled_report_for_tenant(
                    db,
                    tenant_id=tenant_id,
                    report_type=report_type,
                    period_start=start,
                    period_end=end,
                    period_key=key,
                    generated_at=datetime.combine(today, time(hour=0, minute=5)),
                )
                if created is None:
                    skipped += 1
                else:
                    generated += 1
            except Exception as exc:
                logger.exception(
                    "scheduled report failed tenant=%s type=%s key=%s",
                    tenant_id,
                    report_type,
                    key,
                )
                errors.append(
                    {
                        "tenant_id": tenant_id,
                        "report_type": report_type,
                        "period_key": key,
                        "error": str(exc),
                    }
                )
    return {
        "anchor": today.isoformat(),
        "due_types": due_types,
        "tenant_count": len(tenant_ids),
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
    }
