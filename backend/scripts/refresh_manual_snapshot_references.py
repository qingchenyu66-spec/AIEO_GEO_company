#!/usr/bin/env python3
"""重抓一周内非豆包 manual_snapshot 补录的引用信源（不改正文/位次）。

默认 dry-run；加 --apply 才写库。

示例：
  python scripts/refresh_manual_snapshot_references.py --days 7
  python scripts/refresh_manual_snapshot_references.py --days 7 --apply --limit 200
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.monitor_service import _filter_citation_sources, invalidate_monitor_summary_cache
from app.services.share_page_fetch_service import (
    _is_platform_self_url,
    _refs_quality_ok,
    fetch_share_page,
)

logger = logging.getLogger(__name__)

_DOUBAO_BITS = ("doubao",)
_IMAGE_SUFFIX = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _is_doubao_platform(platform: str | None) -> bool:
    p = (platform or "").strip().lower()
    return any(bit in p for bit in _DOUBAO_BITS)


def _share_url_from_subtask(subtask: GeoMonitorSubtask) -> str | None:
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    candidates = [
        raw.get("snapshot_url"),
        raw.get("share_url"),
        subtask.page_screenshot,
    ]
    for item in candidates:
        url = str(item or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        path = urlparse(url).path.lower()
        if path.endswith(_IMAGE_SUFFIX):
            continue
        if "img.molizhishu" in url or "/screenshots/" in url:
            continue
        return url
    return None


def _stored_ref_count(subtask: GeoMonitorSubtask) -> int:
    refs = subtask.reference_list_json or []
    if not isinstance(refs, list):
        return 0
    return len(_filter_citation_sources(refs))


def _looks_like_junk_refs(subtask: GeoMonitorSubtask, share_url: str) -> bool:
    """弱信源：0 条、仅平台自家域、或单条等于分享页自身。"""
    refs = _filter_citation_sources(subtask.reference_list_json or [])
    if not refs:
        return True
    host = (urlparse(share_url).hostname or "").lower()
    if len(refs) == 1:
        only = str(refs[0].get("url") or "")
        if _is_platform_self_url(only, host) or only.rstrip("/") == share_url.rstrip("/"):
            return True
        # 常见脏链：只有平台首页
        try:
            p = urlparse(only)
            if p.path in ("", "/") and _is_platform_self_url(only, host):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _iter_candidates(db: Session, *, days: int, limit: int) -> list[GeoMonitorSubtask]:
    # 2026-08-14 - 全表 ORDER BY 大 JSON 行会炸 sort buffer - 先用 JSON_EXTRACT 收窄
    since = datetime.now() - timedelta(days=days)
    from sqlalchemy import text

    sql = text(
        """
        SELECT s.subtask_id
        FROM geo_monitor_subtask s
        INNER JOIN geo_monitor_task t ON t.task_id = s.task_id
        WHERE t.deleted = 0
          AND s.updated_at >= :since
          AND JSON_UNQUOTE(JSON_EXTRACT(s.raw_result_json, '$.source')) = 'manual_snapshot'
          AND LOWER(COALESCE(s.platform, '')) NOT LIKE '%doubao%'
        ORDER BY s.updated_at DESC
        LIMIT :lim
        """
    )
    ids = [
        str(r[0])
        for r in db.execute(sql, {"since": since, "lim": int(limit)}).all()
    ]
    if not ids:
        return []
    by_id = {
        st.subtask_id: st
        for st in db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id.in_(ids))).all()
    }
    out: list[GeoMonitorSubtask] = []
    for sid in ids:
        st = by_id.get(sid)
        if not st:
            continue
        if _is_doubao_platform(st.platform):
            continue
        if not _share_url_from_subtask(st):
            continue
        out.append(st)
    return out


def _refresh_one(db: Session, subtask: GeoMonitorSubtask, *, apply: bool) -> dict[str, Any]:
    share_url = _share_url_from_subtask(subtask) or ""
    before = _stored_ref_count(subtask)
    junk = _looks_like_junk_refs(subtask, share_url)
    row: dict[str, Any] = {
        "subtask_id": subtask.subtask_id,
        "platform": subtask.platform,
        "share_url": share_url,
        "refs_before": before,
        "junk_before": junk,
        "updated_at": str(subtask.updated_at),
    }
    if not apply:
        row["action"] = "dry-run"
        return row
    try:
        hit = fetch_share_page(share_url, timeout_ms=90000)
    except Exception as exc:  # noqa: BLE001
        row["action"] = "fetch_failed"
        row["error"] = str(exc)[:240]
        return row
    refs = _filter_citation_sources(hit.references or [])
    if _refs_quality_ok(refs, page_host=(hit.source_host or "")):
        # 2026-08-14 - 只刷新信源，不动正文/位次/manual_rank_locked
        subtask.reference_list_json = refs or None
        subtask.citation_list_json = None
        raw = dict(subtask.raw_result_json or {})
        meta = dict(raw.get("backfill_meta") or {}) if isinstance(raw.get("backfill_meta"), dict) else {}
        meta.update(
            {
                "refs_refreshed_at": datetime.now().isoformat(timespec="seconds"),
                "refs_before": before,
                "refs_after": len(refs),
                "refs_refresh_host": hit.source_host,
            }
        )
        raw["backfill_meta"] = meta
        raw["fetch_reference_count"] = len(refs)
        subtask.raw_result_json = raw
        db.add(subtask)
        row["action"] = "updated"
        row["refs_after"] = len(refs)
        return row
    # 2026-08-14 - 千问 my.cn 很多分享无材料面板；旧「1 条平台首页」应清掉而非保留
    if junk and before <= 1:
        subtask.reference_list_json = None
        subtask.citation_list_json = None
        raw = dict(subtask.raw_result_json or {})
        meta = dict(raw.get("backfill_meta") or {}) if isinstance(raw.get("backfill_meta"), dict) else {}
        meta.update(
            {
                "refs_cleared_at": datetime.now().isoformat(timespec="seconds"),
                "refs_before": before,
                "refs_after": 0,
                "refs_clear_reason": "refetch_no_quality_refs",
            }
        )
        raw["backfill_meta"] = meta
        raw["fetch_reference_count"] = 0
        subtask.raw_result_json = raw
        db.add(subtask)
        row["action"] = "cleared_junk"
        row["refs_after"] = 0
        row["refs_fetched"] = len(refs)
        return row
    row["action"] = "skip_weak_fetch"
    row["refs_fetched"] = len(refs)
    return row


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Refresh non-Doubao manual_snapshot references")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--apply", action="store_true", help="写库；默认只统计")
    parser.add_argument("--only-junk", action="store_true", help="仅处理明显脏/空信源")
    args = parser.parse_args()

    db = SessionLocal()
    report: list[dict[str, Any]] = []
    try:
        candidates = _iter_candidates(db, days=args.days, limit=args.limit)
        if args.only_junk:
            filtered = []
            for st in candidates:
                url = _share_url_from_subtask(st) or ""
                if _looks_like_junk_refs(st, url):
                    filtered.append(st)
            candidates = filtered
        print(
            json.dumps(
                {
                    "days": args.days,
                    "apply": args.apply,
                    "only_junk": args.only_junk,
                    "candidate_count": len(candidates),
                    "by_platform": _count_by_platform(candidates),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        tenant_ids: set[int] = set()
        for st in candidates:
            row = _refresh_one(db, st, apply=args.apply)
            report.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if args.apply and row.get("action") in {"updated", "cleared_junk"}:
                task = db.get(GeoMonitorTask, st.task_id)
                if task and task.tenant_id:
                    tenant_ids.add(int(task.tenant_id))
        if args.apply:
            db.commit()
            for tid in tenant_ids:
                invalidate_monitor_summary_cache(tid, bust_overview=True)
            if not tenant_ids:
                invalidate_monitor_summary_cache(bust_overview=True)
        updated = sum(1 for r in report if r.get("action") == "updated")
        cleared = sum(1 for r in report if r.get("action") == "cleared_junk")
        failed = sum(1 for r in report if r.get("action") == "fetch_failed")
        print(
            json.dumps(
                {
                    "done": True,
                    "processed": len(report),
                    "updated": updated,
                    "cleared_junk": cleared,
                    "fetch_failed": failed,
                },
                ensure_ascii=False,
            )
        )
    finally:
        db.close()


def _count_by_platform(rows: list[GeoMonitorSubtask]) -> dict[str, int]:
    out: dict[str, int] = {}
    for st in rows:
        key = str(st.platform or "?")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


if __name__ == "__main__":
    main()
