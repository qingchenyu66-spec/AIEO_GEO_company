# -*- coding: utf-8 -*-
"""按现行 resolve 重算客户监测子任务 mention_position（默认规则、保留 all_rankings_json）。

用途：线上客户数据清洗。勿用 parse 覆盖 all_rankings_json（会把已有结构化榜洗丢）。

示例：
  python -m scripts.recompute_customer_ranks --days 14 --geo-only          # dry-run
  python -m scripts.recompute_customer_ranks --days 14 --geo-only --apply
  python -m scripts.recompute_customer_ranks --tenant-id 6 --days 7 --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services import rank_llm_service
from app.services.monitor_service import recompute_subtask_rank_from_answer
from app.services.monitor_stats_service import refresh_stats_after_subtask_backfill
from scripts.recompute_ranks_for_keyword import _subtask_day

sys.stdout.reconfigure(encoding="utf-8")


def _patch_skip_llm() -> None:
    def _passthrough(*, subtask, task, resolution, brand_terms, asset):
        return resolution

    rank_llm_service.resolve_rank_with_optional_llm = _passthrough  # type: ignore[assignment]
    # 批量洗历史只跑规则, 不因空位次或大数去调模型
    rank_llm_service.accept_llm_fallback = lambda **_kwargs: None  # type: ignore[assignment]


def _recompute_keep_rankings(db, subtask, task, *, dry_run: bool) -> dict | None:
    day = _subtask_day(db, subtask, task)
    previous = subtask.mention_position
    recompute_subtask_rank_from_answer(db, subtask, task)
    current = subtask.mention_position
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    rank_resolution = raw.get("rank_resolution") if isinstance(raw.get("rank_resolution"), dict) else {}
    if previous == current:
        return None
    item = {
        "subtask_id": subtask.subtask_id,
        "tenant_id": task.tenant_id,
        "platform": subtask.platform,
        "prompt": (subtask.prompt or "")[:80],
        "purpose": getattr(task, "purpose", None),
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


def _focus_rank4_plus(item: dict) -> bool:
    """变更涉及「第4名及以后 / 空位次」的样本。"""
    for key in ("before", "after"):
        val = item.get(key)
        if val is None:
            return True
        try:
            if float(val) >= 4:
                return True
        except (TypeError, ValueError):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, default=0, help="0=全部未删除企业")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--geo-only", action="store_true", help="跳过 brand_word")
    parser.add_argument(
        "--focus-rank4-plus",
        action="store_true",
        help="仅统计/输出涉及 before或after>=4 或空位次的变更（仍会全量扫描重算）",
    )
    parser.add_argument("--active-only", action="store_true", help="仅服务中企业（status=1）")
    args = parser.parse_args()

    # 2026-08-19 - LLM 主路径时不能再 patch 掉模型，否则重算会把位次洗空
    if not args.with_llm and str(getattr(settings, "rank_engine", "llm") or "").strip().lower() != "llm":
        _patch_skip_llm()

    db = SessionLocal()
    try:
        until = date.today()
        since = until - timedelta(days=max(1, args.days))
        dry_run = not args.apply

        tenant_stmt = select(Tenant).where(Tenant.deleted.is_(False))
        if args.tenant_id:
            tenant_stmt = tenant_stmt.where(Tenant.id == args.tenant_id)
        if args.active_only:
            tenant_stmt = tenant_stmt.where(Tenant.status.is_(True))
        tenants = list(db.scalars(tenant_stmt))
        tenant_ids = [int(t.id) for t in tenants]
        if not tenant_ids:
            raise SystemExit("no tenants matched")

        print(
            json.dumps(
                {
                    "tenant_count": len(tenant_ids),
                    "tenant_ids_sample": tenant_ids[:20],
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "with_llm": args.with_llm,
                    "geo_only": args.geo_only,
                    "active_only": args.active_only,
                    "focus_rank4_plus": args.focus_rank4_plus,
                    "dry_run": dry_run,
                    "mode": "keep_all_rankings_json",
                },
                ensure_ascii=False,
            )
        )

        rows = db.execute(
            select(GeoMonitorSubtask, GeoMonitorTask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .where(
                GeoMonitorTask.tenant_id.in_(tenant_ids),
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorSubtask.status == "completed",
                GeoMonitorSubtask.answer_content.isnot(None),
            )
            .order_by(GeoMonitorSubtask.updated_at.desc())
        ).all()

        scanned = 0
        changed: list[dict] = []
        by_tenant: Counter[int] = Counter()
        for subtask, task in rows:
            if args.geo_only and str(getattr(task, "purpose", "geo") or "geo") == "brand_word":
                continue
            day = _subtask_day(db, subtask, task)
            if day is None or day < since or day > until:
                continue
            scanned += 1
            item = _recompute_keep_rankings(db, subtask, task, dry_run=dry_run)
            if not item:
                continue
            changed.append(item)
            by_tenant[int(task.tenant_id or 0)] += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()

        focus = [i for i in changed if _focus_rank4_plus(i)] if args.focus_rank4_plus else changed
        delta = Counter(f"{i.get('before')}->{i.get('after')}" for i in focus)
        print(f"scanned={scanned} mention_changed={len(changed)} focus_rank4_plus={len(focus)}")
        print("BY_TENANT_TOP", by_tenant.most_common(15))
        print("DELTA_TOP", delta.most_common(40))
        sample = focus[:80] if args.focus_rank4_plus else changed[:80]
        for item in sample:
            print(json.dumps(item, ensure_ascii=False))
        if len(sample) < len(focus if args.focus_rank4_plus else changed):
            total = len(focus if args.focus_rank4_plus else changed)
            print(f"... and {total - len(sample)} more")
    finally:
        db.close()


if __name__ == "__main__":
    main()
