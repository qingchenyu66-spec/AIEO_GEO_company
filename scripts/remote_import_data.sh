#!/bin/bash
set -euo pipefail

echo "Stopping app services..."
systemctl stop geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default || true

cd /opt/geo/AIEO_GEO/backend
DB_PASS=$(grep -E '^DATABASE_PASSWORD=' .env | cut -d= -f2-)
DB_USER=$(grep -E '^DATABASE_USER=' .env | cut -d= -f2-)
DB_NAME=$(grep -E '^DATABASE_NAME=' .env | cut -d= -f2-)

echo "Recreating database ${DB_NAME}..."
mysql -e "DROP DATABASE IF EXISTS \`${DB_NAME}\`; CREATE DATABASE \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost'; FLUSH PRIVILEGES;"

echo "Importing dump..."
mysql --default-character-set=utf8mb4 -u"${DB_USER}" -p"${DB_PASS}" "${DB_NAME}" < /tmp/geo_monitor_system_migrate.sql
echo "Import done"

echo "Restoring knowledge files..."
mkdir -p /opt/geo/AIEO_GEO/backend/storage/knowledge
unzip -qo /tmp/geo-knowledge.zip -d /opt/geo/AIEO_GEO/backend/storage/knowledge
find /opt/geo/AIEO_GEO/backend/storage/knowledge -type f | wc -l

echo "Counts:"
. .venv/bin/activate
export PYTHONPATH=/opt/geo/AIEO_GEO/backend
python - <<'PY'
from sqlalchemy import text
from app.core.database import SessionLocal
db = SessionLocal()
tables = [
    "sys_user", "sys_tenant", "geo_monitor_task", "geo_monitor_subtask",
    "geo_brand_asset", "geo_knowledge_file", "geo_report", "geo_lead_diagnosis",
]
for t in tables:
    try:
        n = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        print(f"{t}: {n}")
    except Exception as e:
        print(f"{t}: ERR {e}")
db.close()
PY

echo "Starting services..."
systemctl start geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default
sleep 3
systemctl is-active geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default
curl -sS http://127.0.0.1:8001/api/v1/health || true
echo
curl -sS http://127.0.0.1/api/v1/health || true
echo
rm -f /tmp/geo_monitor_system_migrate.sql /tmp/geo-knowledge.zip
echo MIGRATE_DATA_OK
