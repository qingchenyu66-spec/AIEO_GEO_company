"""售前诊断 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest, LeadDiagnosisUpdateRequest
from app.services.approval_service import queue_or_run
from app.services.lead_diagnosis_service import (
    assert_lead_diagnosis_create_allowed,
    build_lead_diagnosis_export,
    create_lead_diagnosis,
    get_lead_diagnosis,
    list_lead_diagnoses,
    refresh_lead_diagnosis_runs,
    require_lead_diagnosis_access,
    submit_due_lead_run,
    update_lead_diagnosis,
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


@router.get("/{lead_id}/export")
def export_record(
    lead_id: int,
    export_format: str = Query(default="pdf", alias="format"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    try:
        require_lead_diagnosis_access(db, current, "can_export")
        content, filename, mime = build_lead_diagnosis_export(db, lead_id, export_format=export_format, current=current)
        return Response(
            content=content,
            media_type=mime,
            headers={"Content-Disposition": content_disposition(filename)},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
