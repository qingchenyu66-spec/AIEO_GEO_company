"""公告本地媒体上传（图片/附件）。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.announcement import AnnouncementMedia
from app.services.announcement_service import require_announcement_permission

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_FILE_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".txt", ".md"}
MAX_FILE_SIZE = 20 * 1024 * 1024
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "announcements"


def _safe_path(storage_path: str) -> Path:
    root = STORAGE_ROOT.resolve()
    target = (STORAGE_ROOT / storage_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("非法文件路径")
    return target


async def save_announcement_media(
    db: Session,
    current: CurrentSession,
    upload: UploadFile,
    *,
    kind: str = "auto",
) -> dict:
    require_announcement_permission(db, current, "can_create")
    original_name = Path(upload.filename or "").name.strip()
    if not original_name:
        raise ValueError("文件名不能为空")
    file_ext = Path(original_name).suffix.lower()
    if kind == "image" or (kind == "auto" and file_ext in ALLOWED_IMAGE_EXT):
        if file_ext not in ALLOWED_IMAGE_EXT:
            raise ValueError("图片仅支持 png/jpg/gif/webp")
        media_kind = "image"
    else:
        allowed = ALLOWED_IMAGE_EXT | ALLOWED_FILE_EXT
        if file_ext not in allowed:
            raise ValueError("不支持的文件类型")
        media_kind = "image" if file_ext in ALLOWED_IMAGE_EXT else "file"

    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{file_ext}"
    target = STORAGE_ROOT / stored_name
    file_size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise ValueError("单个文件不能超过 20MB")
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if file_size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("不能上传空文件")

    record = AnnouncementMedia(
        uploader_user_id=current.user.id,
        original_name=original_name,
        stored_name=stored_name,
        file_ext=file_ext.lstrip("."),
        content_type=upload.content_type,
        file_size=file_size,
        storage_path=stored_name,
        kind=media_kind,
        deleted=False,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    return {
        "id": record.id,
        "kind": record.kind,
        "original_name": record.original_name,
        "file_size": record.file_size,
        "url": f"/api/v1/announcements/media/{record.id}",
    }


def resolve_media_file(db: Session, media_id: int) -> tuple[AnnouncementMedia, Path]:
    record = db.scalar(
        select(AnnouncementMedia).where(AnnouncementMedia.id == media_id, AnnouncementMedia.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")
    path = _safe_path(record.storage_path)
    if not path.exists():
        raise ValueError("文件不存在于存储目录")
    return record, path


def media_content_type(record: AnnouncementMedia) -> str:
    if record.content_type and record.content_type != "application/octet-stream":
        return record.content_type
    ext = str(record.file_ext or "").lower().lstrip(".")
    mapping = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
    }
    return mapping.get(ext, "application/octet-stream")
