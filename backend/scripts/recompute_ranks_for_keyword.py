"""Recompute mention_position / all_rankings_json from stored answers (ranking parser refresh)."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from sqlalchemy import or_, select, create_engine
from sqlalchemy.orm import Session, sessionmaker

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import _is_industry_monitor_keyword, get_brand_asset, keyword_group_to_dict, list_keyword_groups
from app.services.monitor_service import (
    _ranking_match_terms,
    _resolve_brand_rank_detail,
    _subtask_answer_plaintext,
    recompute_subtask_rank_from_answer,
)
from app.services.monitor_stats_service import refresh_stats_after_subtask_backfill
from app.services.ranking_parser import parse_answer_rankings
from app.services.rank_llm_service import should_trigger_llm_fallback
from app.services.schedule_context import lead_diagnosis_runs_for_tasks, prompt_monitor_intent, schedule_runs_for_tasks
from app.services.monitor_stats_service import _detect_stat_date


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _subtask_day(db: Session, subtask: GeoMonitorSubtask, task: GeoMonitorTask) -> date | None:
    schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    lead_run = lead_diagnosis_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    return _detect_stat_date(
        subtask,
        task,
        schedule_run=schedule_run,
        lead_run=lead_run,
        asset=asset,
    )


def _subtask_needs_llm_fallback(db: Session, subtask: GeoMonitorSubtask, task: GeoMonitorTask) -> bool:
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return False
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    brand_terms = _ranking_match_terms(asset, groups)
    if not brand_terms:
        keyword = str(task.monitor_keywords or "").strip()
        brand_terms = [keyword] if keyword else []
    monitor_keyword = str(task.monitor_keywords or "").strip()
    resolution = _resolve_brand_rank_detail(subtask, monitor_keyword, brand_terms, asset)
    is_industry_task = asset is not None and _is_industry_monitor_keyword(monitor_keyword, asset)
    return should_trigger_llm_fallback(resolution, is_industry_task=is_industry_task)


def _recompute_subtask_row(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    dry_run: bool,
    llm_fallback_only: bool,
) -> dict | None:
    day = _subtask_day(db, subtask, task)
    if llm_fallback_only and not _subtask_needs_llm_fallback(db, subtask, task):
        return None

    previous = subtask.mention_position
    parsed = parse_answer_rankings(_subtask_answer_plaintext(subtask))
    subtask.all_rankings_json = (
        [{"name": entry.get("name"), "rank": entry.get("rank"), "category": entry.get("category")} for entry in parsed]
        if parsed
        else None
    )
    recompute_subtask_rank_from_answer(db, subtask, task)
    current = subtask.mention_position
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    rank_resolution = raw.get("rank_resolution") if isinstance(raw.get("rank_resolution"), dict) else {}
    if previous == current and not (llm_fallback_only and rank_resolution.get("source") == "llm"):
        return None

    item = {
        "subtask_id": subtask.subtask_id,
        "platform": subtask.platform,
        "prompt": subtask.prompt,
        "day": day.isoformat() if day else None,
        "before": previous,
        "after": current,
        "rank_source": rank_resolution.get("source"),
    }
    if not dry_run:
        refresh_stats_after_subtask_backfill(
            db,
            task=task,
            subtask=subtask,
            previous_stat_date=day,
        )
    return item


def recompute_for_tenant(
    db: Session,
    *,
    tenant_id: int,
    since: date | None = None,
    until: date | None = None,
    dry_run: bool = False,
    llm_fallback_only: bool = False,
) -> list[dict]:
    rows = db.execute(
        select(GeoMonitorSubtask, GeoMonitorTask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorSubtask.status == "completed",
            GeoMonitorSubtask.answer_content.isnot(None),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    ).all()

    changed: list[dict] = []
    for subtask, task in rows:
        day = _subtask_day(db, subtask, task)
        if since and day and day < since:
            continue
        if until and day and day > until:
            continue
        item = _recompute_subtask_row(
            db, subtask, task, dry_run=dry_run, llm_fallback_only=llm_fallback_only,
        )
        if item:
            changed.append(item)

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return changed


def recompute_for_keyword(
    db: Session,
    *,
    tenant_id: int,
    keyword: str,
    since: date | None = None,
    until: date | None = None,
    dry_run: bool = False,
    llm_fallback_only: bool = False,
) -> list[dict]:
    token = (keyword or "").strip()
    if not token:
        raise ValueError("keyword required")

    rows = db.execute(
        select(GeoMonitorSubtask, GeoMonitorTask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorSubtask.status == "completed",
            GeoMonitorSubtask.answer_content.isnot(None),
            or_(
                GeoMonitorSubtask.prompt.like(f"%{token}%"),
                GeoMonitorTask.monitor_keywords.like(f"%{token}%"),
            ),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    ).all()

    changed: list[dict] = []
    for subtask, task in rows:
        day = _subtask_day(db, subtask, task)
        if since and day and day < since:
            continue
        if until and day and day > until:
            continue

        item = _recompute_subtask_row(
            db, subtask, task, dry_run=dry_run, llm_fallback_only=llm_fallback_only,
        )
        if item:
            changed.append(item)

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute ranks from stored monitor answers")
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--keyword", help="monitor keyword / prompt substring filter")
    parser.add_argument("--all", action="store_true", help="recompute all completed subtasks for tenant")
    parser.add_argument(
        "--llm-fallback-only",
        action="store_true",
        help="only recompute subtasks that need DeepSeek rank fallback",
    )
    parser.add_argument("--since", help="YYYY-MM-DD")
    parser.add_argument("--until", help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.all and not args.keyword:
        parser.error("provide --keyword or --all")

    engine = create_engine(
        f"mysql+pymysql://{settings.database_user}:{settings.database_password}"
        f"@{settings.database_host}:{settings.database_port}/{settings.database_name}"
    )
    db = sessionmaker(bind=engine)()
    try:
        common = {
            "tenant_id": args.tenant_id,
            "since": _parse_day(args.since),
            "until": _parse_day(args.until),
            "dry_run": args.dry_run,
            "llm_fallback_only": args.llm_fallback_only,
        }
        if args.all:
            changed = recompute_for_tenant(db, **common)
            scope = f"tenant={args.tenant_id} ALL"
        else:
            changed = recompute_for_keyword(db, keyword=args.keyword, **common)
            scope = f"tenant={args.tenant_id} keyword={args.keyword!r}"
        suffix = " llm_fallback_only" if args.llm_fallback_only else ""
        print(f"{scope}{suffix} changed={len(changed)} dry_run={args.dry_run}")
        for item in changed:
            print(item)
    finally:
        db.close()


if __name__ == "__main__":
    main()
