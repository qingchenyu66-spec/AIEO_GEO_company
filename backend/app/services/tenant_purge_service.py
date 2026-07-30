"""企业彻底删除：先落盘备份，再清监测历史与客户账号，最后软删企业。"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup, BrandWordGroup
from app.models.knowledge import KnowledgeFile
from app.models.monitor import (
    GeoMonitorDailyStat,
    GeoMonitorScheduleRun,
    GeoMonitorSourceDaily,
    GeoMonitorSubtask,
    GeoMonitorTask,
)
from app.models.report import GeoReport
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity

logger = logging.getLogger(__name__)

# ponytail: 备份目录固定在 backend/data；磁盘满时需人工清理，升级可改配置项
_BACKUP_ROOT = Path(__file__).resolve().parents[2] / "data" / "tenant_purge_backups"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _row_dict(obj: Any, *, skip: set[str] | None = None) -> dict[str, Any]:
    skip = skip or set()
    data: dict[str, Any] = {}
    for key in obj.__mapper__.column_attrs.keys():  # type: ignore[attr-defined]
        if key in skip:
            continue
        data[key] = _json_safe(getattr(obj, key, None))
    return data


def backup_dir() -> Path:
    _BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    return _BACKUP_ROOT


def write_tenant_purge_backup(db: Session, tenant: Tenant) -> Path:
    """写出 gzip JSON 备份，返回文件路径。"""
    tenant_id = tenant.id
    tasks = list(db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.tenant_id == tenant_id)))
    task_ids = [item.task_id for item in tasks]
    subtasks: list[GeoMonitorSubtask] = []
    if task_ids:
        # 分批拉子任务，避免一次炸内存
        chunk = 200
        for i in range(0, len(task_ids), chunk):
            part = task_ids[i : i + chunk]
            subtasks.extend(list(db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(part)))))

    identities = list(db.scalars(select(UserIdentity).where(UserIdentity.tenant_id == tenant_id)))
    user_ids = sorted({item.user_id for item in identities})
    users = list(db.scalars(select(User).where(User.id.in_(user_ids)))) if user_ids else []

    payload = {
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
        "tenant": _row_dict(tenant),
        "users": [_row_dict(item, skip={"password_hash"}) for item in users],
        "identities": [_row_dict(item) for item in identities],
        "brand_assets": [
            _row_dict(item)
            for item in db.scalars(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id))
        ],
        "keyword_groups": [
            _row_dict(item)
            for item in db.scalars(select(BrandKeywordGroup).where(BrandKeywordGroup.tenant_id == tenant_id))
        ],
        "brand_word_groups": [
            _row_dict(item)
            for item in db.scalars(select(BrandWordGroup).where(BrandWordGroup.tenant_id == tenant_id))
        ],
        "competitors": [
            _row_dict(item)
            for item in db.scalars(select(BrandCompetitor).where(BrandCompetitor.tenant_id == tenant_id))
        ],
        "knowledge_files": [
            _row_dict(item)
            for item in db.scalars(select(KnowledgeFile).where(KnowledgeFile.tenant_id == tenant_id))
        ],
        "reports": [
            _row_dict(item) for item in db.scalars(select(GeoReport).where(GeoReport.tenant_id == tenant_id))
        ],
        "monitor_tasks": [_row_dict(item) for item in tasks],
        "monitor_subtasks": [_row_dict(item) for item in subtasks],
        "monitor_daily_stats": [
            _row_dict(item)
            for item in db.scalars(select(GeoMonitorDailyStat).where(GeoMonitorDailyStat.tenant_id == tenant_id))
        ],
        "monitor_source_daily": [
            _row_dict(item)
            for item in db.scalars(select(GeoMonitorSourceDaily).where(GeoMonitorSourceDaily.tenant_id == tenant_id))
        ],
        "schedule_runs": [
            _row_dict(item)
            for item in db.scalars(select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.tenant_id == tenant_id))
        ],
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_code = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (tenant.code or str(tenant_id)))
    path = backup_dir() / f"tenant_{tenant_id}_{safe_code}_{stamp}.json.gz"
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb") as fh:
        fh.write(raw)
    logger.info("tenant purge backup written path=%s bytes=%s", path, path.stat().st_size)
    return path


def _soft_delete_rows(db: Session, model: type, tenant_id: int) -> int:
    rows = list(db.scalars(select(model).where(model.tenant_id == tenant_id, model.deleted.is_(False))))  # type: ignore[attr-defined]
    for row in rows:
        row.deleted = True
        status = getattr(row, "status", None)
        if isinstance(status, bool):
            row.status = False
    db.flush()
    return len(rows)


def purge_tenant_thoroughly(
    db: Session,
    tenant: Tenant,
    *,
    operator_user_id: int | None,
) -> dict[str, Any]:
    """备份后清除监测历史与客户账号，并软删企业。"""
    if tenant.deleted:
        raise ValueError("企业已删除")

    backup_path = write_tenant_purge_backup(db, tenant)
    tenant_id = tenant.id
    stats: dict[str, Any] = {"backup_path": str(backup_path), "tenant_id": tenant_id}

    # 客户身份 + 仅挂此企业的用户
    identities = list(db.scalars(select(UserIdentity).where(UserIdentity.tenant_id == tenant_id)))
    user_ids = sorted({item.user_id for item in identities})
    for identity in identities:
        identity.deleted = True
        identity.status = False
    db.flush()
    deleted_users = 0
    for user_id in user_ids:
        other = db.scalar(
            select(UserIdentity.id).where(
                UserIdentity.user_id == user_id,
                UserIdentity.deleted.is_(False),
                UserIdentity.tenant_id.is_not(None),
                UserIdentity.tenant_id != tenant_id,
            )
        )
        platform = db.scalar(
            select(UserIdentity.id).where(
                UserIdentity.user_id == user_id,
                UserIdentity.deleted.is_(False),
                UserIdentity.identity_type == "PLATFORM",
            )
        )
        if other is None and platform is None:
            user = db.get(User, user_id)
            if user and not user.deleted:
                user.deleted = True
                user.status = False
                deleted_users += 1
    stats["deleted_identities"] = len(identities)
    stats["deleted_users"] = deleted_users

    stats["brand_assets"] = _soft_delete_rows(db, BrandAsset, tenant_id)
    stats["keyword_groups"] = _soft_delete_rows(db, BrandKeywordGroup, tenant_id)
    stats["brand_word_groups"] = _soft_delete_rows(db, BrandWordGroup, tenant_id)
    stats["competitors"] = _soft_delete_rows(db, BrandCompetitor, tenant_id)
    stats["knowledge_files"] = _soft_delete_rows(db, KnowledgeFile, tenant_id)
    stats["reports"] = _soft_delete_rows(db, GeoReport, tenant_id)

    tasks = list(db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.tenant_id == tenant_id)))
    task_ids = [item.task_id for item in tasks]
    deleted_subtasks = 0
    if task_ids:
        chunk = 200
        for i in range(0, len(task_ids), chunk):
            part = task_ids[i : i + chunk]
            result = db.execute(delete(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(part)))
            deleted_subtasks += int(result.rowcount or 0)
        db.flush()
    for task in tasks:
        task.deleted = True
    db.flush()
    stats["monitor_tasks"] = len(tasks)
    stats["monitor_subtasks_deleted"] = deleted_subtasks

    stats["daily_stats"] = int(
        db.execute(delete(GeoMonitorDailyStat).where(GeoMonitorDailyStat.tenant_id == tenant_id)).rowcount or 0
    )
    stats["source_daily"] = int(
        db.execute(delete(GeoMonitorSourceDaily).where(GeoMonitorSourceDaily.tenant_id == tenant_id)).rowcount or 0
    )
    stats["schedule_runs"] = int(
        db.execute(delete(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.tenant_id == tenant_id)).rowcount or 0
    )
    db.flush()

    tenant.deleted = True
    tenant.status = False
    tenant.stop_reason = "purged"
    tenant.stopped_at = datetime.now()
    if operator_user_id is not None:
        tenant.stopped_by = operator_user_id
    db.flush()

    try:
        from app.core.read_cache import invalidate_dashboard_caches

        invalidate_dashboard_caches(tenant_id, bust_overview=True)
    except Exception:
        logger.warning("invalidate cache after purge failed tenant_id=%s", tenant_id, exc_info=True)

    return stats
