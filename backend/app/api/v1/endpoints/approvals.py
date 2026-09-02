"""操作审批 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.approval_service import (
    approve_and_execute,
    can_review_approvals,
    count_pending_approvals,
    get_approval,
    list_approvals,
    reject_approval,
    resubmit_approval,
    revise_lead_diagnosis_create_approval,
)

router = APIRouter(prefix="/approvals")


@router.get("", response_model=ApiResponse[list[dict]])
def approval_list(
    approval_status: str | None = Query(default=None, alias="status"),
    mine_only: bool = Query(default=False),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    try:
        rows = list_approvals(db, current, status=approval_status, mine_only=mine_only)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise_read_endpoint_error(exc, context="approvals.list")
    return ApiResponse(data=rows)


@router.get("/pending-count", response_model=ApiResponse[dict])
def approval_pending_count(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        count = count_pending_approvals(db, current)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="approvals.pending_count")
    return ApiResponse(data={"count": count})


@router.get("/{approval_id}", response_model=ApiResponse[dict])
def approval_detail(
    approval_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        from app.services.approval_service import approval_to_dict

        record = get_approval(db, current, approval_id)
        return ApiResponse(data=approval_to_dict(db, record))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_read_endpoint_error(exc, context="approvals.detail")


@router.post("/{approval_id}/revise-lead-diagnosis", response_model=ApiResponse[dict])
def approval_revise_lead_diagnosis(
    approval_id: int,
    payload: dict | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """保存售前诊断新建审批的「审批采用」内容（不含品牌名）。"""
    if not can_review_approvals(db, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权审批")
    try:
        data = revise_lead_diagnosis_create_approval(db, current, approval_id, payload or {})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="approvals.revise_lead_diagnosis")
    return ApiResponse(data=data)


@router.post("/{approval_id}/resubmit", response_model=ApiResponse[dict])
def approval_resubmit(
    approval_id: int,
    payload: dict | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """销售修改已驳回审批单并重新提交（原单复活为 pending）。"""
    try:
        data = resubmit_approval(db, current, approval_id, payload or {})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="approvals.resubmit")
    return ApiResponse(data=data)


@router.post("/{approval_id}/approve", response_model=ApiResponse[dict])
def approval_approve(
    approval_id: int,
    payload: dict | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    if not can_review_approvals(db, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权审批")
    comment = (payload or {}).get("comment") if isinstance(payload, dict) else None
    try:
        data = approve_and_execute(db, current, approval_id, comment=comment)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="approvals.approve")
    return ApiResponse(data=data)


@router.post("/{approval_id}/reject", response_model=ApiResponse[dict])
def approval_reject(
    approval_id: int,
    payload: dict | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    if not can_review_approvals(db, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权审批")
    comment = (payload or {}).get("comment") if isinstance(payload, dict) else None
    try:
        data = reject_approval(db, current, approval_id, comment=comment)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="approvals.reject")
    return ApiResponse(data=data)
