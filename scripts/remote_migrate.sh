#!/bin/bash
set -euo pipefail
cd /opt/geo/AIEO_GEO/backend
DB_PASS=$(grep -E '^DATABASE_PASSWORD=' .env | cut -d= -f2-)
REDIS_PASS=$(grep -E '^REDIS_PASSWORD=' .env | cut -d= -f2-)
echo "db_pass_len=${#DB_PASS} redis_pass_len=${#REDIS_PASS}"

systemctl enable --now mysql redis-server
mysql -e "CREATE DATABASE IF NOT EXISTS geo_monitor_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -e "DROP USER IF EXISTS 'geo_app'@'localhost';"
mysql -e "CREATE USER 'geo_app'@'localhost' IDENTIFIED BY '${DB_PASS}';"
mysql -e "GRANT ALL PRIVILEGES ON geo_monitor_system.* TO 'geo_app'@'localhost'; FLUSH PRIVILEGES;"

if grep -q '^requirepass ' /etc/redis/redis.conf; then
  sed -i "s|^requirepass .*|requirepass ${REDIS_PASS}|" /etc/redis/redis.conf
else
  echo "requirepass ${REDIS_PASS}" >> /etc/redis/redis.conf
fi
sed -i 's/^bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf || true
systemctl restart redis-server
redis-cli -a "${REDIS_PASS}" ping

mysql -ugeo_app -p"${DB_PASS}" -e "SELECT 1 AS ok;" geo_monitor_system

. .venv/bin/activate
export PYTHONPATH=/opt/geo/AIEO_GEO/backend
alembic upgrade head
python - <<'PY'
from app.core.database import SessionLocal
from app.services.system_config_service import bootstrap_and_apply
db = SessionLocal()
try:
    bootstrap_and_apply(db)
    print("BOOTSTRAP_OK")
finally:
    db.close()
PY
python - <<'PY'
from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.models.user import User
db = SessionLocal()
try:
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
