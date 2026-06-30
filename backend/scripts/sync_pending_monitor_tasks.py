from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import joinedload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.dependencies import CurrentSession  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.monitor import GeoMonitorTask  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_identity import UserIdentity  # noqa: E402
from app.services.monitor_service import TERMINAL_STATUSES, serialize_task, sync_monitor_task  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync pending GEO monitor tasks from Molizhishu.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum tasks to sync in one run.")
    parser.add_argument("--task-id", default=None, help="Only sync one task.")
    parser.add_argument("--terminal-grace-hours", type=int, default=24, help="Also recheck recent partial/failed/stopped tasks within this many hours.")
    return parser.parse_args()


def load_platform_session(db) -> CurrentSession:
    identity = db.scalar(
        select(UserIdentity)
        .options(joinedload(UserIdentity.user), joinedload(UserIdentity.tenant))
        .join(User, User.id == UserIdentity.user_id)
        .where(
            UserIdentity.identity_type == "PLATFORM",
            UserIdentity.status.is_(True),
            UserIdentity.deleted.is_(False),
            User.status.is_(True),
            User.deleted.is_(False),
        )
        .order_by(UserIdentity.is_default.desc(), UserIdentity.id.asc())
    )
    if identity is None or identity.user is None or not identity.user.status:
        raise RuntimeError("没有可用的平台运营端身份，无法同步监测任务。")
    return CurrentSession(user=identity.user, identity=identity)


def pending_task_ids(db, *, task_id: str | None, limit: int, terminal_grace_hours: int) -> list[str]:
    stmt = select(GeoMonitorTask.task_id).where(GeoMonitorTask.deleted.is_(False))
    if task_id:
        stmt = stmt.where(GeoMonitorTask.task_id == task_id)
    else:
        grace_cutoff = datetime.now() - timedelta(hours=max(0, terminal_grace_hours))
        stmt = stmt.where(
            or_(
                GeoMonitorTask.status.notin_(TERMINAL_STATUSES),
                and_(
                    GeoMonitorTask.status.in_(("partial_completed", "failed", "stopped")),
                    GeoMonitorTask.updated_at >= grace_cutoff,
                ),
            )
        )
    stmt = stmt.order_by(GeoMonitorTask.updated_at.asc(), GeoMonitorTask.id.asc()).limit(limit)
    return list(db.scalars(stmt))


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    results: list[dict] = []
    try:
        current = load_platform_session(db)
        for task_id in pending_task_ids(db, task_id=args.task_id, limit=args.limit, terminal_grace_hours=args.terminal_grace_hours):
            try:
                task = sync_monitor_task(db, task_id, current)
                results.append({"task_id": task_id, "status": "synced", "task": serialize_task(task)})
            except Exception as exc:
                results.append({"task_id": task_id, "status": "failed", "message": str(exc)})
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 0 if all(item["status"] == "synced" for item in results) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
