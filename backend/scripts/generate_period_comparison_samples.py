"""CLI：生成桌面周期报告环比 HTML 样例（渲染逻辑在 report_period_comparison_service）。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.report_period_comparison_service import (
    OUT_DIR,
    REPORT_TYPES,
    generate_one,
    _resolve_tenant_id,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成桌面周期报告环比 HTML 样例")
    parser.add_argument("--tenant-id", type=int, default=None)
    parser.add_argument("--tenant-code", type=str, default="AIDIYA_REAL")
    parser.add_argument("--today", type=str, default=None, help="YYYY-MM-DD，默认今天")
    parser.add_argument("--v2", action="store_true", help="生成 _V2 试讲版（不覆盖原版样例）")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        tenant_id, tenant_name = _resolve_tenant_id(db, args.tenant_id, args.tenant_code)
        paths = [generate_one(db, tenant_id, tenant_name, rt, today, v2=args.v2) for rt in REPORT_TYPES]

    print(f"企业: {tenant_name} (id={tenant_id})")
    for path in paths:
        print(path)
    print(f"DONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
