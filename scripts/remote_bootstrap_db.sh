#!/bin/bash
set -euo pipefail

APP=/opt/geo/AIEO_GEO/backend
cd "$APP"

# Preserve tokens if present
MOLI=$(grep -E '^MOLIZHISHU_TOKEN=' .env 2>/dev/null | cut -d= -f2- || true)
DS=$(grep -E '^DEEPSEEK_API_KEY=' .env 2>/dev/null | cut -d= -f2- || true)
# Ignore weak/dev placeholders
case "$MOLI" in ""|replace*|changeme*) MOLI="" ;; esac
case "$DS" in ""|replace*|changeme*) DS="" ;; esac
if [ -f /tmp/geo-secrets.env ]; then
  # shellcheck disable=SC1091
  set -a; . /tmp/geo-secrets.env; set +a
  MOLI="${MOLIZHISHU_TOKEN:-$MOLI}"
  DS="${DEEPSEEK_API_KEY:-$DS}"
  rm -f /tmp/geo-secrets.env
fi

REDIS_PASS=$(openssl rand -hex 16)
DB_PASS=$(openssl rand -hex 16)
SECRET=$(openssl rand -hex 32)

cat > .env <<EOF
APP_NAME=GEO Monitor API
APP_ENV=production
DEBUG=false
API_V1_PREFIX=/api/v1
SECRET_KEY=${SECRET}
ACCESS_TOKEN_EXPIRE_MINUTES=120
IDENTITY_TICKET_EXPIRE_MINUTES=30
DATABASE_HOST=127.0.0.1
DATABASE_PORT=3306
DATABASE_USER=geo_app
DATABASE_PASSWORD=${DB_PASS}
DATABASE_NAME=geo_monitor_system
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40
REDIS_ENABLED=true
REDIS_PASSWORD=${REDIS_PASS}
REDIS_URL=redis://:${REDIS_PASS}@127.0.0.1:6379/0
CELERY_ENABLED=true
CELERY_BROKER_URL=redis://:${REDIS_PASS}@127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://:${REDIS_PASS}@127.0.0.1:6379/1
TRUSTED_HOSTS=www.aieokj.com,aieokj.com,101.200.152.71
CORS_ORIGINS=["https://www.aieokj.com","https://aieokj.com","http://www.aieokj.com","http://101.200.152.71"]
AUTH_COOKIE_ENABLED=true
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
AUTH_CSRF_ENABLED=true
AUTH_EXPOSE_TOKEN_IN_BODY=false
FLOWER_ENABLED=false
MOLIZHISHU_BASE_URL=https://business-api.molizhishu.com/api/business/monitor
MOLIZHISHU_TOKEN=${MOLI}
MOLIZHISHU_TIMEOUT_SECONDS=30
DEEPSEEK_API_KEY=${DS}
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_SENTIMENT_KEYWORD_ENABLED=true
DEEPSEEK_REPORT_ENABLED=true
DEEPSEEK_KNOWLEDGE_PARSE_ENABLED=true
KNOWLEDGE_PARSE_TIMEOUT_MINUTES=10
SCHEDULE_TOLERANCE_MINUTES=60
MOLIZHISHU_SUBMIT_RATE_PER_MINUTE=30
MOLIZHISHU_SYNC_RATE_PER_MINUTE=60
EOF
chmod 600 .env
mkdir -p /root/geo-secrets
cp .env /root/geo-secrets/backend.env
chmod 600 /root/geo-secrets/backend.env

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
echo "ENV_READY moli=$([ -n \"$MOLI\" ] && echo yes || echo no) ds=$([ -n \"$DS\" ] && echo yes || echo no)"
echo MIGRATE_OK
