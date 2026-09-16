# -*- coding: utf-8 -*-
"""Export production store-guide samples for offline rank impact testing."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.monitor_service import _subtask_answer_plaintext, _task_brand_terms_for_rank

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    out_path = sys.argv[3] if len(sys.argv) > 3 else "/tmp/prod_store_rank_sample.json"
    pin = "\U0001f4cd"
    db = SessionLocal()
    try:
        since = datetime.now() - timedelta(days=max(1, days))
        rows = db.execute(
            select(GeoMonitorSubtask, GeoMonitorTask, Tenant)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .join(Tenant, Tenant.id == GeoMonitorTask.tenant_id)
            .where(
                GeoMonitorSubtask.status == "completed",
                GeoMonitorSubtask.updated_at >= since,
                GeoMonitorSubtask.answer_content.isnot(None),
                or_(
                    GeoMonitorSubtask.prompt.like("%门店%"),
                    GeoMonitorSubtask.prompt.like("%专卖店%"),
                    GeoMonitorSubtask.prompt.like("%板材店%"),
                    GeoMonitorSubtask.answer_content.like(f"%{pin}%"),
                ),
            )
            .order_by(GeoMonitorSubtask.updated_at.desc())
            .limit(limit)
        ).all()
        items = []
        for sub, task, tenant in rows:
            text = _subtask_answer_plaintext(sub) or ""
            if len(text.strip()) < 40:
                continue
            raw = sub.raw_result_json if isinstance(sub.raw_result_json, dict) else {}
            items.append(
                {
                    "subtask_id": sub.subtask_id,
                    "tenant_id": task.tenant_id,
                    "tenant": tenant.name,
                    "platform": sub.platform,
                    "prompt": sub.prompt,
                    "monitor_keywords": task.monitor_keywords,
                    "db_rank": sub.mention_position,
                    "brand_terms": _task_brand_terms_for_rank(db, task),
                    "answer": text,
                    "updated_at": str(sub.updated_at),
                    "manual_locked": bool(
                        raw.get("manual_rank_locked") or raw.get("manual_snapshot")
                    ),
                    "rank_resolution": raw.get("rank_resolution"),
                }
            )
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "days": days,
            "count": len(items),
            "items": items,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f"WROTE {out_path} count={len(items)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
