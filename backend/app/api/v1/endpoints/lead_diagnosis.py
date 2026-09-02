"""售前诊断 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest, LeadDiagnosisUpdateRequest, LeadDiagnosisConfigReviseRequest
from app.services.approval_service import queue_or_run
from app.services.lead_diagnosis_service import (
    assert_lead_diagnosis_create_allowed,
    build_lead_diagnosis_export,
    build_lead_diagnosis_preview_html,
    cancel_lead_diagnosis,
    create_lead_diagnosis,
    finalize_lead_diagnosis_early,
    get_lead_diagnosis,
    list_lead_diagnoses,
    refresh_lead_diagnosis_runs,
    require_lead_diagnosis_access,
    sanitize_lead_region_codes_for_grants,
    submit_due_lead_run,
    update_lead_diagnosis,
    revise_lead_diagnosis_config,
)
from app.services.report_export_service import content_disposition

router = APIRouter(prefix="/lead-diagnosis")


@router.get("/list", response_model=ApiResponse[list[dict]])
def list_records(
    keyword: str | None = None,
    status: str | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    try:
        return ApiResponse(data=list_lead_diagnoses(db, current, keyword=keyword, status=status))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("", response_model=ApiResponse[dict])
def create_record(
    payload: LeadDiagnosisCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        assert_lead_diagnosis_create_allowed(db, current, payload.brand_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 2026-08-11 - 无企业地区编辑权仍可选诊断地区 - 入队前清空，避免审批 diff 假变更
    payload = payload.model_copy(
        update={"region_codes": sanitize_lead_region_codes_for_grants(db, current, payload.region_codes)},
    )

    def _execute():
        return create_lead_diagnosis(db, current, payload)

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="lead_diagnosis.create",
            module="lead_diagnosis",
            action="create",
            summary=f"新建售前诊断：{payload.brand_name or '未命名'}",
            payload={"body": payload.model_dump(mode="json")},
            executor=_execute,
        )
        return ApiResponse(data=result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{lead_id}", response_model=ApiResponse[dict])
def get_record(
    lead_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        require_lead_diagnosis_access(db, current, "can_export")
        return ApiResponse(data=get_lead_diagnosis(db, lead_id, current=current))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{lead_id}", response_model=ApiResponse[dict])
def update_record(
    lead_id: int,
    payload: LeadDiagnosisUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    def _execute():
        return update_lead_diagnosis(db, current, lead_id, payload)

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="lead_diagnosis.update",
            module="lead_diagnosis",
            action="update",
            summary=f"修改售前诊断 #{lead_id}",
            payload={"body": payload.model_dump(mode="json"), "lead_id": lead_id},
            target_id=lead_id,
            executor=_execute,
        )
        return ApiResponse(data=result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{lead_id}/revise-config", response_model=ApiResponse[dict])
def revise_config_record(
    lead_id: int,
    payload: LeadDiagnosisConfigReviseRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """运营/管理员修改任务配置（不含检测问法）；后续抓取按新配置执行。"""
    try:
        return ApiResponse(data=revise_lead_diagnosis_config(db, current, lead_id, payload))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{lead_id}/cancel", response_model=ApiResponse[dict])
def cancel_record(
    lead_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """取消进行中的诊断任务，后续场次不再抓取。"""
    try:
        return ApiResponse(data=cancel_lead_diagnosis(db, current, lead_id))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{lead_id}/finalize-early", response_model=ApiResponse[dict])
def finalize_early_record(
    lead_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """提前收官：跳过剩余场次，用已完成数据生成报告。"""
    try:
        return ApiResponse(data=finalize_lead_diagnosis_early(db, current, lead_id))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{lead_id}/submit-run", response_model=ApiResponse[dict])
def submit_run(
    lead_id: int,
    schedule_key: str | None = None,
    force: bool = Query(default=False),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    def _execute():
        return submit_due_lead_run(db, current, lead_id, schedule_key=schedule_key, force=force)

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="lead_diagnosis.submit_run",
            module="lead_diagnosis",
            action="submit",
            summary=f"提交售前诊断执行 #{lead_id}",
            payload={"lead_id": lead_id, "schedule_key": schedule_key, "force": force},
            target_id=lead_id,
            executor=_execute,
        )
        return ApiResponse(data=result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{lead_id}/refresh", response_model=ApiResponse[dict])
def refresh_record(
    lead_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        require_lead_diagnosis_access(db, current, "can_export")
        return ApiResponse(data=refresh_lead_diagnosis_runs(db, lead_id, current=current))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{lead_id}/preview/html")
def preview_lead_diagnosis_html(
    lead_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """售前诊断驾驶舱 HTML 预览（与下载 HTML 同源）。"""
    try:
        require_lead_diagnosis_access(db, current, "can_export")
        html = build_lead_diagnosis_preview_html(db, lead_id, current=current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="诊断预览生成失败") from exc
    return HTMLResponse(content=html)


@router.post("/{lead_id}/export-jobs", response_model=ApiResponse[dict])
def create_export_job(
    lead_id: int,
    export_format: str = Query(default="html", alias="format"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """异步导出：立即返回 job_id，前端轮询后再下载。"""
    from app.services.report_export_job_service import start_export_job

    try:
        require_lead_diagnosis_access(db, current, "can_export")
        # 校验可读且已完成
        detail = get_lead_diagnosis(db, lead_id, current=current)
        if detail.get("status") != "ready":
            raise ValueError("诊断尚未完成，暂无法导出")
        fmt = (export_format or "html").lower()
        # 2026-08-12 - 诊断改驾驶舱 - 导出仅开放 html（pdf/docx 在 build_report_export 也会拦）
        if fmt not in {"html"}:
            raise ValueError("诊断报告暂仅支持 HTML 下载")
        job = start_export_job(
            kind="lead_diagnosis",
            ref_id=lead_id,
            export_format=fmt,  # type: ignore[arg-type]
            owner_user_id=current.user.id,
        )
        return ApiResponse(data=job)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/export-jobs/{job_id}", response_model=ApiResponse[dict])
def get_export_job_status(
    job_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    from app.services.report_export_job_service import get_export_job

    try:
        require_lead_diagnosis_access(db, current, "can_export")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    job = get_export_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出任务不存在")
    if job.get("kind") != "lead_diagnosis":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出任务不存在")
    return ApiResponse(data=job)


@router.get("/export-jobs/{job_id}/download")
def download_export_job(
    job_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    from app.services.report_export_job_service import export_job_file_path, get_export_job

    try:
        require_lead_diagnosis_access(db, current, "can_export")
        job = get_export_job(job_id)
        if not job or job.get("kind") != "lead_diagnosis":
            raise FileNotFoundError("导出任务不存在")
        get_lead_diagnosis(db, int(job["ref_id"]), current=current)
        path, filename, mime = export_job_file_path(job_id)
        return FileResponse(
            path,
            media_type=mime,
            filename=filename,
            headers={"Content-Disposition": content_disposition(filename)},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{lead_id}/export")
def export_record(
    lead_id: int,
    export_format: str = Query(default="html", alias="format"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    try:
        require_lead_diagnosis_access(db, current, "can_export")
        # 2026-08-24 - 与 export-jobs 一致，直连导出仅 html
        fmt = (export_format or "html").lower()
        if fmt != "html":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="售前诊断仅支持 HTML 导出")
        content, filename, mime = build_lead_diagnosis_export(db, lead_id, export_format=fmt, current=current)
        return Response(
            content=content,
            media_type=mime,
            headers={"Content-Disposition": content_disposition(filename)},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
