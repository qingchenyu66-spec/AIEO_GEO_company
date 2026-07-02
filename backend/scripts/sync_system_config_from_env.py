"""One-shot: sync .env settings into sys_config registry rows."""

from __future__ import annotations

from app.core.database import SessionLocal
from app.services.system_config_service import apply_all_configs_from_db, sync_registry_from_env


def main() -> None:
    db = SessionLocal()
    try:
        count = sync_registry_from_env(db, overwrite=True)
        apply_all_configs_from_db(db)
        print(f"synced {count} config row(s) from .env into sys_config")
    finally:
        db.close()


if __name__ == "__main__":
    main()
