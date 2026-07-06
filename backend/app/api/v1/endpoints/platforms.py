"""平台管理与预警阈值API。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session, require_platform
from app.core.database import get_db
from app.models.platform import AlertThreshold, GeoPlatform
from app.schemas.common import ApiResponse
from app.core.read_cache import CELERY_MONITOR_CACHE_TTL, celery_monitor_cache_key, get_or_build_json_cache
from app.core.celery_queue_monitor import (
    format_celery_monitor_zh,
    get_queue_monitor_snapshot,
    invalidate_queue_threshold_cache,
    is_business_metric_type,
    metric_label,
)
from app.services.deepseek_balance_service import fetch_deepseek_balance
from app.services.molizhishu_balance_service import fetch_molizhishu_balance
from app.services.molizhishu_platforms import (
    get_platform_catalog_meta,
    get_supported_platform_catalog,
    refresh_platform_catalog,
)
from app.services.geo_platform_seed_service import sync_geo_platforms_from_catalog
from app.services.platform_matrix_service import build_platform_matrix

router = APIRouter(prefix="/platforms")
alert_router = APIRouter(prefix="/alerts")

logger = logging.getLogger(__name__)


# ── 平台管理 ──────────────────────────────────────────────

@router.get("", response_model=ApiResponse[list[dict]])
def list_platforms(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """模型平台列表——名称、图标、访问方式、状态。运营和客户均可查看。"""
    rows = list(
        db.scalars(
            select(GeoPlatform)
            .where(GeoPlatform.deleted.is_(False))
            .order_by(GeoPlatform.sort_order.asc(), GeoPlatform.id.asc())
        )
    )
    return ApiResponse(data=[
        {
            "id": r.id,
            "platform_code": r.platform_code,
            "platform_name": r.platform_name,
            "platform_icon": r.platform_icon,
            "access_type": r.access_type,
            "api_endpoint": r.api_endpoint,
            "status": r.status,
            "sort_order": r.sort_order,
            "description": r.description,
        }
        for r in rows
    ])


@router.post("/sync-catalog", response_model=ApiResponse[dict])
def sync_platform_catalog(
    force_refresh: bool = Query(False),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """从模力官方目录同步 geo_platform 表（幂等 upsert）。"""
    require_platform(current)
    result = sync_geo_platforms_from_catalog(db, force_refresh=force_refresh)
    return ApiResponse(data=result)


@router.get("/matrix", response_model=ApiResponse[dict])
def platform_matrix(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """平台运营端：支持平台目录 + 当日服务可用性探测结果。"""
    try:
        data = build_platform_matrix(db, current)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/molizhishu-balance", response_model=ApiResponse[dict])
def molizhishu_balance(
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    """查询模力指数账户当前余额。"""
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可查看")
    return ApiResponse(data=fetch_molizhishu_balance())


@router.get("/deepseek-balance", response_model=ApiResponse[dict])
def deepseek_balance(
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    """查询 DeepSeek API 账户当前余额。"""
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可查看")
    return ApiResponse(data=fetch_deepseek_balance())


@router.get("/supported", response_model=ApiResponse[dict])
def supported_platforms(
    refresh: bool = False,
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    """从模力指数官方文档同步的支持平台目录。"""
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可查看")
    if refresh:
        refresh_platform_catalog(force=True)
    catalog = get_supported_platform_catalog()
    return ApiResponse(data={
        **get_platform_catalog_meta(),
        "platforms": catalog,
    })


@router.put("/{platform_id}", response_model=ApiResponse[dict])
def update_platform(
    platform_id: int,
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """更新平台配置。"""
    require_platform(current)
    platform = db.scalar(
        select(GeoPlatform).where(GeoPlatform.id == platform_id, GeoPlatform.deleted.is_(False))
    )
    if platform is None:
        raise HTTPException(status_code=404, detail="平台不存在")
    for field in ("platform_name", "platform_icon", "access_type", "api_endpoint", "description", "sort_order"):
        if field in payload:
            setattr(platform, field, payload[field])
    if "status" in payload:
        platform.status = bool(payload["status"])
    db.commit()
    db.refresh(platform)
    return ApiResponse(data={
        "id": platform.id,
        "platform_code": platform.platform_code,
        "platform_name": platform.platform_name,
        "status": platform.status,
    })


# ── 预警阈值 ──────────────────────────────────────────────

@alert_router.get("/thresholds", response_model=ApiResponse[list[dict]])
def list_thresholds(
    tenant_id: int | None = None,
    scope: str = Query("business", pattern="^(business|technical|all)$"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """预警阈值配置列表。scope=business|technical|all。"""
    require_platform(current)
    stmt = select(AlertThreshold).where(AlertThreshold.deleted.is_(False))
    if tenant_id is not None:
        stmt = stmt.where(AlertThreshold.tenant_id == tenant_id)
    else:
        stmt = stmt.where(AlertThreshold.tenant_id.is_(None))
    rows = list(db.scalars(stmt.order_by(AlertThreshold.id.asc())))
    if scope == "business":
        rows = [r for r in rows if is_business_metric_type(r.metric_type)]
    elif scope == "technical":
        rows = [r for r in rows if not is_business_metric_type(r.metric_type)]
    return ApiResponse(data=[
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "metric_type": r.metric_type,
            "metric_label": metric_label(r.metric_type),
            "threshold_name": r.threshold_name,
            "warning_value": r.warning_value,
            "critical_value": r.critical_value,
            "unit": r.unit,
            "enabled": r.enabled,
            "updated_by": r.updated_by,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ])


@alert_router.get("/celery-monitor", response_model=ApiResponse[dict])
def alerts_celery_monitor(
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    """中文版 Celery 队列与 Worker 监控。"""
    require_platform(current)
    try:
        data = get_or_build_json_cache(
            celery_monitor_cache_key(),
            lambda: format_celery_monitor_zh(get_queue_monitor_snapshot()),
            ttl_seconds=CELERY_MONITOR_CACHE_TTL,
        )
    except Exception as exc:
        logger.exception("celery monitor snapshot failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="调度监控暂时不可用，请确认 Celery Worker 与 Redis 已启动",
        ) from exc
    return ApiResponse(data=data)


@alert_router.put("/thresholds/{threshold_id}", response_model=ApiResponse[dict])
def update_threshold(
    threshold_id: int,
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """更新预警阈值。"""
    require_platform(current)
    threshold = db.scalar(
        select(AlertThreshold).where(
            AlertThreshold.id == threshold_id, AlertThreshold.deleted.is_(False)
        )
    )
    if threshold is None:
        raise HTTPException(status_code=404, detail="阈值配置不存在")
    for field in ("threshold_name", "warning_value", "critical_value", "unit", "metric_type"):
        if field in payload:
            setattr(threshold, field, payload[field])
    if "enabled" in payload:
        threshold.enabled = bool(payload["enabled"])
    threshold.updated_by = current.user.display_name or current.identity.identity_name
    db.commit()
    db.refresh(threshold)
    if str(threshold.metric_type or "").startswith("celery_"):
        invalidate_queue_threshold_cache()
    return ApiResponse(data={
        "id": threshold.id,
        "threshold_name": threshold.threshold_name,
        "warning_value": threshold.warning_value,
        "critical_value": threshold.critical_value,
        "enabled": threshold.enabled,
    })
