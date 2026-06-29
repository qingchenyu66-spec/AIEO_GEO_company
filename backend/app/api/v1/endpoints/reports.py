"""报告中心API——报告列表、生成、详情。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc, func as sa_func
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.models.report import GeoReport
from app.models.diagnosis import BrandDiagnosis
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/reports")


def _tenant_scope(current: CurrentSession) -> int | None:
    """返回当前会话可访问的企业ID范围，客户只能看自己的。"""
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="未绑定企业")
        return current.identity.tenant_id
    return None


@router.get("/list", response_model=ApiResponse[list[dict]])
def report_list(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """报告列表——客户看自己的，运营看全部。"""
    tenant_id = _tenant_scope(current)
    stmt = (
        select(GeoReport)
        .where(GeoReport.deleted.is_(False))
        .order_by(desc(GeoReport.id))
    )
    if tenant_id:
        stmt = stmt.where(GeoReport.tenant_id == tenant_id)
    rows = list(db.scalars(stmt))
    return ApiResponse(data=[
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "report_title": r.report_title,
            "report_type": r.report_type,
            "status": r.status,
            "data_summary": r.data_summary,
            "report_url": r.report_url,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ])


@router.post("/generate", response_model=ApiResponse[dict])
def generate_report(
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """生成报告——基于诊断记录+监测数据生成一份新报告。"""
    tenant_id = payload.get("tenant_id")
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="未绑定企业")
        tenant_id = current.identity.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定企业ID")
    # 拉取最新的诊断记录
    diagnosis = db.scalar(
        select(BrandDiagnosis)
        .where(BrandDiagnosis.tenant_id == tenant_id, BrandDiagnosis.deleted.is_(False))
        .order_by(desc(BrandDiagnosis.id))
        .limit(1)
    )
    # 统计该企业的监测子任务数
    task_ids_sub = select(GeoMonitorTask.task_id).where(
        GeoMonitorTask.tenant_id == tenant_id, GeoMonitorTask.deleted.is_(False)
    ).subquery()
    total_subtasks = db.scalar(
        sa_func.count(GeoMonitorSubtask.id)
        .where(GeoMonitorSubtask.task_id.in_(select(task_ids_sub)))
    ) or 0
    report_type = payload.get("report_type", "diagnosis")
    report_title = payload.get(
        "report_title",
        f"品牌监测报告-{diagnosis.diagnosis_title if diagnosis else tenant_id}",
    )
    data_summary = f"基于{total_subtasks}条监测子任务数据生成"
    content = {
        "diagnosis": {
            "health_score": diagnosis.health_score if diagnosis else None,
            "sentiment_summary": diagnosis.sentiment_summary if diagnosis else None,
            "strength_points": diagnosis.strength_points if diagnosis else None,
            "weakness_points": diagnosis.weakness_points if diagnosis else None,
            "recommendation": diagnosis.recommendation if diagnosis else None,
        },
        "monitor_info": {
            "total_subtasks": total_subtasks,
            "generated_at": None,
        },
    }
    report = GeoReport(
        tenant_id=int(tenant_id),
        report_title=report_title,
        report_type=report_type,
        status="published",
        data_summary=data_summary,
        report_content_json=content,
        created_by=current.user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ApiResponse(data={
        "id": report.id,
        "report_title": report.report_title,
        "report_type": report.report_type,
        "status": report.status,
        "data_summary": report.data_summary,
        "created_at": report.created_at.isoformat(),
    })


@router.get("/{report_id}", response_model=ApiResponse[dict])
def report_detail(
    report_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """报告详情。"""
    report = db.scalar(
        select(GeoReport).where(GeoReport.id == report_id, GeoReport.deleted.is_(False))
    )
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    if current.identity.identity_type == "CUSTOMER":
        if report.tenant_id != current.identity.tenant_id:
            raise HTTPException(status_code=403, detail="无权查看")
    return ApiResponse(data={
        "id": report.id,
        "tenant_id": report.tenant_id,
        "report_title": report.report_title,
        "report_type": report.report_type,
        "status": report.status,
        "data_summary": report.data_summary,
        "report_content": report.report_content_json,
        "report_url": report.report_url,
        "created_by": report.created_by,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
    })
