"""2026-08-28: revert to old schedule for rest of day; --apply-new at 2026-08-29 00:00."""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.brand import BrandAsset
from app.models.tenant import Tenant
from app.services.schedule_history import TENANT_SCHEDULE_HISTORY as SCHEDULES


def _apply(mode: str) -> int:
    if mode not in {"old", "new"}:
        raise ValueError(mode)
    db = SessionLocal()
    updated = 0
    try:
        for tenant_id, slots in SCHEDULES.items():
            tenant = db.get(Tenant, tenant_id)
            if tenant is None or tenant.deleted or not tenant.status:
                continue
            asset = db.scalar(
                select(BrandAsset).where(
                    BrandAsset.tenant_id == tenant_id,
                    BrandAsset.deleted.is_(False),
                )
            )
            if asset is None:
                continue
            times = list(slots[mode])
            asset.schedule_type = "daily_times"
            asset.schedule_frequency = len(times)
            asset.schedule_times_json = times
            updated += 1
            print(f"tenant={tenant_id} {tenant.name} -> {'、'.join(times)}")
        if updated:
            db.commit()
        print(f"APPLY_{mode.upper()}_OK count={updated}")
        return updated
    finally:
        db.close()


def main() -> int:
    if "--apply-old" in sys.argv:
        _apply("old")
        return 0
    if "--apply-new" in sys.argv:
        _apply("new")
        return 0
    print("usage: --apply-old | --apply-new")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
