#!/bin/bash
# 生产机一键更新：git pull → 迁移 → 前端 build → 轮转重启 API
# 用法（在服务器上）：
#   cd /opt/geo/AIEO_GEO && bash scripts/deploy_prod.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "ERROR: $ROOT 不是 git 仓库，请先执行 scripts/bootstrap_prod_git.sh" >&2
  exit 1
fi

BEFORE_REV="$(git rev-parse HEAD)"

echo "==> git pull"
if ! GIT_SSH_COMMAND='ssh -o BatchMode=yes' git fetch origin main; then
  echo "ERROR: git fetch 失败。请先在 GitHub 添加 Deploy Key，见 scripts/PROD-DEPLOY.md" >&2
  exit 1
fi
git checkout main
git pull --ff-only origin main
AFTER_REV="$(git rev-parse HEAD)"

RESTART_CELERY=0
if [[ "$BEFORE_REV" != "$AFTER_REV" ]]; then
  if git diff --name-only "$BEFORE_REV" "$AFTER_REV" | grep -qE '^(backend/|scripts/setup_api_split_services\.sh|scripts/deploy_prod\.sh|deploy/)'; then
    RESTART_CELERY=1
  fi
else
  # 同 commit 再跑：新 unit / drop-in 仍可能需要落地
  RESTART_CELERY=1
fi

# 2026-08-10 - 知识库预览 400「文件不存在于存储目录」：backend/storage 被 mkdir 成空目录，冲掉指向 /data/geo/storage 的软链
echo "==> ensure backend/storage -> /data/geo/storage"
DATA_STORAGE="/data/geo/storage"
APP_STORAGE="$ROOT/backend/storage"
mkdir -p "$DATA_STORAGE"
if [[ -L "$APP_STORAGE" ]]; then
  :
elif [[ -d "$APP_STORAGE" ]]; then
  rsync -a --ignore-existing "$APP_STORAGE"/ "$DATA_STORAGE"/
  mv "$APP_STORAGE" "${APP_STORAGE}.broken-$(date +%Y%m%d%H%M%S)"
  ln -sfn "$DATA_STORAGE" "$APP_STORAGE"
  echo "restored symlink $APP_STORAGE -> $DATA_STORAGE"
elif [[ ! -e "$APP_STORAGE" ]]; then
  ln -sfn "$DATA_STORAGE" "$APP_STORAGE"
fi
if [[ ! -L "$APP_STORAGE" ]] || [[ "$(readlink -f "$APP_STORAGE")" != "$(readlink -f "$DATA_STORAGE")" ]]; then
  echo "ERROR: $APP_STORAGE must be symlink to $DATA_STORAGE" >&2
  exit 1
fi

echo "==> alembic upgrade"
cd "$ROOT/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$ROOT/backend"

echo "==> pip install requirements"
pip install -r requirements.txt

alembic upgrade head

echo "==> sync sys_config from .env (Redis/Celery 等运行时配置)"
python scripts/sync_system_config_from_env.py

echo "==> redis health"
python - <<'PY' || echo "WARN: Redis 自检未通过，见运营看板 · Redis 缓存" >&2
from app.core.redis_client import redis_health
result = redis_health()
print("redis:", result)
if result.get("enabled") and result.get("status") != "ready":
    raise SystemExit(1)
PY

echo "==> playwright chromium (周期/Premium 报告 PDF 依赖)"
if ! python -m playwright install chromium; then
  echo "WARN: playwright install chromium 失败，PDF 导出可能不可用" >&2
fi
if command -v playwright >/dev/null 2>&1; then
  playwright install-deps chromium 2>/dev/null || true
fi
python - <<'PY' || echo "WARN: Chromium 启动自检未通过，见 /api/v1/health/ops · playwright_chromium" >&2
from app.services.playwright_health import playwright_chromium_health
result = playwright_chromium_health()
print("playwright_chromium:", result)
if result.get("status") != "ready":
    raise SystemExit(1)
PY

echo "==> frontend build"
cd "$ROOT/frontend"
npm ci --legacy-peer-deps
npm run build

