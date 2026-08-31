# -*- coding: utf-8 -*-
"""方案 A：规则位次比库内更靠前 ≥2 时回写 mention_position（默认 dry-run）。

用途：压 LLM / parser_cross_check 虚高（如进口+国产长榜把类内第4抬成第9）。
不调 DeepSeek；只跑 _resolve_brand_rank_detail。

示例：
  PYTHONPATH=backend python -m scripts.correct_ranks_rules_over_llm --tenant-id 134 --days 7
  PYTHONPATH=backend python -m scripts.correct_ranks_rules_over_llm --tenant-id 134 --days 7 --apply
  PYTHONPATH=backend python -m scripts.correct_ranks_rules_over_llm --tenant-id 134 --start 2026-08-25 --end 2026-08-31 --platform doubao --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset, keyword_group_to_dict, list_keyword_groups
from app.services.monitor_service import (
    _ranking_match_terms,
    _resolve_brand_rank_detail,
    is_manual_snapshot_subtask,
)
from app.services.monitor_stats_service import refresh_stats_after_subtask_backfill
from app.services.rank_llm_service import persist_rank_resolution

sys.stdout.reconfigure(encoding="utf-8")


def _parse_day(text: str) -> date:
    return date.fromisoformat(str(text).strip())


def _day_from_schedule_key(key: str) -> date | None:
    text = str(key or "").strip()
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--days", type=int, default=7, help="相对今天往前 N 天（与 --start/--end 互斥优先后者）")
    parser.add_argument("--start", type=str, default="", help="业务日起 YYYY-MM-DD")
    parser.add_argument("--end", type=str, default="", help="业务日止 YYYY-MM-DD（含）")
    parser.add_argument("--platform", type=str, default="", help="空=全平台；如 doubao")
    parser.add_argument("--min-gap", type=float, default=2.0, help="规则比库内至少好多少名才回写")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="最多回写条数，0=不限")
    args = parser.parse_args()

    if args.start and args.end:
        since = _parse_day(args.start)
        until = _parse_day(args.end)
    else:
        until = date.today()
        since = until - timedelta(days=max(1, args.days) - 1)

    start_key = since.strftime("%Y%m%d")
    end_key_excl = (until + timedelta(days=1)).strftime("%Y%m%d")
    platform = str(args.platform or "").strip().lower()
    min_gap = float(args.min_gap)
    dry_run = not args.apply

    db = SessionLocal()
    try:
        asset = get_brand_asset(db, args.tenant_id)
        if not asset:
            raise SystemExit(f"no brand asset for tenant {args.tenant_id}")
        groups = [keyword_group_to_dict(g) for g in list_keyword_groups(db, args.tenant_id)]
        brand_terms = _ranking_match_terms(asset, groups)
        if not brand_terms:
            raise SystemExit("empty brand_terms")

        schedule_rows = db.execute(
            select(GeoMonitorScheduleRun.schedule_key, GeoMonitorScheduleRun.task_id).where(
                GeoMonitorScheduleRun.tenant_id == args.tenant_id,
                GeoMonitorScheduleRun.task_id.isnot(None),
                GeoMonitorScheduleRun.schedule_key >= start_key,
                GeoMonitorScheduleRun.schedule_key < end_key_excl,
            )
        ).all()
        key_by_task = {}
        for sk, tid in schedule_rows:
            if tid and tid not in key_by_task:
                key_by_task[tid] = sk
        task_ids = list(key_by_task.keys())
        print(
            json.dumps(
                {
                    "tenant_id": args.tenant_id,
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "platform": platform or "all",
                    "min_gap": min_gap,
                    "dry_run": dry_run,
                    "schedule_runs": len(schedule_rows),
                    "tasks": len(task_ids),
                    "brand_terms": brand_terms[:8],
                },
                ensure_ascii=False,
            )
        )
        if not task_ids:
            raise SystemExit("no schedule tasks in window")

        stmt = (
            select(GeoMonitorSubtask, GeoMonitorTask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .where(
                GeoMonitorSubtask.task_id.in_(task_ids),
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.purpose == "geo",
                GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
                GeoMonitorSubtask.answer_content.isnot(None),
            )
        )
        if platform:
            stmt = stmt.where(GeoMonitorSubtask.platform == platform)

        changed: list[dict] = []
        scanned = 0
        skipped_manual = 0
        by_delta: Counter[str] = Counter()

        for subtask, task in db.execute(stmt).all():
            scanned += 1
            if is_manual_snapshot_subtask(subtask):
                skipped_manual += 1
                continue
            sk = key_by_task.get(subtask.task_id) or ""
            day = _day_from_schedule_key(sk)
            if day is None or day < since or day > until:
                continue

            stored = subtask.mention_position
            try:
                stored_f = float(stored) if stored is not None else None
            except (TypeError, ValueError):
                stored_f = None

            detail = _resolve_brand_rank_detail(
                subtask,
                subtask.prompt or task.monitor_keywords,
                brand_terms,
                asset,
            )
            rules = detail.rank
            if rules is None:
                continue
            try:
                rules_f = float(rules)
            except (TypeError, ValueError):
                continue

            if stored_f is not None and (stored_f - rules_f) < min_gap - 1e-9:
                continue

            raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
            old_rr = raw.get("rank_resolution") if isinstance(raw.get("rank_resolution"), dict) else {}
            item = {
                "subtask_id": subtask.subtask_id,
                "day": day.isoformat(),
                "platform": subtask.platform,
                "prompt": (subtask.prompt or "")[:60],
                "before": stored,
                "after": int(rules_f) if rules_f.is_integer() else rules_f,
                "old_source": old_rr.get("source"),
                "old_basis": old_rr.get("rank_basis"),
                "new_source": detail.source,
                "new_basis": detail.rank_basis,
            }
            changed.append(item)
            by_delta[f"{stored}->{item['after']}"] += 1

            if dry_run:
                continue
            # 2026-08-31 - 方案A纠偏 - 仅规则更优≥2时落库，保留正文，刷新日统计/矩阵缓存
            new_rank = item["after"]
            subtask.mention_position = new_rank
            persist_rank_resolution(subtask, detail)
            raw2 = dict(subtask.raw_result_json or {})
            rr2 = dict(raw2.get("rank_resolution") or {})
            rr2["corrected_from"] = {
                "rank": stored,
                "source": old_rr.get("source"),
                "rank_basis": old_rr.get("rank_basis"),
                "at": datetime.now().isoformat(timespec="seconds"),
                "reason": "rules_over_llm_min_gap",
            }
            raw2["rank_resolution"] = rr2
            subtask.raw_result_json = raw2
            refresh_stats_after_subtask_backfill(
                db,
                task=task,
                subtask=subtask,
                previous_stat_date=day,
            )
            if args.limit and len(changed) >= args.limit:
                break

        if dry_run:
            db.rollback()
        else:
            db.commit()

        print(
            json.dumps(
                {
                    "scanned": scanned,
                    "skipped_manual": skipped_manual,
                    "corrected": len(changed),
                    "delta_top": by_delta.most_common(30),
                },
                ensure_ascii=False,
            )
        )
        for row in changed[:60]:
            print(json.dumps(row, ensure_ascii=False))
        if len(changed) > 60:
            print(f"... and {len(changed) - 60} more")
    finally:
        db.close()


if __name__ == "__main__":
    main()
