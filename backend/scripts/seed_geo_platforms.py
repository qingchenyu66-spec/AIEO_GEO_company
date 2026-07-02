"""Seed geo_platform from Molizhishu catalog."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.services.geo_platform_seed_service import sync_geo_platforms_from_catalog


def main() -> None:
    with SessionLocal() as db:
        result = sync_geo_platforms_from_catalog(db, force_refresh=False)
    print(f"geo_platform sync done: {result}")


if __name__ == "__main__":
    main()
