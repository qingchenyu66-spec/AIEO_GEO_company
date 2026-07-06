"""品牌诊断API端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session, require_platform
from app.api.http_errors import raise_read_endpoint_error
from app.core.database import get_db
from app.models.diagnosis import BrandDiagnosis
from app.schemas.common import ApiResponse
from app.services.tenant_scope import (
    guard_tenant_resource_access,
    resolve_and_guard_tenant_id,
    sales_owned_tenant_ids,
)

router = APIRouter(prefix="/diagnosis")

_LIST_LIMIT = 200


@router.get("/records", response_model=ApiResponse[list[dict]])
def list_diagnosis(
    tenant_id: int | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """品牌诊断列表。客户看自己的，运营看全部。"""
    stmt = (
        select(BrandDiagnosis)
        .where(BrandDiagnosis.deleted.is_(False))
        .order_by(BrandDiagnosis.id.desc())
        .limit(_LIST_LIMIT)
    )
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            return ApiResponse(data=[])
        stmt = stmt.where(BrandDiagnosis.tenant_id == current.identity.tenant_id)
    else:
        owned = sales_owned_tenant_ids(db, current)
        if owned is not None:
            if not owned:
                return ApiResponse(data=[])
            stmt = stmt.where(BrandDiagnosis.tenant_id.in_(owned))
        elif tenant_id:
            try:
                resolved = resolve_and_guard_tenant_id(db, current, tenant_id)
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            stmt = stmt.where(BrandDiagnosis.tenant_id == resolved)
    rows = list(db.scalars(stmt))
    return ApiResponse(data=[
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "diagnosis_title": r.diagnosis_title,
            "health_score": r.health_score,
            "sentiment_summary": r.sentiment_summary,
            "strength_points": r.strength_points,
            "weakness_points": r.weakness_points,
            "recommendation": r.recommendation,
            "diagnosis_platforms": r.diagnosis_platforms_json,
            "reference_count": r.reference_count,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ])


@router.post("/records", response_model=ApiResponse[dict])
def create_diagnosis(
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """运营创建品牌诊断。"""
    require_platform(current)
    raw_tenant_id = payload.get("tenant_id", current.identity.tenant_id)
    if raw_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定企业")
    try:
        tenant_id = resolve_and_guard_tenant_id(db, current, int(raw_tenant_id))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record = BrandDiagnosis(
        tenant_id=tenant_id,
        created_by_user_id=current.user.id,
        diagnosis_title=payload.get("diagnosis_title", "品牌诊断"),
        health_score=payload.get("health_score", 80),
        sentiment_summary=payload.get("sentiment_summary"),
        strength_points=payload.get("strength_points"),
        weakness_points=payload.get("weakness_points"),
        recommendation=payload.get("recommendation"),
        diagnosis_platforms_json=payload.get("diagnosis_platforms", ["doubao_mobile", "deepseek"]),
        diagnosis_keywords_json=payload.get("diagnosis_keywords", []),
        reference_count=payload.get("reference_count", 0),
        monitor_data_summary=payload.get("monitor_data_summary"),
        status="published",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ApiResponse(data={"id": record.id, "diagnosis_title": record.diagnosis_title})


@router.get("/records/{record_id}", response_model=ApiResponse[dict])
def get_diagnosis_detail(
    record_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """获取单条诊断详情。"""
    record = db.scalar(select(BrandDiagnosis).where(BrandDiagnosis.id == record_id, BrandDiagnosis.deleted.is_(False)))
    if record is None:
        raise HTTPException(status_code=404, detail="诊断记录不存在")
    if current.identity.identity_type == "CUSTOMER":
        if record.tenant_id != current.identity.tenant_id:
            raise HTTPException(status_code=403, detail="无权查看")
    else:
        try:
            guard_tenant_resource_access(db, current, record.tenant_id)
        except Exception as exc:
            raise_read_endpoint_error(exc, context="diagnosis.detail")
    return ApiResponse(data={
        "id": record.id,
        "tenant_id": record.tenant_id,
        "diagnosis_title": record.diagnosis_title,
        "health_score": record.health_score,
        "sentiment_summary": record.sentiment_summary,
        "strength_points": record.strength_points,
        "weakness_points": record.weakness_points,
        "recommendation": record.recommendation,
        "diagnosis_platforms": record.diagnosis_platforms_json,
        "diagnosis_keywords": record.diagnosis_keywords_json,
        "reference_count": record.reference_count,
        "monitor_data_summary": record.monitor_data_summary,
        "report_url": record.report_url,
        "status": record.status,
        "created_at": record.created_at.isoformat(),
    })
