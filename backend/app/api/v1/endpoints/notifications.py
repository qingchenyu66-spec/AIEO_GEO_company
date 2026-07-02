"""站内系统通知 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.system_notification_service import (
    count_unread_notifications,
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/notifications")


@router.get("", response_model=ApiResponse[list[dict]])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """当前用户可见的站内通知列表。"""
    rows = list_notifications_for_user(
        db,
        user_id=current.user.id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
        unread_only=unread_only,
        limit=limit,
    )
    return ApiResponse(data=rows)


@router.get("/unread-count", response_model=ApiResponse[dict])
def unread_count(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    count = count_unread_notifications(
        db,
        user_id=current.user.id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
    )
    return ApiResponse(data={"count": count})


@router.post("/{notification_id}/read", response_model=ApiResponse[dict])
def read_notification(
    notification_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    ok = mark_notification_read(db, user_id=current.user.id, notification_id=notification_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
    return ApiResponse(data={"id": notification_id, "read": True})


@router.post("/read-all", response_model=ApiResponse[dict])
def read_all_notifications(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    count = mark_all_notifications_read(
        db,
        user_id=current.user.id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
    )
    return ApiResponse(data={"marked": count})
