"""平台运营 GEO 选词历史与范例库 API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.keyword_miner import (
    KeywordMinerExampleBatchRequest,
    KeywordMinerExampleUpdateRequest,
    KeywordMinerJobEditRequest,
    KeywordMinerJobUpsertRequest,
)
from app.services import keyword_miner_service

router = APIRouter(prefix="/keyword-miner", tags=["Keyword Miner"])


@router.get("/gate", status_code=status.HTTP_204_NO_CONTENT)
def keyword_miner_gate(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    """nginx auth_request / 挖词微服务二次校验: 平台 + 选词台权限."""
    try:
        keyword_miner_service._require_workbench(db, current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs", response_model=ApiResponse[dict])
def list_keyword_miner_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        items = keyword_miner_service.list_jobs(db, current, limit=limit)
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data={"items": items})


@router.get("/jobs/{job_id}", response_model=ApiResponse[dict])
def get_keyword_miner_job(
    job_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.get_job(db, current, job_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.put("/jobs/{job_id}", response_model=ApiResponse[dict])
def upsert_keyword_miner_job(
    job_id: str,
    payload: KeywordMinerJobUpsertRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.upsert_job(db, current, job_id, payload)
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data=data)


@router.put("/jobs/{job_id}/edits", response_model=ApiResponse[dict])
def save_keyword_miner_job_edits(
    job_id: str,
    payload: KeywordMinerJobEditRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.save_job_edits(db, current, job_id, payload)
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data=data)


@router.get("/examples", response_model=ApiResponse[dict])
def list_keyword_miner_examples(
    kind: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    status_filter: str | None = Query(default="active", alias="status"),
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.list_examples(
            db,
            current,
            kind=kind,
            industry=industry,
            status=status_filter,
            q=q,
            limit=limit,
            offset=offset,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/examples/match", response_model=ApiResponse[dict])
def match_keyword_miner_examples(
    industry: str = Query(default=""),
    product: str = Query(default=""),
    kind: str | None = Query(default=None),
    limit: int = Query(default=6, ge=1, le=20),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.match_examples(
            db, current, industry=industry, product=product, kind=kind, limit=limit
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data=data)


@router.post("/examples/touch", response_model=ApiResponse[dict])
def touch_keyword_miner_examples(
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """生成注入范例后累加 use_count."""
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ids 必须为数组")
    try:
        data = keyword_miner_service.touch_examples(db, current, ids)
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data=data)


@router.post("/examples/batch", response_model=ApiResponse[dict])
def batch_create_keyword_miner_examples(
    payload: KeywordMinerExampleBatchRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.batch_create_examples(db, current, payload)
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data=data)


@router.patch("/examples/{example_id}", response_model=ApiResponse[dict])
def update_keyword_miner_example(
    example_id: int,
    payload: KeywordMinerExampleUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = keyword_miner_service.update_example(db, current, example_id, payload)
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return ApiResponse(data=data)
