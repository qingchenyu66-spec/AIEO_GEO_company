from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.knowledge_parse_service import schedule_knowledge_parse, serialize_knowledge_file
from app.services.knowledge_service import (
    delete_knowledge_file,
    list_knowledge_files,
    read_knowledge_file_text,
    save_knowledge_file,
)

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
    return ApiResponse(data=[serialize_knowledge_file(item) for item in records])


@router.post("/files", response_model=ApiResponse[dict])
async def upload_knowledge_file(
    tenant_id: int | None = Form(default=None),
    file: UploadFile = File(...),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """上传企业知识库原文件；可选自动触发 DeepSeek 解析。"""
    try:
        record = await save_knowledge_file(db, current, file, tenant_id)
        if settings.deepseek_knowledge_auto_parse_on_upload and settings.deepseek_knowledge_parse_enabled:
            try:
                record = schedule_knowledge_parse(db, record.id)
            except ValueError:
                db.refresh(record)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=serialize_knowledge_file(record))


@router.get("/files/{file_id}/content", response_model=ApiResponse[dict])
def knowledge_file_content(
    file_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """读取知识库原文件全文，供前端完整预览。"""
    try:
        data = read_knowledge_file_text(db, current, file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/files/{file_id}/parse", response_model=ApiResponse[dict])
def parse_knowledge_file_endpoint(
    file_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """手动触发 DeepSeek 解析指定资料。"""
    del current
    try:
        record = schedule_knowledge_parse(db, file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=serialize_knowledge_file(record))


@router.delete("/files/{file_id}", response_model=ApiResponse[dict])
def remove_knowledge_file(
    file_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """逻辑删除企业知识库文件。"""
    try:
        delete_knowledge_file(db, current, file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": file_id})
