"""企业 Logo 本地存储与读取。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.tenant import Tenant
from app.services.tenant_scope import resolve_and_guard_tenant_id

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE = 2 * 1024 * 1024
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "tenant-logos"

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def tenant_logo_media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _safe_logo_path(tenant: Tenant) -> Path:
    if not tenant.logo_path:
        raise ValueError("企业尚未上传 Logo")
    root = STORAGE_ROOT.resolve()
    target = (STORAGE_ROOT / tenant.logo_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("非法文件路径")
    if not target.is_file():
        raise ValueError("Logo 文件不存在")
    return target


def serialize_tenant_logo_meta(tenant: Tenant) -> dict:
    return {
        "has_logo": bool(tenant.logo_path),
        "logo_updated_at": tenant.logo_updated_at.isoformat(sep=" ", timespec="seconds")
        if tenant.logo_updated_at
        else None,
    }


async def save_tenant_logo(
    db: Session,
    current: CurrentSession,
    tenant_id: int,
    upload: UploadFile,
) -> dict:
    resolve_and_guard_tenant_id(db, current, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted:
        raise ValueError("企业不存在")

    original_name = Path(upload.filename or "").name.strip()
    if not original_name:
        raise ValueError("文件名不能为空")
    file_ext = Path(original_name).suffix.lower()
    if file_ext not in ALLOWED_EXT:
        raise ValueError("Logo 仅支持 png/jpg/webp")

    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    stored_rel = f"{tenant_id}/logo{file_ext}"
    target = STORAGE_ROOT / stored_rel
    # 2026-08-24 - Logo 上传 500 - mkdir 只建了 tenant-logos，未建 {tenant_id} 子目录
    target.parent.mkdir(parents=True, exist_ok=True)

    file_size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await upload.read(1024 * 256)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise ValueError("Logo 不能超过 2MB")
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if file_size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("不能上传空文件")

    if tenant.logo_path and tenant.logo_path != stored_rel:
        old = (STORAGE_ROOT / tenant.logo_path).resolve()
        if old.is_file():
            old.unlink(missing_ok=True)

    # 2026-08-24 - 企业侧栏 Logo - 存相对路径，GET 走鉴权流式返回
    now = datetime.now()
    tenant.logo_path = stored_rel
    tenant.logo_updated_at = now
    db.flush()
    return {"tenant_id": tenant_id, **serialize_tenant_logo_meta(tenant)}


def resolve_tenant_logo_path(
    db: Session,
    current: CurrentSession,
    tenant_id: int,
) -> tuple[Tenant, Path]:
    resolve_and_guard_tenant_id(db, current, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted:
        raise ValueError("企业不存在")
    return tenant, _safe_logo_path(tenant)
