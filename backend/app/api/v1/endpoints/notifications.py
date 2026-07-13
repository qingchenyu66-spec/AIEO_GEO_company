"""站内系统通知 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.approval_service import can_review_approvals
from app.services.menu_permission_service import has_any_identity_menu_permission, has_identity_menu_permission
from app.services.system_notification_service import (
    count_unread_notifications,
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.services.tenant_scope import is_sales_identity
from sqlalchemy.orm import Session

router = APIRouter(prefix="/notifications")


def _notification_visibility(db: Session, current: CurrentSession) -> dict[str, bool]:
    identity_id = current.identity.id
    can_view_ops_alerts = (
        has_identity_menu_permission(db, identity_id, "platform.alerts", "can_export")
        or has_identity_menu_permission(db, identity_id, "platform.alerts", "can_update")
        or has_identity_menu_permission(db, identity_id, "platform.settings", "can_export")
    )
    if is_sales_identity(db, current.identity):
        can_view_ops_alerts = False
    can_view_customer_reports = False
    if current.identity.identity_type == "CUSTOMER":
        can_view_customer_reports = has_identity_menu_permission(
            db,
            identity_id,
            "customer.reports",
            "can_export",
        )
    return {
        "can_review_approvals": can_review_approvals(db, current),
        "can_view_ops_alerts": can_view_ops_alerts,
        "can_view_snapshot_backfill": has_any_identity_menu_permission(
            db,
            identity_id,
            "platform.snapshot_backfill",
            ("can_export", "can_update"),
        ),
        "can_view_customer_reports": can_view_customer_reports,
    }


@router.get("", response_model=ApiResponse[list[dict]])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """当前用户可见的站内通知列表。"""
    visibility = _notification_visibility(db, current)
    rows = list_notifications_for_user(
        db,
        user_id=current.user.id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
        unread_only=unread_only,
        limit=limit,
        **visibility,
    )
    return ApiResponse(data=rows)


@router.get("/unread-count", response_model=ApiResponse[dict])
def unread_count(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    visibility = _notification_visibility(db, current)
    count = count_unread_notifications(
        db,
        user_id=current.user.id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
        **visibility,
    )
    return ApiResponse(data={"count": count})


@router.post("/{notification_id}/read", response_model=ApiResponse[dict])
def read_notification(
    notification_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    visibility = _notification_visibility(db, current)
    ok = mark_notification_read(
        db,
        user_id=current.user.id,
        notification_id=notification_id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
        **visibility,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
    return ApiResponse(data={"id": notification_id, "read": True})


@router.post("/read-all", response_model=ApiResponse[dict])
def read_all_notifications(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    visibility = _notification_visibility(db, current)
    count = mark_all_notifications_read(
        db,
        user_id=current.user.id,
        identity_type=current.identity.identity_type,
        tenant_id=current.identity.tenant_id,
        **visibility,
    )
    return ApiResponse(data={"marked": count})
