from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.knowledge import KnowledgeFile
from app.services.brand_service import ensure_tenant, resolve_tenant_id

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".md", ".txt"}
MAX_FILE_SIZE = 30 * 1024 * 1024
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "knowledge"


def list_knowledge_files(db: Session, current: CurrentSession, tenant_id: int | None = None) -> list[KnowledgeFile]:
    """按身份读取知识库文件；客户只能查看自己企业，平台端可指定企业。"""
    resolved_tenant_id = resolve_tenant_id(current, tenant_id)
    return list(
        db.scalars(
            select(KnowledgeFile)
            .where(KnowledgeFile.tenant_id == resolved_tenant_id, KnowledgeFile.deleted.is_(False))
            .order_by(KnowledgeFile.id.desc())
        )
    )


async def save_knowledge_file(
    db: Session,
    current: CurrentSession,
    upload: UploadFile,
    tenant_id: int | None = None,
) -> KnowledgeFile:
    """保存企业知识库原文件；当前阶段不解析内容，只登记文件元信息。"""
    resolved_tenant_id = resolve_tenant_id(current, tenant_id)
    ensure_tenant(db, resolved_tenant_id)
    original_name = Path(upload.filename or "").name.strip()
    if not original_name:
        raise ValueError("文件名不能为空")
    file_ext = Path(original_name).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 PDF、Word、Markdown 和 TXT 文件")

    content = await upload.read()
    file_size = len(content)
    if file_size == 0:
        raise ValueError("不能上传空文件")
    if file_size > MAX_FILE_SIZE:
        raise ValueError("单个文件不能超过 30MB")

    tenant_dir = STORAGE_ROOT / str(resolved_tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{file_ext}"
    storage_path = Path(str(resolved_tenant_id)) / stored_name
    (STORAGE_ROOT / storage_path).write_bytes(content)

    record = KnowledgeFile(
        tenant_id=resolved_tenant_id,
        uploader_user_id=current.user.id,
        original_name=original_name,
        stored_name=stored_name,
        file_ext=file_ext.lstrip("."),
        content_type=upload.content_type,
        file_size=file_size,
        storage_path=str(storage_path).replace("\\", "/"),
        status="uploaded",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def knowledge_file_to_dict(record: KnowledgeFile) -> dict:
    """序列化知识库文件，前端只展示业务需要的字段。"""
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "original_name": record.original_name,
        "file_ext": record.file_ext,
        "file_size": record.file_size,
        "status": record.status,
        "created_at": record.created_at.isoformat(),
    }
