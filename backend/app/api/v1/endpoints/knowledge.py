"""知识库 API。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error, raise_write_endpoint_error
from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.knowledge_parse_service import schedule_knowledge_parse, serialize_knowledge_file
from app.services.knowledge_service import (
    assert_knowledge_file_access,
    delete_knowledge_file,
    knowledge_file_media_type,
    list_knowledge_files,
    read_knowledge_file_text,
    resolve_knowledge_file_path,
    save_knowledge_file,
)
from app.services.operation_log_service import write_business_audit

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
    except Exception as exc:
        raise_read_endpoint_error(exc, context="knowledge.files")
    return ApiResponse(data=[serialize_knowledge_file(item) for item in records])


@router.post("/files", response_model=ApiResponse[dict])
async def upload_knowledge_file(
    request: Request,
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
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="knowledge.upload")
    write_business_audit(
        db,
        current,
        "知识库上传",
        f"上传资料：{record.original_name}（{record.file_size} 字节）",
        request=request,
        target_module="知识库",
        target_id=record.id,
        tenant_id=record.tenant_id,
    )
    db.commit()
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
    except Exception as exc:
        raise_read_endpoint_error(exc, context="knowledge.content")
    return ApiResponse(data=data)


@router.get("/files/{file_id}/download")
def download_knowledge_file(
    file_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载知识库原文件。"""
    try:
        record, file_path = resolve_knowledge_file_path(db, current, file_id)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="knowledge.download")
    encoded_name = quote(record.original_name)
    return FileResponse(
        path=file_path,
        media_type=knowledge_file_media_type(record),
        filename=record.original_name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.post("/files/{file_id}/parse", response_model=ApiResponse[dict])
def parse_knowledge_file_endpoint(
    file_id: int,
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """手动触发 DeepSeek 解析指定资料。"""
    try:
        assert_knowledge_file_access(db, current, file_id)
        record = schedule_knowledge_parse(db, file_id)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="knowledge.parse")
    write_business_audit(
        db,
        current,
        "知识库解析",
        f"触发 AI 解析：{record.original_name}",
        request=request,
        target_module="知识库",
        target_id=record.id,
        tenant_id=record.tenant_id,
        risk_level="关注",
    )
    db.commit()
    return ApiResponse(data=serialize_knowledge_file(record))


@router.delete("/files/{file_id}", response_model=ApiResponse[dict])
def remove_knowledge_file(
    file_id: int,
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """逻辑删除企业知识库文件。"""
    from app.models.knowledge import KnowledgeFile
    from sqlalchemy import select

    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件不存在")
    file_name = record.original_name
    file_tenant_id = record.tenant_id
    try:
        delete_knowledge_file(db, current, file_id)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="knowledge.delete")
    write_business_audit(
        db,
        current,
        "知识库删除",
        f"删除资料：{file_name}",
        request=request,
        target_module="知识库",
        target_id=file_id,
        tenant_id=file_tenant_id,
        risk_level="关注",
    )
    db.commit()
    return ApiResponse(data={"id": file_id})
