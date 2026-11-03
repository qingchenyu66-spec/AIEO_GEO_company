"""Preview/queue only unsubmitted permission failures for an explicit day.

Run on production after deploying the worker identity fix. Default is read only.
"""
import argparse
from datetime import date, datetime, time, timedelta

from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorScheduleRun
from app.services.platform_session import load_platform_session
from app.services.tenant_scope import is_sales_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    start = datetime.combine(args.date, time.min)
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        current = load_platform_session(db)
        if is_sales_identity(db, current.identity):
            raise SystemExit("Refusing recovery with a sales worker identity")
        rows = list(db.scalars(select(GeoMonitorScheduleRun).where(
            GeoMonitorScheduleRun.created_at >= start,
            GeoMonitorScheduleRun.created_at < start + timedelta(days=1),
            GeoMonitorScheduleRun.status == "failed",
            GeoMonitorScheduleRun.task_id.is_(None),
            GeoMonitorScheduleRun.error_message == "当前账号无权访问该企业数据",
        ).order_by(GeoMonitorScheduleRun.id)))
        print("worker_user_id:", current.user.id, "eligible_runs:", len(rows))
        if args.apply:
            from app.tasks.monitor import submit_schedule_group_task
            from app.services.schedule_service import due_item_from_group_key
            if not settings.celery_enabled:
                raise SystemExit("Celery is disabled")
            for row in rows:
                item = due_item_from_group_key(
                    tenant_id=row.tenant_id, group_key=row.schedule_key,
                    max_prompts=row.prompt_count or settings.celery_scan_submit_max_prompts,
                )
                submit_schedule_group_task.apply_async(
                    kwargs={"tenant_id": item.tenant_id, "group_key": item.group_key,
                            "max_prompts": item.max_prompts, "keyword": item.keyword,
                            "region_code": item.region_code},
                    task_id=f"permission-recovery-{row.id}",
                )
                print("enqueued_run_id:", row.id)
        else:
            print("preview_run_ids:", [row.id for row in rows])
        db.rollback()


if __name__ == "__main__":
    main()
