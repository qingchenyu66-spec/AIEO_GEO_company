from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.knowledge_service import knowledge_file_to_dict, list_knowledge_files, save_knowledge_file

router = APIRouter(prefix="/knowledge")


@router.get("/files", response_model=ApiResponse[list[dict]])
def knowledge_files(
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """查询企业知识库文件；客户只能查看自身企业。"""
    try:
        records = list_knowledge_files(db, current, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=[knowledge_file_to_dict(item) for item in records])


@router.post("/files", response_model=ApiResponse[dict])
async def upload_knowledge_file(
    tenant_id: int | None = Form(default=None),
    file: UploadFile = File(...),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """上传企业知识库原文件；只保存文件，不做解析和向量化。"""
    try:
        record = await save_knowledge_file(db, current, file, tenant_id)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=knowledge_file_to_dict(record))
