"""Customer report center visibility rules."""

from __future__ import annotations

from app.models.report import GeoReport
from app.services.report_service import (
    CUSTOMER_PORTAL_REPORT_TYPES,
    _customer_can_view_report,
    _skip_empty_scheduled_period,
)


def _report(*, report_type: str, status: str = "published") -> GeoReport:
    return GeoReport(
        id=1,
        tenant_id=10,
        report_title="t",
        report_type=report_type,
        status=status,
    )


def test_customer_portal_excludes_diagnosis() -> None:
    assert "diagnosis" not in CUSTOMER_PORTAL_REPORT_TYPES
    assert "custom" not in CUSTOMER_PORTAL_REPORT_TYPES
    assert "weekly" in CUSTOMER_PORTAL_REPORT_TYPES


def test_customer_can_view_published_weekly_only() -> None:
    assert _customer_can_view_report(_report(report_type="weekly")) is True
    assert _customer_can_view_report(_report(report_type="diagnosis")) is False
    assert _customer_can_view_report(_report(report_type="custom")) is False
    assert _customer_can_view_report(_report(report_type="weekly", status="draft")) is False
    sales_export = _report(report_type="weekly")
    sales_export.created_by = 7
    assert _customer_can_view_report(sales_export) is False


def test_manual_export_keeps_empty_weekly_while_schedule_skips() -> None:
    assert _skip_empty_scheduled_period(completed_count=0, report_type="weekly") is True
    assert _skip_empty_scheduled_period(completed_count=0, report_type="weekly", allow_empty=True) is False
    assert _skip_empty_scheduled_period(completed_count=12, report_type="weekly") is False
    assert _skip_empty_scheduled_period(completed_count=0, report_type="custom") is False


def test_build_report_export_html_requires_db() -> None:
    from app.services.report_export_service import build_report_export

    payload = {"report_type": "weekly", "title": "t", "tenant_id": 1, "period_start": "2026-07-01", "period_end": "2026-07-07"}
    try:
        build_report_export(payload, "html", db=None)
        raised = False
    except ValueError as exc:
        raised = True
        assert "数据库" in str(exc)
    assert raised
