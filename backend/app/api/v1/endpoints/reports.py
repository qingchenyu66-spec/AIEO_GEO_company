"""报告中心API——报告列表、生成、详情、导出。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.report_export_service import build_report_export, content_disposition
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
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """生成报告——仅运营端，基于诊断记录与监测快照，初始为草稿。"""
    try:
        return ApiResponse(data=generate_report(db, payload, current))
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=message) from exc


@router.put("/{report_id}", response_model=ApiResponse[dict])
def update_report_endpoint(
    report_id: int,
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """编辑并保存报告草稿——仅运营端。"""
    try:
        return ApiResponse(data=update_report(db, report_id, payload, current))
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc


@router.post("/{report_id}/publish", response_model=ApiResponse[dict])
def publish_report_endpoint(
    report_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """发布报告——客户侧可见。"""
    try:
        return ApiResponse(data=publish_report(db, report_id, current))
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc


@router.get("/{report_id}/export/{export_format}")
def export_report(
    report_id: int,
    export_format: Literal["pdf", "docx"],
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    """导出报告为 PDF 或 Word。"""
    try:
        from app.services.menu_permission_service import require_report_permission

        require_report_permission(db, current, "can_export")
        detail = get_report_detail(db, report_id, current)
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc
    try:
        content, filename, mime = build_report_export(detail, export_format)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"报告导出失败：{exc}") from exc
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
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_403_FORBIDDEN if "无权" in message else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc
