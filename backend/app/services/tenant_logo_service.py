"""企业 Logo 本地存储与读取。"""

from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.tenant import Tenant
from app.services.tenant_scope import resolve_and_guard_tenant_id

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE = 2 * 1024 * 1024
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "tenant-logos"
STAGING_ROOT = Path(__file__).resolve().parents[2] / "storage" / "logo-staging"
# 2026-09-07 - 平台默认 Logo 与企业 Logo 同仓，专用目录名避开数字 tenant_id
PLATFORM_LOGO_DIR = "_platform"
STAGING_KEY_RE = re.compile(r"^[a-f0-9]{32}$")

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def tenant_logo_media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _validate_logo_upload_name(upload: UploadFile) -> str:
    original_name = Path(upload.filename or "").name.strip()
    if not original_name:
        raise ValueError("文件名不能为空")
    file_ext = Path(original_name).suffix.lower()
    if file_ext not in ALLOWED_EXT:
        raise ValueError("Logo 仅支持 png/jpg/webp")
    return file_ext


async def _write_logo_file(target: Path, upload: UploadFile) -> None:
    """共享落盘：企业 / 平台默认 / staging 同一套体积与空文件校验。"""
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


def _find_logo_in_dir(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    for ext in ALLOWED_EXT:
        candidate = directory / f"logo{ext}"
        if candidate.is_file():
            return candidate.resolve()
    return None


def _clear_logo_dir(directory: Path, *, keep_ext: str | None = None) -> None:
    if not directory.is_dir():
        return
    for ext in ALLOWED_EXT:
        if keep_ext and ext == keep_ext:
            continue
        (directory / f"logo{ext}").unlink(missing_ok=True)

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


def _find_disk_logo(tenant_id: int) -> Path | None:
    """磁盘上已有 logo 文件但库内 logo_path 为空时兜底（审批回滚等会留下孤儿文件）。"""
    return _find_logo_in_dir(STORAGE_ROOT / str(int(tenant_id)))


def backfill_tenant_logo_path_if_missing(db: Session, tenant: Tenant) -> tuple[Path | None, bool]:
    """2026-08-27 - 库盘不一致时按磁盘回填 logo_path，避免侧栏永远 404。"""
    if tenant.logo_path:
        try:
            return _safe_logo_path(tenant), False
        except ValueError:
            pass
    disk = _find_disk_logo(tenant.id)
    if disk is None:
        return None, False
    stored_rel = f"{tenant.id}/logo{disk.suffix.lower()}"
    tenant.logo_path = stored_rel
    tenant.logo_updated_at = datetime.fromtimestamp(disk.stat().st_mtime)
    db.flush()
    db.commit()
    return disk.resolve(), True


def tenant_has_logo_on_disk(tenant: Tenant) -> bool:
    return bool(tenant.logo_path) or _find_disk_logo(tenant.id) is not None


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

    file_ext = _validate_logo_upload_name(upload)
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    stored_rel = f"{tenant_id}/logo{file_ext}"
    target = STORAGE_ROOT / stored_rel
    # 2026-08-24 - Logo 上传 500 - mkdir 只建了 tenant-logos，未建 {tenant_id} 子目录
    await _write_logo_file(target, upload)

    if tenant.logo_path and tenant.logo_path != stored_rel:
        old = (STORAGE_ROOT / tenant.logo_path).resolve()
        if old.is_file():
            old.unlink(missing_ok=True)
    else:
        _clear_logo_dir(target.parent, keep_ext=file_ext)

    # 2026-08-24 - 企业侧栏 Logo - 存相对路径，GET 走鉴权流式返回
    now = datetime.now()
    tenant.logo_path = stored_rel
    tenant.logo_updated_at = now
    db.flush()
    return {"tenant_id": tenant_id, **serialize_tenant_logo_meta(tenant)}


def serialize_platform_logo_meta() -> dict:
    path = _find_logo_in_dir(STORAGE_ROOT / PLATFORM_LOGO_DIR)
    if path is None:
        return {"has_logo": False, "logo_updated_at": None}
    return {
        "has_logo": True,
        "logo_updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(sep=" ", timespec="seconds"),
    }


def resolve_platform_logo_path() -> Path:
    path = _find_logo_in_dir(STORAGE_ROOT / PLATFORM_LOGO_DIR)
    if path is None:
        raise ValueError("尚未配置平台默认 Logo")
    root = STORAGE_ROOT.resolve()
    if not path.is_relative_to(root):
        raise ValueError("非法文件路径")
    return path


async def save_platform_logo(upload: UploadFile) -> dict:
    """平台默认 Logo：与企业同一目录规范，目录固定为 _platform。"""
    file_ext = _validate_logo_upload_name(upload)
    target = STORAGE_ROOT / PLATFORM_LOGO_DIR / f"logo{file_ext}"
    await _write_logo_file(target, upload)
    _clear_logo_dir(target.parent, keep_ext=file_ext)
    return serialize_platform_logo_meta()


def clear_platform_logo() -> dict:
    _clear_logo_dir(STORAGE_ROOT / PLATFORM_LOGO_DIR)
    return serialize_platform_logo_meta()


def resolve_tenant_logo_path(
    db: Session,
    current: CurrentSession,
    tenant_id: int,
) -> tuple[Tenant, Path]:
    resolve_and_guard_tenant_id(db, current, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted:
        raise ValueError("企业不存在")
    path, _backfilled = backfill_tenant_logo_path_if_missing(db, tenant)
    if path is None:
        raise ValueError("企业尚未上传 Logo")
    return tenant, path


def _validate_staging_key(staging_key: str) -> str:
    key = str(staging_key or "").strip().lower()
    if not STAGING_KEY_RE.fullmatch(key):
        raise ValueError("无效的 Logo 暂存标识")
    return key


def _staging_dir(owner_user_id: int, staging_key: str) -> Path:
    return STAGING_ROOT / str(int(owner_user_id)) / staging_key


def _find_staging_logo_file(owner_user_id: int, staging_key: str) -> Path:
    directory = _staging_dir(owner_user_id, staging_key)
    if not directory.is_dir():
        raise ValueError("Logo 暂存不存在或已过期")
    for ext in ALLOWED_EXT:
        candidate = directory / f"logo{ext}"
        if candidate.is_file():
            return candidate
    raise ValueError("Logo 暂存文件不存在")


def find_staging_logo_by_key(staging_key: str) -> tuple[int, Path]:
    """按 staging_key 定位暂存文件（全局唯一）。"""
    key = _validate_staging_key(staging_key)
    if not STAGING_ROOT.is_dir():
        raise ValueError("Logo 暂存不存在或已过期")
    for user_dir in STAGING_ROOT.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        try:
            return int(user_dir.name), _find_staging_logo_file(int(user_dir.name), key)
        except ValueError:
            continue
    raise ValueError("Logo 暂存不存在或已过期")


def can_access_logo_staging(db: Session, current: CurrentSession, owner_user_id: int) -> None:
    if current.user.id == int(owner_user_id):
        return
    from app.services.approval_service import can_review_approvals

    if not can_review_approvals(db, current):
        raise PermissionError("无权查看该 Logo 暂存")


def resolve_logo_staging_path(
    db: Session,
    current: CurrentSession,
    *,
    staging_key: str,
) -> tuple[int, Path]:
    owner_user_id, path = find_staging_logo_by_key(staging_key)
    can_access_logo_staging(db, current, owner_user_id)
    return owner_user_id, path


async def save_logo_staging(current: CurrentSession, upload: UploadFile) -> dict:
    """销售提交审批前暂存 Logo，审批通过后再落到企业目录。"""
    file_ext = _validate_logo_upload_name(upload)
    original_name = Path(upload.filename or "").name.strip()
    staging_key = uuid.uuid4().hex
    directory = _staging_dir(current.user.id, staging_key)
    target = directory / f"logo{file_ext}"
    try:
        await _write_logo_file(target, upload)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return {"staging_key": staging_key, "filename": original_name}


def delete_logo_staging(*, staging_key: str, owner_user_id: int) -> None:
    key = _validate_staging_key(staging_key)
    shutil.rmtree(_staging_dir(int(owner_user_id), key), ignore_errors=True)


def cleanup_logo_staging_from_payload(payload: dict | None, *, owner_user_id: int) -> None:
    body = (payload or {}).get("body")
    if not isinstance(body, dict):
        return
    key = str(body.get("logo_staging_key") or "").strip()
    if key:
        delete_logo_staging(staging_key=key, owner_user_id=owner_user_id)


def apply_staging_logo_to_tenant(
    db: Session,
    *,
    tenant_id: int,
    staging_key: str,
    owner_user_id: int,
) -> dict:
    """审批通过或免审时，将暂存 Logo 写入企业。"""
    key = _validate_staging_key(staging_key)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted:
        raise ValueError("企业不存在")

    source = _find_staging_logo_file(int(owner_user_id), key)
    stored_rel = f"{tenant_id}/logo{source.suffix.lower()}"
    target = STORAGE_ROOT / stored_rel
    target.parent.mkdir(parents=True, exist_ok=True)

    if tenant.logo_path and tenant.logo_path != stored_rel:
        old = (STORAGE_ROOT / tenant.logo_path).resolve()
        if old.is_file():
            old.unlink(missing_ok=True)

    shutil.copy2(source, target)
    now = datetime.now()
    tenant.logo_path = stored_rel
    tenant.logo_updated_at = now
    db.flush()
    delete_logo_staging(staging_key=key, owner_user_id=int(owner_user_id))
    return {"tenant_id": tenant_id, **serialize_tenant_logo_meta(tenant)}


def maybe_apply_logo_staging_from_body(
    db: Session,
    *,
    tenant_id: int,
    body: dict | Any,
    owner_user_id: int,
) -> dict | None:
    """审批通过或免审时，按请求体中的暂存 key 落库 Logo。"""
    if hasattr(body, "logo_staging_key"):
        key = str(getattr(body, "logo_staging_key") or "").strip()
    else:
        key = str((body or {}).get("logo_staging_key") or "").strip()
    if not key:
        return None
    return apply_staging_logo_to_tenant(
        db,
        tenant_id=tenant_id,
        staging_key=key,
        owner_user_id=owner_user_id,
    )
