"""系统公告 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.announcement import AnnouncementUpsertRequest
from app.schemas.common import ApiResponse
from app.services import announcement_media_service, announcement_service

router = APIRouter(prefix="/announcements", tags=["Announcements"])


@router.get("/pending", response_model=ApiResponse[dict | None])
def get_pending_announcement(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict | None]:
    data = announcement_service.next_pending_announcement(db, current)
    return ApiResponse(data=data)


@router.post("/{announcement_id}/ack", response_model=ApiResponse[dict])
def ack_announcement(
    announcement_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = announcement_service.ack_announcement(db, current, announcement_id)
        db.commit()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/media/{media_id}")
def download_announcement_media(
    media_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    del current  # 登录即可拉取（uuid 文件名 + 需鉴权）
    try:
        record, path = announcement_media_service.resolve_media_file(db, media_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    media_type = announcement_media_service.media_content_type(record)
    return FileResponse(
        path,
        media_type=media_type,
        filename=record.original_name,
        content_disposition_type="inline" if record.kind == "image" else "attachment",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/media", response_model=ApiResponse[dict])
async def upload_announcement_media(
    kind: str = Form(default="auto"),
    file: UploadFile = File(...),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = await announcement_media_service.save_announcement_media(db, current, file, kind=kind)
        db.commit()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/list", response_model=ApiResponse[list])
def list_announcements(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list]:
    try:
        data = announcement_service.list_announcements_admin(db, current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/{announcement_id}", response_model=ApiResponse[dict])
def get_announcement(
    announcement_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = announcement_service.get_announcement_admin(db, current, announcement_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/", response_model=ApiResponse[dict])
def create_announcement(
    payload: AnnouncementUpsertRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = announcement_service.create_announcement(db, current, payload)
        db.commit()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.put("/{announcement_id}", response_model=ApiResponse[dict])
def update_announcement(
    announcement_id: int,
    payload: AnnouncementUpsertRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = announcement_service.update_announcement(db, current, announcement_id, payload)
        db.commit()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/{announcement_id}/offline", response_model=ApiResponse[dict])
def offline_announcement(
    announcement_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = announcement_service.take_offline_announcement(db, current, announcement_id)
        db.commit()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.delete("/{announcement_id}", response_model=ApiResponse[dict])
def delete_announcement(
    announcement_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        announcement_service.delete_announcement(db, current, announcement_id)
        db.commit()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"ok": True})