echo "==> API 快/重/回调双实例"
bash "$ROOT/scripts/setup_api_split_services.sh"
cp "$ROOT/deploy/nginx/geo-http-prod-split.conf" /etc/nginx/sites-available/geo-http.conf
nginx -t
systemctl reload nginx

wait_health() {
  local port="$1"
  local i
  for i in $(seq 1 15); do
    if curl -sf "http://127.0.0.1:${port}/api/v1/health" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "WARN: health timeout on :${port}" >&2
  return 1
}

rolling_pair() {
  local unit_a="$1" port_a="$2" unit_b="$3" port_b="$4"
  echo "==> restart ${unit_a} then ${unit_b}"
  systemctl restart "$unit_a"
  wait_health "$port_a" || true
  systemctl restart "$unit_b"
  wait_health "$port_b" || true
}

# 旧单实例让出 A 端口后，再轮转 A/B
for old in geo-api geo-api-heavy geo-api-callback; do
  if [[ -f "/etc/systemd/system/${old}.service" ]]; then
    systemctl stop "$old" 2>/dev/null || true
    systemctl disable "$old" 2>/dev/null || true
    rm -f "/etc/systemd/system/${old}.service"
  fi
done
systemctl daemon-reload
systemctl start geo-api-a geo-api-heavy-a geo-api-callback-a || true
wait_health 8001 || true
wait_health 8002 || true
wait_health 8003 || true

echo "==> rolling restart API pairs"
rolling_pair geo-api-a 8001 geo-api-b 8011
rolling_pair geo-api-heavy-a 8002 geo-api-heavy-b 8012
rolling_pair geo-api-callback-a 8003 geo-api-callback-b 8013

ensure_celery_graceful() {
  local unit="$1"
  local drop="/etc/systemd/system/${unit}.service.d"
  mkdir -p "$drop"
  cat > "${drop}/graceful.conf" <<'EOF'
[Service]
TimeoutStopSec=120
KillSignal=SIGTERM
EOF
}

# 2026-09-02 - 补录 Playwright 独立队列；无 unit 时现场安装
if [[ ! -f /etc/systemd/system/geo-celery-backfill.service ]]; then
  cat > /etc/systemd/system/geo-celery-backfill.service <<'EOF'
[Unit]
Description=GEO Celery Backfill Worker
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
# 浏览器任务串行，避免本机 Chromium 打满
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/celery -A app.celery_app worker -Q backfill -n backfill@%%h -c 1 --loglevel=info
Restart=always
RestartSec=5
TimeoutStopSec=120
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
  systemctl enable geo-celery-backfill
fi

for u in geo-celery-submit geo-celery-sync geo-celery-default geo-celery-backfill geo-celery-beat; do
  if [[ -f "/etc/systemd/system/${u}.service" ]]; then
    ensure_celery_graceful "$u"
  fi
done
systemctl daemon-reload

if [[ "$RESTART_CELERY" == "1" ]]; then
  echo "==> restart Celery one by one"
  for u in geo-celery-submit geo-celery-sync geo-celery-default geo-celery-backfill geo-celery-beat; do
    systemctl restart "$u" || true
    sleep 2
  done
else
  echo "==> skip Celery restart (frontend-only change)"
fi
systemctl is-active geo-celery-backfill || echo "WARN: geo-celery-backfill not active" >&2

echo "==> prune weak-rank backfill bells"
cd "$ROOT/backend"
python - <<'PY' || echo "WARN: backfill notification prune failed" >&2
from app.core.database import SessionLocal
from app.services.snapshot_backfill_service import rebuild_empty_answer_backfill_notifications

db = SessionLocal()
try:
    print("pruned:", rebuild_empty_answer_backfill_notifications(db))
finally:
    db.close()
PY

echo "==> health check"
for port in 8001 8011 8002 8012 8003 8013; do
  curl -sf "http://127.0.0.1:${port}/api/v1/health" | head -c 120
  echo " (port ${port})"
done
curl -sf -o /dev/null -w "https:%{http_code}\n" https://www.aieokj.com/api/v1/health || true
echo "DEPLOY_OK"
