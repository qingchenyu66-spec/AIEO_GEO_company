from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.core.redis_client import redis_lock  # noqa: E402
from app.services.monitor_service import list_pending_monitor_task_ids, serialize_task, sync_monitor_task  # noqa: E402
from app.services.platform_session import load_platform_session  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync pending GEO monitor tasks from Molizhishu.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum tasks to sync in one run.")
    parser.add_argument("--task-id", default=None, help="Only sync one task.")
    parser.add_argument("--terminal-grace-hours", type=int, default=24, help="Also recheck recent partial/failed/stopped tasks within this many hours.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    results: list[dict] = []
    try:
        current = load_platform_session(db)
        lock_key = f"pending-sync:{args.task_id or 'batch'}"
        with redis_lock(lock_key, ttl_seconds=900) as acquired:
            if not acquired:
                print(json.dumps([{"status": "locked", "message": "已有其他进程正在同步监测结果"}], ensure_ascii=False, indent=2))
                return 0
            for task_id in list_pending_monitor_task_ids(
                db,
                task_id=args.task_id,
                limit=args.limit,
                terminal_grace_hours=args.terminal_grace_hours,
            ):
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
