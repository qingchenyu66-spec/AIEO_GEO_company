"""生产一次性：按现有日统计键全量重建 geo_monitor_daily_stat，消化脏 KPI。

用法（生产机）:
  cd /opt/geo/AIEO_GEO/backend && source .venv/bin/activate
  PYTHONPATH=. python scripts/rebuild_all_daily_stats.py
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.read_cache import invalidate_dashboard_caches
from app.models.monitor import GeoMonitorDailyStat
from app.models.tenant import Tenant
from app.services.monitor_stats_service import _rebuild_daily_stat_for_platform_day

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rebuild_daily_stats")


def main() -> None:
    db = SessionLocal()
    try:
        tenant_ids = list(
            db.scalars(select(Tenant.id).where(Tenant.deleted.is_(False)).order_by(Tenant.id.asc()))
        )
        keys = list(
            db.execute(
                select(
                    GeoMonitorDailyStat.tenant_id,
                    GeoMonitorDailyStat.stat_date,
                    GeoMonitorDailyStat.platform,
                ).order_by(
                    GeoMonitorDailyStat.tenant_id.asc(),
                    GeoMonitorDailyStat.stat_date.asc(),
                    GeoMonitorDailyStat.platform.asc(),
                )
            ).all()
        )
        logger.info("tenants=%s daily_stat_keys=%s", len(tenant_ids), len(keys))
        done = 0
        for tenant_id, stat_date, platform in keys:
            _rebuild_daily_stat_for_platform_day(
                db,
                tenant_id=int(tenant_id),
                stat_date=stat_date,
                platform=str(platform),
            )
            done += 1
            if done % 50 == 0:
                db.commit()
                logger.info("progress %s/%s", done, len(keys))
        db.commit()
        for tid in tenant_ids:
            invalidate_dashboard_caches(int(tid), bust_overview=False)
        logger.info("DONE rebuilt=%s tenants_cache_busted=%s", done, len(tenant_ids))
    except Exception:
        db.rollback()
        logger.exception("rebuild failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
