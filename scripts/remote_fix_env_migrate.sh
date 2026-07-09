#!/bin/bash
set -euo pipefail
cd /opt/geo/AIEO_GEO/backend

python3 - <<'PY'
from pathlib import Path
p = Path(".env")
lines = []
for line in p.read_text().splitlines():
    if line.startswith("TRUSTED_HOSTS="):
        lines.append('TRUSTED_HOSTS=["www.aieokj.com","aieokj.com","101.200.152.71"]')
    else:
        lines.append(line)
p.write_text("\n".join(lines) + "\n")
print("TRUSTED_HOSTS patched")
PY

. .venv/bin/activate
export PYTHONPATH=/opt/geo/AIEO_GEO/backend
alembic upgrade head

python - <<'PY'
from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.services.system_config_service import bootstrap_and_apply
from app.models.user import User

db = SessionLocal()
try:
    bootstrap_and_apply(db)
    print("BOOTSTRAP_OK")
    n = db.scalar(select(func.count()).select_from(User)) or 0
    print("user_count", n)
    if n == 0:
        import runpy
        runpy.run_module("scripts.seed_demo", run_name="__main__")
        print("SEED_OK")
    else:
        print("SEED_SKIP")
finally:
    db.close()
PY

echo MIGRATE_OK
