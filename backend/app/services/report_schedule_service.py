"""周期报告自动生成——扫描到期类型并为活跃企业生成已发布报告。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
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

# 2026-08-04 - 结项：到期次日生成；回扫防 Beat 漏跑
COMPLETION_LOOKBACK_DAYS = 7


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


def completion_period_bounds(tenant: Tenant) -> tuple[date, date] | None:
    """结项统计窗 = 合同服务起止；缺任一侧则无法自动结项。"""
    start = tenant.service_start_date
    end = tenant.service_end_date
    if start is None or end is None:
        return None
    if start > end:
        return None
    return start, end


def list_tenants_due_completion(
    db: Session,
    *,
    today: date,
    lookback_days: int = COMPLETION_LOOKBACK_DAYS,
) -> list[Tenant]:
    """服务结束日落在 [today-lookback, today-1]：到期次日及回扫窗口内待结项企业。

    不要求 status=启用（到期停服后仍要出结项）。
    """
    days = max(1, int(lookback_days))
    window_start = today - timedelta(days=days)
    window_end = today - timedelta(days=1)
    if window_end < window_start:
        return []
    return list(
        db.scalars(
            select(Tenant)
            .where(
                Tenant.deleted.is_(False),
                Tenant.service_start_date.is_not(None),
                Tenant.service_end_date.is_not(None),
                Tenant.service_end_date >= window_start,
                Tenant.service_end_date <= window_end,
            )
            .order_by(Tenant.id.asc())
        )
    )


def run_due_completion_reports(
    db: Session,
    *,
    today: date | None = None,
    lookback_days: int = COMPLETION_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """为刚到期（及回扫窗口内）企业生成并发布结项报告。"""
    today = today or date.today()
    tenants = list_tenants_due_completion(db, today=today, lookback_days=lookback_days)
    generated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for tenant in tenants:
        bounds = completion_period_bounds(tenant)
        if bounds is None:
            skipped += 1
            continue
        start, end = bounds
        key = period_key("completion", start, end)
        if report_already_generated(db, tenant_id=tenant.id, report_type="completion", key=key):
            skipped += 1
            continue
        try:
            created = generate_scheduled_report_for_tenant(
                db,
                tenant_id=tenant.id,
                report_type="completion",
                period_start=start,
                period_end=end,
                period_key=key,
                generated_at=datetime.combine(today, time(hour=0, minute=10)),
            )
            if created is None:
                skipped += 1
            else:
                generated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "completion report failed tenant=%s key=%s",
                tenant.id,
                key,
            )
            errors.append(
                {
                    "tenant_id": tenant.id,
                    "report_type": "completion",
                    "period_key": key,
                    "error": str(exc),
                }
            )

    return {
        "anchor": today.isoformat(),
        "due_types": ["completion"],
        "tenant_count": len(tenants),
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
    }


def run_due_scheduled_reports(
    db: Session,
    *,
    anchor: date | None = None,
    report_types: list[str] | None = None,
    include_completion: bool = True,
) -> dict[str, Any]:
    today = anchor or date.today()
    due_types = report_types if report_types is not None else due_scheduled_report_types(today)

    generated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    tenant_ids: list[int] = []

    # 2026-08-04 - 非周一/非 1 号 due_types 为空时仍要跑结项，勿早退
    if due_types:
        tenant_ids = list_active_report_tenant_ids(db)
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

    completion_result: dict[str, Any] | None = None
    if include_completion:
        completion_result = run_due_completion_reports(db, today=today)
        generated += int(completion_result.get("generated") or 0)
        skipped += int(completion_result.get("skipped") or 0)
        errors.extend(list(completion_result.get("errors") or []))
        due_types = list(due_types) + ["completion"]

    return {
        "anchor": today.isoformat(),
        "due_types": due_types,
        "tenant_count": len(tenant_ids),
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "completion": completion_result,
    }
