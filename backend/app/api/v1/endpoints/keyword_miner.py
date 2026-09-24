"""平台运营 GEO 选词历史 API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.keyword_miner import KeywordMinerJobUpsertRequest
from app.services import keyword_miner_service

router = APIRouter(prefix="/keyword-miner", tags=["Keyword Miner"])


@router.get("/jobs", response_model=ApiResponse[dict])
def list_keyword_miner_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        items = keyword_miner_service.list_jobs(db, current, limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
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
