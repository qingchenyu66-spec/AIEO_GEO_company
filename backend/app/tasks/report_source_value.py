"""渠道价值拆解：异步预生成（Playwright 正文 + LLM）。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from app.celery_app import celery_app
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.report_source_value.pregenerate_source_value_task", ignore_result=True)
def pregenerate_source_value_task(
    brand_name: str,
    period_label: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from app.services.source_value_analysis_service import pregenerate_source_value_analyses

    result = pregenerate_source_value_analyses(
        brand_name=brand_name or "",
        period_label=period_label or "",
        sources=list(sources or []),
    )
    logger.info(
        "source_value_pregenerate brand=%s fetched=%s analyzed=%s status=%s",
        brand_name,
        result.get("fetched"),
        result.get("analyzed"),
        result.get("status"),
    )
    return result


@celery_app.task(name="app.tasks.report_source_value.scan_source_value_pregenerate", ignore_result=True)
def scan_source_value_pregenerate(max_tenants: int = 30) -> dict[str, Any]:
    """定时预热：活跃企业近 7 日 TOP 信源入队深抓+解读。"""
    # 2026-07-29 - 周期报导出前预热渠道拆解缓存，避免首次 PDF 仍是规则套话
    from app.services.report_schedule_service import list_active_report_tenant_ids
    from app.services.report_service import build_tenant_monitor_snapshot
    from app.services.source_value_analysis_service import enqueue_source_value_pregenerate

    db = SessionLocal()
    queued = 0
    errors: list[dict[str, Any]] = []
    try:
        tenant_ids = list_active_report_tenant_ids(db)[: max(1, int(max_tenants or 30))]
        end = date.today()
        start = end - timedelta(days=6)
        period_label = f"{start.isoformat()}~{end.isoformat()}"
        for tenant_id in tenant_ids:
            try:
                snapshot = build_tenant_monitor_snapshot(
                    db, tenant_id, start_date=start, end_date=end
                )
                sources = list(snapshot.get("top_sources") or [])
                if not sources:
                    continue
                brand_name = str(snapshot.get("brand_name") or "")
                result = enqueue_source_value_pregenerate(
                    brand_name=brand_name,
                    period_label=period_label,
                    sources=sources,
                )
                if result.get("queued"):
                    queued += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("source_value scan failed tenant=%s", tenant_id)
                errors.append({"tenant_id": tenant_id, "error": str(exc)})
        return {
            "tenant_count": len(tenant_ids),
            "queued": queued,
            "errors": errors,
            "period_label": period_label,
        }
    finally:
        db.close()
