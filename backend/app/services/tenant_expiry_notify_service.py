"""客户服务即将到期：按通知规则扫企业并写站内铃铛。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.services.platform_notify_recipients import (
    TENANT_EXPIRY_DAYS_KEY,
    TENANT_EXPIRY_POSITIONS_KEY,
    parse_notify_position_ids,
)
from app.services.system_config_service import get_runtime_config
from app.services.system_notification_service import (
    resolve_tenant_expiry_notifications,
    upsert_tenant_expiry_notification,
)

logger = logging.getLogger(__name__)


def _short_tenant_name(name: str) -> str:
    text = str(name or "").strip() or "企业"
    for suffix in ("控股集团有限公司", "股份有限公司", "有限责任公司", "有限公司", "集团"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            return text[: -len(suffix)]
    return text


def sync_tenant_expiry_notifications(db: Session, *, today: date | None = None) -> dict[str, Any]:
    """按配置 N 天窗口 upsert；窗口外或已过期的旧通知清掉。职位未勾选则只清理不推送。"""
    today = today or date.today()
    try:
        days = int(get_runtime_config(TENANT_EXPIRY_DAYS_KEY, db=db) or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(0, min(days, 365))
    allowed_positions = parse_notify_position_ids(db=db, config_key=TENANT_EXPIRY_POSITIONS_KEY)

    if days == 0 or not allowed_positions:
        cleared = resolve_tenant_expiry_notifications(db, active_tenant_ids=set())
        return {
            "days": days,
            "positions": len(allowed_positions),
            "upserted": 0,
            "cleared": cleared,
            "skipped": "disabled" if not allowed_positions else "days_zero",
        }

    window_end = today + timedelta(days=days)
    tenants = list(
        db.scalars(
            select(Tenant).where(
                Tenant.deleted.is_(False),
                Tenant.service_end_date.is_not(None),
                Tenant.service_end_date >= today,
                Tenant.service_end_date <= window_end,
            )
        )
    )

    active_ids: set[int] = set()
    upserted = 0
    for tenant in tenants:
        end_date = tenant.service_end_date
        if end_date is None:
            continue
        days_left = (end_date - today).days
        active_ids.add(tenant.id)
        short = _short_tenant_name(tenant.name)
        # 2026-07-31 - 到期铃铛 - 销售靠 payload.owner_user_id 精细过滤
        upsert_tenant_expiry_notification(
            db,
            tenant_id=tenant.id,
            title=f"客户即将到期 · {short}",
            message=f"{tenant.name} 还有 {days_left} 天到期（{end_date.isoformat()}）",
            level="warning",
            payload={
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "owner_user_id": tenant.owner_user_id,
                "days_left": days_left,
                "service_end_date": end_date.isoformat(),
            },
            auto_commit=False,
        )
        upserted += 1

    cleared = resolve_tenant_expiry_notifications(db, active_tenant_ids=active_ids, auto_commit=False)
    db.commit()
    logger.info(
        "tenant_expiry_notify days=%s positions=%s upserted=%s cleared=%s",
        days,
        len(allowed_positions),
        upserted,
        cleared,
    )
    return {
        "days": days,
        "positions": len(allowed_positions),
        "upserted": upserted,
        "cleared": cleared,
    }
