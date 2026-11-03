"""Preview/queue only unsubmitted permission failures for an explicit day.

Run on production after deploying the worker identity fix. Default is read only.
"""
import argparse
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorTask, GeoMonitorSubtask
from app.models.brand import BrandAsset, BrandCompetitor
from app.services.platform_session import load_platform_session
from app.services.tenant_scope import is_sales_identity


def existing_slot_results(db, row):
    """Conservatively skip a whole group if any matching result is already present.

    Incomplete manual groups remain for review rather than resubmitting filled cells.
    """
    from app.services.schedule_service import (
        due_item_from_group_key, resolve_schedule_keyword_group, build_scheduled_payload,
    )
    from app.services.schedule_context import resolve_task_schedule_context
    from app.core.region_catalog import normalize_region_codes

    item = due_item_from_group_key(tenant_id=row.tenant_id, group_key=row.schedule_key,
                                  max_prompts=row.prompt_count or settings.celery_scan_submit_max_prompts)
    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == row.tenant_id,
                                              BrandAsset.deleted.is_(False)))
    if asset is None:
        return "missing brand configuration"
    group = resolve_schedule_keyword_group(db, item)
    if group is None:
        return "missing keyword group"
    competitors = list(db.scalars(select(BrandCompetitor).where(
        BrandCompetitor.tenant_id == row.tenant_id, BrandCompetitor.deleted.is_(False))))
    payload = build_scheduled_payload(db, asset, competitors, max_prompts=item.max_prompts,
                                     keyword_group=group, region_code=item.region_code)
    expected = {(p.platform, prompt.strip()) for p in payload.platforms for prompt in payload.prompts}
    day = datetime.strptime(item.schedule_key[:8], "%Y%m%d")
    tasks = db.scalars(select(GeoMonitorTask).where(
        GeoMonitorTask.tenant_id == row.tenant_id, GeoMonitorTask.deleted.is_(False),
        GeoMonitorTask.created_at >= day, GeoMonitorTask.created_at < day + timedelta(days=1)))
    for task in tasks:
        linked_run = db.scalar(select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.task_id == task.task_id))
        raw = task.raw_request_json or {}
        ctx = resolve_task_schedule_context(task, linked_run, asset)
        if (raw.get("schedule_window_key") or ctx["schedule_window_key"]) != item.schedule_key:
            continue
        if set(normalize_region_codes(task.region_code_json or [])) != set([item.region_code] if item.region_code else []):
            continue
        for sub in db.execute(select(GeoMonitorSubtask.platform, GeoMonitorSubtask.prompt,
                                     GeoMonitorSubtask.status,
                                     func.length(GeoMonitorSubtask.answer_content).label("answer_len"))
                              .where(GeoMonitorSubtask.task_id == task.task_id)):
            if (sub.platform, (sub.prompt or "").strip()) not in expected:
                continue
            if sub.answer_len or (sub.status in {"pending", "queued", "processing", "running"}
                                  and raw.get("source") != "gap_backfill"):
                return f"existing result or inflight task {task.task_id}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run-ids", required=True, help="Explicit comma-separated approved run IDs")
    args = parser.parse_args()
    start = datetime.combine(args.date, time.min)
    approved_ids = [int(value) for value in args.run_ids.split(",")]
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        current = load_platform_session(db)
        if is_sales_identity(db, current.identity):
            raise SystemExit("Refusing recovery with a sales worker identity")
        rows = list(db.scalars(select(GeoMonitorScheduleRun).where(
            GeoMonitorScheduleRun.id.in_(approved_ids),
            GeoMonitorScheduleRun.created_at >= start,
            GeoMonitorScheduleRun.created_at < start + timedelta(days=1),
            GeoMonitorScheduleRun.status == "failed",
            GeoMonitorScheduleRun.task_id.is_(None),
            GeoMonitorScheduleRun.error_message == "当前账号无权访问该企业数据",
        ).order_by(GeoMonitorScheduleRun.id)))
        eligible_ids = [row.id for row in rows]
        print("worker_user_id:", current.user.id, "eligible_runs:", len(rows),
              "already_handled:", sorted(set(approved_ids) - set(eligible_ids)))
        db.rollback()
        enqueued = 0
        safe_ids = []
        for run_id in eligible_ids:
            # New snapshot immediately before each enqueue catches concurrent manual work.
            db.execute(text("SET TRANSACTION READ ONLY"))
            row = db.get(GeoMonitorScheduleRun, run_id, populate_existing=True)
            if row.status != "failed" or row.task_id or row.error_message != "当前账号无权访问该企业数据":
                print("skipped_changed_run_id:", run_id)
                db.rollback()
                continue
            reason = existing_slot_results(db, row)
            if reason:
                print("skipped_existing_run_id:", run_id, "reason:", reason)
                db.rollback()
                continue
            safe_ids.append(run_id)
            tenant_id, group_key, prompt_count = row.tenant_id, row.schedule_key, row.prompt_count
            db.rollback()
            if args.apply:
                from app.tasks.monitor import submit_schedule_group_task
                from app.services.schedule_service import due_item_from_group_key
                if not settings.celery_enabled:
                    raise SystemExit("Celery is disabled")
                item = due_item_from_group_key(
                    tenant_id=tenant_id, group_key=group_key,
                    max_prompts=prompt_count or settings.celery_scan_submit_max_prompts,
                )
                submit_schedule_group_task.apply_async(
                    kwargs={"tenant_id": item.tenant_id, "group_key": item.group_key,
                            "max_prompts": item.max_prompts, "keyword": item.keyword,
                            "region_code": item.region_code},
                    task_id=f"permission-recovery-{run_id}",
                )
                enqueued += 1
                print("enqueued_run_id:", run_id)
        print("safe_run_ids:", safe_ids, "enqueued:", enqueued)


if __name__ == "__main__":
    main()
