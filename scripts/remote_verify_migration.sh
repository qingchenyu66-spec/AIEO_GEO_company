#!/bin/bash
set -euo pipefail
sleep 2
curl -sS http://127.0.0.1:8001/api/v1/health
echo
curl -sS http://127.0.0.1/api/v1/health
echo
cd /opt/geo/AIEO_GEO/backend
. .venv/bin/activate
export PYTHONPATH=/opt/geo/AIEO_GEO/backend
python <<'PY'
from sqlalchemy import text
from app.core.database import SessionLocal
db = SessionLocal()
rows = db.execute(text("SELECT status, COUNT(*) c FROM geo_monitor_task GROUP BY status ORDER BY c DESC")).all()
print("status_breakdown:")
for r in rows:
    print(f"  {r[0]}: {r[1]}")
pend = db.execute(
    text(
        "SELECT COUNT(*) FROM geo_monitor_task "
        "WHERE status NOT IN ('completed','failed','stopped','partial_completed')"
    )
).scalar()
print("non_terminal:", pend)
db.close()
PY
systemctl is-active geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default
