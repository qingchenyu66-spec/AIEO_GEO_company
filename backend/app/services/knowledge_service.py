from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.knowledge import KnowledgeFile
from app.services.tenant_scope import guard_tenant_resource_access, resolve_and_guard_tenant_id

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".html",
    ".htm",
    ".ppt",
    ".pptx",
}
MAX_FILE_SIZE = 30 * 1024 * 1024
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "knowledge"

# 扩展名 -> (magic bytes, offset)
FILE_SIGNATURES: dict[str, list[tuple[bytes, int]]] = {
    ".pdf": [(b"%PDF", 0)],
    ".docx": [(b"PK\x03\x04", 0)],
    ".doc": [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0)],
    ".pptx": [(b"PK\x03\x04", 0)],
    ".ppt": [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0)],
    ".png": [(b"\x89PNG\r\n\x1a\n", 0)],
    ".jpg": [(b"\xff\xd8\xff", 0)],
    ".jpeg": [(b"\xff\xd8\xff", 0)],
    ".webp": [(b"RIFF", 0)],
}


def _validate_file_signature(file_ext: str, content: bytes) -> None:
    signatures = FILE_SIGNATURES.get(file_ext)
    if not signatures:
        return
    if file_ext == ".webp":
        if not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
            raise ValueError("文件内容与扩展名不匹配，请上传真实图片文件")
        return
    if not any(content[offset:offset + len(magic)] == magic for magic, offset in signatures):
        raise ValueError("文件内容与扩展名不匹配，请上传真实 PDF、Office 或图片文件")


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
    # 2026-08-18 - 知识库列表依赖 tenant_id - 客户走身份绑定企业，平台必须显式指定，禁止无参扫全库
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
        raise ValueError("仅支持 PDF、Word、PPT、图片、HTML、Markdown 和 TXT 文件")

    # Stream to disk in chunks; abort as soon as size exceeds the cap (CWE-400).
    tenant_dir = STORAGE_ROOT / str(resolved_tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{file_ext}"
    storage_path = Path(str(resolved_tenant_id)) / stored_name
    target = STORAGE_ROOT / storage_path
    file_size = 0
    head = b""
    try:
        with target.open("wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise ValueError("单个文件不能超过 30MB")
                if len(head) < 16:
                    need = 16 - len(head)
                    head += chunk[:need]
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if file_size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("不能上传空文件")
    try:
        _validate_file_signature(file_ext, head)
    except ValueError:
        target.unlink(missing_ok=True)
        raise

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
    db.flush()
    db.refresh(record)
    return record


def delete_knowledge_file(db: Session, current: CurrentSession, file_id: int) -> None:
    """逻辑删除知识库文件；客户侧不允许删除，仅平台运营可删。"""
    if current.identity.identity_type == "CUSTOMER":
        raise ValueError("客户侧不允许删除知识库资料")
    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")
    _assert_knowledge_record_access(db, current, record)
    record.deleted = True
    db.flush()


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


def resolve_knowledge_file_path(db: Session, current: CurrentSession, file_id: int) -> tuple[KnowledgeFile, Path]:
    """返回已通过权限校验的文件记录与磁盘路径。"""
    record = assert_knowledge_file_access(db, current, file_id)
    file_path = _safe_file_path(record.storage_path)
    if not file_path.exists():
        raise ValueError("文件不存在于存储目录")
    return record, file_path


def resolve_knowledge_preview_pdf(db: Session, current: CurrentSession, file_id: int) -> tuple[KnowledgeFile, Path]:
    """返回可内嵌预览的 PDF（原 PDF 或转换缓存）。"""
    from app.services.knowledge_preview_pdf_service import (
        KnowledgePreviewPdfError,
        ensure_knowledge_preview_pdf,
    )

    record, source_path = resolve_knowledge_file_path(db, current, file_id)
    try:
        preview_path = ensure_knowledge_preview_pdf(
            source_path,
            record.file_ext,
            title=record.original_name,
        )
    except KnowledgePreviewPdfError as exc:
        raise ValueError(str(exc)) from exc
    return record, preview_path


def knowledge_file_media_type(record: KnowledgeFile) -> str:
    if record.content_type:
        return record.content_type
    mapping = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "md": "text/markdown; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "htm": "text/html; charset=utf-8",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }
    return mapping.get(str(record.file_ext or "").lower(), "application/octet-stream")
