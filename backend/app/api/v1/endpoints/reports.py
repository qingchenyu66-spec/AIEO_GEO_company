"""报告中心API——报告列表、生成、详情、导出。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.approval_service import queue_or_run
from app.services.operation_log_service import write_business_audit
from app.services.report_export_service import (
    build_report_export,
    content_disposition,
    read_or_build_report_html_preview,
)
from app.services.report_service import generate_report, get_report_detail, list_reports, publish_report, update_report

router = APIRouter(prefix="/reports")


@router.get("/list", response_model=ApiResponse[list[dict]])
def report_list(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """报告列表——客户看自己的，运营看全部。"""
    if current.identity.identity_type == "CUSTOMER" and current.identity.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="未绑定企业")
    return ApiResponse(data=list_reports(db, current))


@router.post("/generate", response_model=ApiResponse[dict])
def generate_report_endpoint(
    payload: dict,
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """生成品牌诊断报告——仅运营端手动触发，生成即为可用（无草稿）。周期报告由 Celery 自动生成并发布。"""
    tenant_id = payload.get("tenant_id")

    def _execute():
        data = generate_report(db, payload, current)
        write_business_audit(
            db,
            current,
            "报告生成",
            f"生成报告：{data.get('report_title') or data.get('title') or '未命名'}",
            request=request,
            target_module="报告中心",
            target_id=data.get("id"),
            tenant_id=data.get("tenant_id"),
        )
        db.commit()
        return data

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="reports.generate",
            module="report",
            action="create",
            summary=f"生成分析报告：{payload.get('report_title') or payload.get('title') or '未命名'}",
            payload={"body": payload},
            tenant_id=int(tenant_id) if tenant_id is not None else None,
            executor=_execute,
        )
    except Exception as exc:
        raise_write_endpoint_error(exc, context="reports.generate")
    return ApiResponse(data=result)


@router.put("/{report_id}", response_model=ApiResponse[dict])
def update_report_endpoint(
    report_id: int,
    payload: dict,
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """编辑报告内容——仅运营端。"""
    def _execute():
        data = update_report(db, report_id, payload, current)
        write_business_audit(
            db,
            current,
            "报告编辑",
            f"更新报告：{data.get('report_title') or data.get('title') or report_id}",
            request=request,
            target_module="报告中心",
            target_id=report_id,
            tenant_id=data.get("tenant_id"),
            risk_level="关注",
        )
        db.commit()
        return data

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="reports.update",
            module="report",
            action="update",
            summary=f"编辑分析报告 #{report_id}",
            payload={"body": payload, "report_id": report_id},
            target_id=report_id,
            tenant_id=payload.get("tenant_id"),
            executor=_execute,
        )
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="reports.update")
    return ApiResponse(data=result)


@router.post("/{report_id}/publish", response_model=ApiResponse[dict])
def publish_report_endpoint(
    report_id: int,
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """发布报告——客户侧可见。"""
    def _execute():
        data = publish_report(db, report_id, current)
        write_business_audit(
            db,
            current,
            "报告发布",
            f"发布报告：{data.get('report_title') or data.get('title') or report_id}",
            request=request,
            target_module="报告中心",
            target_id=report_id,
            tenant_id=data.get("tenant_id"),
            risk_level="关注",
        )
        db.commit()
        return data

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="reports.publish",
            module="report",
            action="publish",
            summary=f"发布分析报告 #{report_id}",
            payload={"report_id": report_id},
            target_id=report_id,
            executor=_execute,
        )
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="reports.publish")
    return ApiResponse(data=result)


@router.get("/{report_id}/preview/html")
def preview_report_html(
    report_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """周期/年报/诊断 HTML 模板预览（与导出 PDF 同源）。"""
    try:
        from app.services.menu_permission_service import require_report_permission

        require_report_permission(db, current, "can_export")
        detail = get_report_detail(db, report_id, current)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="reports.preview")

    report_type = str(detail.get("report_type") or "")
    from app.services.report_period_service import HTML_TEMPLATE_REPORT_TYPES

    if report_type not in HTML_TEMPLATE_REPORT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该报告类型暂不支持 HTML 模板预览")

    try:
        html = read_or_build_report_html_preview(db, detail)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="报告预览生成失败") from exc

    return HTMLResponse(content=html)


@router.post("/{report_id}/export-jobs/{export_format}", response_model=ApiResponse[dict])
def create_report_export_job(
    report_id: int,
    export_format: Literal["pdf", "docx", "html"],
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """异步导出报告：立即返回 job_id。"""
    from app.services.menu_permission_service import require_report_permission
    from app.services.report_export_job_service import start_export_job

    try:
        require_report_permission(db, current, "can_export")
        get_report_detail(db, report_id, current)
        job = start_export_job(
            kind="report",
            ref_id=report_id,
            export_format=export_format,
            owner_user_id=current.user.id,
        )
        return ApiResponse(data=job)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="reports.export_job_create")


@router.get("/export-jobs/{job_id}", response_model=ApiResponse[dict])
def get_report_export_job(
    job_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    from app.services.menu_permission_service import require_report_permission
    from app.services.report_export_job_service import get_export_job

    try:
        require_report_permission(db, current, "can_export")
    except Exception as exc:
        raise_read_endpoint_error(exc, context="reports.export_job_status")
    job = get_export_job(job_id)
    if not job or job.get("kind") != "report":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出任务不存在")
    return ApiResponse(data=job)


@router.get("/export-jobs/{job_id}/download")
def download_report_export_job(
    job_id: str,
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    from app.services.menu_permission_service import require_report_permission
    from app.services.report_export_job_service import export_job_file_path, get_export_job

    try:
        require_report_permission(db, current, "can_export")
        job = get_export_job(job_id)
        if not job or job.get("kind") != "report":
            raise FileNotFoundError("导出任务不存在")
        detail = get_report_detail(db, int(job["ref_id"]), current)
        path, filename, mime = export_job_file_path(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_read_endpoint_error(exc, context="reports.export_job_download")
    write_business_audit(
        db,
        current,
        "报告导出",
        f"异步导出 {str(job.get('format') or '').upper()}：{detail.get('report_title') or job.get('ref_id')}",
        request=request,
        target_module="报告中心",
        target_id=int(job["ref_id"]),
        tenant_id=detail.get("tenant_id"),
        risk_level="关注",
    )
    db.commit()
    return FileResponse(
        path,
        media_type=mime,
        filename=filename,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/{report_id}/export/{export_format}")
def export_report(
    report_id: int,
    export_format: Literal["pdf", "docx", "html"],
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    """导出报告为 PDF、Word 或 HTML（周期/诊断模板）。"""
    try:
        from app.services.menu_permission_service import require_report_permission

        require_report_permission(db, current, "can_export")
        detail = get_report_detail(db, report_id, current)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="reports.export")
    try:
        content, filename, mime = build_report_export(detail, export_format, db=db)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="报告导出失败，请稍后重试") from exc
    write_business_audit(
        db,
        current,
        "报告导出",
        f"导出 {export_format.upper()}：{detail.get('report_title') or report_id}",
        request=request,
        target_module="报告中心",
        target_id=report_id,
        tenant_id=detail.get("tenant_id"),
        risk_level="关注",
    )
    db.commit()
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/{report_id}", response_model=ApiResponse[dict])
def report_detail(
    report_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """报告详情。"""
    try:
        return ApiResponse(data=get_report_detail(db, report_id, current))
    except Exception as exc:
        raise_read_endpoint_error(exc, context="reports.detail")
