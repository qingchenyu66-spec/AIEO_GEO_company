"""Hard-delete all tenant-scoped data except one keep tenant."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import delete, inspect, select, update

from app.core.database import SessionLocal
from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup
from app.models.diagnosis import BrandDiagnosis
from app.models.knowledge import KnowledgeFile
from app.models.monitor import GeoMonitorCallbackEvent, GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.ops import OperationLog
from app.models.permission import UserIdentityMenu
from app.models.platform import AlertThreshold
from app.models.report import GeoReport
from app.services.knowledge_service import STORAGE_ROOT
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity


def _delete_if_table(db, table_name: str, stmt) -> int:
    if not inspect(db.bind).has_table(table_name):
        return 0
    return db.execute(stmt).rowcount or 0


def purge_tenants_except(keep_tenant_id: int) -> dict[str, int]:
    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        tenant_ids = [
            row[0]
            for row in db.execute(select(Tenant.id).where(Tenant.id != keep_tenant_id)).all()
        ]
        if not tenant_ids:
            return counts

        task_ids = [
            row[0]
            for row in db.execute(
                select(GeoMonitorTask.task_id).where(GeoMonitorTask.tenant_id.in_(tenant_ids))
            ).all()
        ]

        if task_ids:
            counts["callback_events"] = db.execute(
                delete(GeoMonitorCallbackEvent).where(GeoMonitorCallbackEvent.task_id.in_(task_ids))
            ).rowcount or 0
            counts["subtasks"] = db.execute(
                delete(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(task_ids))
            ).rowcount or 0

        counts["schedule_runs"] = db.execute(
            delete(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.tenant_id.in_(tenant_ids))
        ).rowcount or 0
        counts["monitor_tasks"] = db.execute(
            delete(GeoMonitorTask).where(GeoMonitorTask.tenant_id.in_(tenant_ids))
        ).rowcount or 0

        counts["keyword_groups"] = db.execute(
            delete(BrandKeywordGroup).where(BrandKeywordGroup.tenant_id.in_(tenant_ids))
        ).rowcount or 0
        counts["competitors"] = db.execute(
            delete(BrandCompetitor).where(BrandCompetitor.tenant_id.in_(tenant_ids))
        ).rowcount or 0
        counts["brand_assets"] = db.execute(
            delete(BrandAsset).where(BrandAsset.tenant_id.in_(tenant_ids))
        ).rowcount or 0

        knowledge_rows = list(
            db.scalars(select(KnowledgeFile).where(KnowledgeFile.tenant_id.in_(tenant_ids)))
        )
        storage_root = STORAGE_ROOT
        removed_files = 0
        for item in knowledge_rows:
            file_path = storage_root / item.storage_path
            if file_path.is_file():
                file_path.unlink()
                removed_files += 1
        counts["knowledge_files_disk"] = removed_files
        counts["knowledge_files"] = db.execute(
            delete(KnowledgeFile).where(KnowledgeFile.tenant_id.in_(tenant_ids))
        ).rowcount or 0

        counts["reports"] = _delete_if_table(
            db,
            "geo_report",
            delete(GeoReport).where(GeoReport.tenant_id.in_(tenant_ids)),
        )
        counts["diagnosis"] = _delete_if_table(
            db,
            "geo_brand_diagnosis",
            delete(BrandDiagnosis).where(BrandDiagnosis.tenant_id.in_(tenant_ids)),
        )
        counts["alert_thresholds"] = _delete_if_table(
            db,
            "geo_alert_threshold",
            delete(AlertThreshold).where(AlertThreshold.tenant_id.in_(tenant_ids)),
        )
        counts["operation_logs"] = _delete_if_table(
            db,
            "sys_operation_log",
            delete(OperationLog).where(OperationLog.tenant_id.in_(tenant_ids)),
        )

        identity_ids = [
            row[0]
            for row in db.execute(
                select(UserIdentity.id).where(UserIdentity.tenant_id.in_(tenant_ids))
            ).all()
        ]
        if identity_ids:
            counts["identity_menus"] = db.execute(
                delete(UserIdentityMenu).where(UserIdentityMenu.identity_id.in_(identity_ids))
            ).rowcount or 0
            user_ids = [
                row[0]
                for row in db.execute(
                    select(UserIdentity.user_id).where(UserIdentity.id.in_(identity_ids))
                ).all()
            ]
            counts["identities"] = db.execute(
                delete(UserIdentity).where(UserIdentity.id.in_(identity_ids))
            ).rowcount or 0
            orphan_user_ids = []
            for user_id in set(user_ids):
                remaining = db.scalar(
                    select(UserIdentity.id).where(UserIdentity.user_id == user_id).limit(1)
                )
                if remaining is None:
                    orphan_user_ids.append(user_id)
            if orphan_user_ids:
                db.execute(
                    update(Tenant)
                    .where(Tenant.owner_user_id.in_(orphan_user_ids))
                    .values(owner_user_id=None)
                )
                counts["users"] = db.execute(
                    delete(User).where(User.id.in_(orphan_user_ids))
                ).rowcount or 0

        db.execute(
            update(Tenant).where(Tenant.id.in_(tenant_ids)).values(owner_user_id=None)
        )
        counts["tenants"] = db.execute(
            delete(Tenant).where(Tenant.id.in_(tenant_ids))
        ).rowcount or 0

        for tid in tenant_ids:
            tenant_dir = storage_root / str(tid)
            if tenant_dir.is_dir():
                for child in tenant_dir.iterdir():
                    if child.is_file():
                        child.unlink(missing_ok=True)
                tenant_dir.rmdir()

        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-tenant-id", type=int, default=6)
    args = parser.parse_args()
    result = purge_tenants_except(args.keep_tenant_id)
    print(f"Kept tenant {args.keep_tenant_id}. Purged:", result)
