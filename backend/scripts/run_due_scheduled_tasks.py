from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import joinedload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.dependencies import CurrentSession  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_identity import UserIdentity  # noqa: E402
from app.services.schedule_service import run_due_scheduled_tasks  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run due GEO monitor scheduled tasks.")
    parser.add_argument("--tenant-id", type=int, default=None, help="Only run one tenant.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum tenants to process.")
    parser.add_argument("--max-prompts", type=int, default=50, help="Maximum prompts per tenant.")
    parser.add_argument("--force", action="store_true", help="Run immediately and use current time as schedule key.")
    parser.add_argument("--at", default=None, help="Run as a specific local time, format: YYYY-MM-DD HH:mm.")
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
        raise RuntimeError("没有可用的平台运营端身份，无法执行定时监测。")
    return CurrentSession(user=identity.user, identity=identity)


def main() -> int:
    args = parse_args()
    run_at = datetime.strptime(args.at, "%Y-%m-%d %H:%M") if args.at else None
    db = SessionLocal()
    try:
        current = load_platform_session(db)
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
