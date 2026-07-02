from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.core.redis_client import redis_lock  # noqa: E402
from app.services.platform_session import load_platform_session  # noqa: E402
from app.services.schedule_service import run_due_scheduled_tasks  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run due GEO monitor scheduled tasks.")
    parser.add_argument("--tenant-id", type=int, default=None, help="Only run one tenant.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum tenants to process.")
    parser.add_argument("--max-prompts", type=int, default=50, help="Maximum prompts per tenant.")
    parser.add_argument("--force", action="store_true", help="Run immediately and use current time as schedule key.")
    parser.add_argument("--at", default=None, help="Run as a specific local time, format: YYYY-MM-DD HH:mm.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_at = datetime.strptime(args.at, "%Y-%m-%d %H:%M") if args.at else None
    db = SessionLocal()
    try:
        current = load_platform_session(db)
        lock_time = (run_at or datetime.now()).strftime("%Y%m%d%H%M")
        lock_key = f"scheduled-submit:{args.tenant_id or 'all'}:{lock_time}:{args.force}"
        with redis_lock(lock_key) as acquired:
            if not acquired:
                print(json.dumps([{"status": "locked", "message": "已有其他进程正在执行本轮定时提交"}], ensure_ascii=False, indent=2))
                return 0
            result = run_due_scheduled_tasks(
                db,
                current,
                tenant_id=args.tenant_id,
                limit=args.limit,
                max_prompts=args.max_prompts,
                force=args.force,
                now=run_at,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
