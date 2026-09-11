"""补扣艾迪亚 20260911-1542 批次：amount 晚到被误释放的 10 格。

用法（生产机）:
  cd /opt/geo/AIEO_GEO/backend && source .venv/bin/activate
  export PYTHONPATH=/opt/geo/AIEO_GEO/backend
  python scripts/backfill_aidiya_false_unbilled_20260911.py
  python scripts/backfill_aidiya_false_unbilled_20260911.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal
from app.services.credit_service import backfill_false_unbilled_releases, tenant_today_credit_deduct

TENANT_ID = 6
BATCH_REF = "20260911-1542-kw20"
ORIGIN_IDS = [
    "22787481",
    "22787489",
    "22787490",
    "22787494",
    "22787496",
    "22787500",
    "22787501",
    "22787506",
    "22787512",
    "22787514",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只预览")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        before = float(tenant_today_credit_deduct(db, TENANT_ID))
        if not args.apply:
            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "tenant_id": TENANT_ID,
                        "batch_ref": BATCH_REF,
                        "candidate_ids": ORIGIN_IDS,
                        "today_deduct_before": before,
                        "hint": "加 --apply 才会补扣",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        result = backfill_false_unbilled_releases(
            db,
            tenant_id=TENANT_ID,
            batch_ref=BATCH_REF,
            origin_subtask_ids=ORIGIN_IDS,
        )
        db.commit()
        after = float(tenant_today_credit_deduct(db, TENANT_ID))
        result["today_deduct_before"] = before
        result["today_deduct_after"] = after
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
