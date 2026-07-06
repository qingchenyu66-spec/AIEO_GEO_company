from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.knowledge import KnowledgeFile
from app.services.tenant_scope import guard_tenant_resource_access, resolve_and_guard_tenant_id

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".md", ".txt"}
MAX_FILE_SIZE = 30 * 1024 * 1024
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "knowledge"

# 扩展名 -> (magic bytes, offset)
FILE_SIGNATURES: dict[str, list[tuple[bytes, int]]] = {
    ".pdf": [(b"%PDF", 0)],
    ".docx": [(b"PK\x03\x04", 0)],
    ".doc": [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0)],
}


def _validate_file_signature(file_ext: str, content: bytes) -> None:
    signatures = FILE_SIGNATURES.get(file_ext)
    if not signatures:
        return
    if not any(content[offset:offset + len(magic)] == magic for magic, offset in signatures):
        raise ValueError("文件内容与扩展名不匹配，请上传真实 PDF 或 Word 文件")


def _safe_file_path(storage_path: str) -> Path:
    root = STORAGE_ROOT.resolve()
    target = (STORAGE_ROOT / storage_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("非法文件路径")
    return target


def _assert_knowledge_record_access(db: Session, current: CurrentSession, record: KnowledgeFile) -> None:
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id != record.tenant_id:
            raise ValueError("无权访问该文件")
        return
    guard_tenant_resource_access(db, current, record.tenant_id)


def list_knowledge_files(db: Session, current: CurrentSession, tenant_id: int | None = None) -> list[KnowledgeFile]:
    """按身份读取知识库文件；客户只能查看自己企业，平台端可指定企业。"""
    resolved_tenant_id = resolve_and_guard_tenant_id(db, current, tenant_id)
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
    resolved_tenant_id = resolve_and_guard_tenant_id(db, current, tenant_id)
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
    _validate_file_signature(file_ext, content)

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


def delete_knowledge_file(db: Session, current: CurrentSession, file_id: int) -> None:
    """逻辑删除知识库文件；客户只能删除本企业文件。"""
    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")
    _assert_knowledge_record_access(db, current, record)
    record.deleted = True
    db.commit()


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


def read_knowledge_file_text(db: Session, current: CurrentSession, file_id: int) -> dict[str, Any]:
    """读取知识库原文件全文，用于前端预览。"""
    from app.services.knowledge_text_extractor import KnowledgeTextExtractError, extract_knowledge_text

    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")
    _assert_knowledge_record_access(db, current, record)
    file_path = _safe_file_path(record.storage_path)
    if not file_path.exists():
        raise ValueError("文件不存在于存储目录")
    try:
        text = extract_knowledge_text(file_path, record.file_ext)
    except KnowledgeTextExtractError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "file_id": record.id,
        "original_name": record.original_name,
        "char_count": len(text),
        "text": text,
    }


def assert_knowledge_file_access(db: Session, current: CurrentSession, file_id: int) -> KnowledgeFile:
    """解析文件并校验访问权限（解析任务等复用）。"""
    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")
    _assert_knowledge_record_access(db, current, record)
    return record
