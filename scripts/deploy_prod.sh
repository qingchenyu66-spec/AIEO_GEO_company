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

# 当次进程读的是旧脚本；deploy_prod.sh 自己变了就换成新文件再跑
if [[ -z "${DEPLOY_PROD_REEXEC:-}" && "$BEFORE_REV" != "$AFTER_REV" ]]; then
  if git diff --name-only "$BEFORE_REV" "$AFTER_REV" | grep -qE '^scripts/deploy_prod\.sh$'; then
    echo "==> re-exec updated deploy_prod.sh"
    export DEPLOY_PROD_REEXEC=1
    exec bash "$ROOT/scripts/deploy_prod.sh"
  fi
fi

RESTART_API=0
RESTART_CELERY=0
if [[ "$BEFORE_REV" != "$AFTER_REV" ]]; then
  if git diff --name-only "$BEFORE_REV" "$AFTER_REV" | grep -qE '^(backend/|scripts/setup_api_split_services\.sh|scripts/deploy_prod\.sh|deploy/)'; then
    RESTART_API=1
    RESTART_CELERY=1
  fi
else
  # 同 commit 再跑：新 unit / drop-in 仍可能需要落地
  RESTART_API=1
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
# 先写到 dist-next，再同步进 dist，避免 vite 清空正在被访问的目录
rm -rf dist-next
npm run build -- --outDir dist-next
if [[ ! -f dist-next/index.html ]]; then
  echo "ERROR: frontend build missing dist-next/index.html" >&2
  exit 1
fi
mkdir -p dist
# 先铺新文件再切 index.html；不要 --delete，否则在线旧标签页懒加载旧 hash 会 404 白屏
rsync -a --exclude index.html dist-next/ dist/
rsync -a dist-next/index.html dist/index.html
# 清理 14 天前未被引用的旧 hash 资源，控制磁盘
find dist/assets -type f -mtime +14 -delete 2>/dev/null || true

echo "==> API 快/重/回调双实例 (nginx 拆流)"
# 2026-09-18 - 生产 sites-enabled 曾是独立旧文件，只写 sites-available 不会生效，发布窗口全站 502
NGINX_SPLIT_SRC="$ROOT/deploy/nginx/geo-http-prod-split.conf"
cp "$NGINX_SPLIT_SRC" /etc/nginx/sites-available/geo-http.conf
cp "$NGINX_SPLIT_SRC" /etc/nginx/sites-enabled/geo-http.conf
nginx -t
if ! nginx -T 2>/dev/null | grep -q 'upstream geo_api_fast'; then
  echo "ERROR: nginx 未加载 upstream geo_api_fast，拒绝 reload" >&2
  exit 1
fi
if ! nginx -T 2>/dev/null | grep -q '127.0.0.1:8011'; then
  echo "ERROR: nginx fast upstream 缺少 8011，拒绝 reload" >&2
  exit 1
fi
systemctl reload nginx

wait_health() {
  local port="$1"
  local i
  for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${port}/api/v1/health" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: health timeout on :${port}" >&2
  return 1
}

rolling_pair() {
  local unit_a="$1" port_a="$2" unit_b="$3" port_b="$4"
  echo "==> rolling restart ${unit_a} then ${unit_b} (never both down)"
  # 先确认对端在服，再动本侧，避免 a/b 同秒重启
  if ! wait_health "$port_b"; then
    echo "ERROR: 对端 ${unit_b}:${port_b} 不健康，拒绝重启 ${unit_a}" >&2
    exit 1
  fi
  systemctl restart "$unit_a"
  if ! wait_health "$port_a"; then
    echo "ERROR: ${unit_a} 未起来，保留 ${unit_b} 继续服务" >&2
    exit 1
  fi
  if ! wait_health "$port_b"; then
    echo "ERROR: 重启 ${unit_a} 后对端 ${unit_b} 异常，拒绝继续" >&2
    exit 1
  fi
  systemctl restart "$unit_b"
  if ! wait_health "$port_b"; then
    echo "ERROR: ${unit_b} 未起来，${unit_a} 仍在服务" >&2
    exit 1
  fi
}

if [[ "$RESTART_API" == "1" ]]; then
  bash "$ROOT/scripts/setup_api_split_services.sh"
  # 旧单实例让出 A 端口后，再轮转 A/B
  for old in geo-api geo-api-heavy geo-api-callback; do
    if [[ -f "/etc/systemd/system/${old}.service" ]]; then
      systemctl stop "$old" 2>/dev/null || true
      systemctl disable "$old" 2>/dev/null || true
      rm -f "/etc/systemd/system/${old}.service"
    fi
  done
  systemctl daemon-reload
  systemctl start geo-api-a geo-api-heavy-a geo-api-callback-a
  wait_health 8001
  wait_health 8002
  wait_health 8003

  echo "==> rolling restart API pairs"
  rolling_pair geo-api-a 8001 geo-api-b 8011
  rolling_pair geo-api-heavy-a 8002 geo-api-heavy-b 8012
  rolling_pair geo-api-callback-a 8003 geo-api-callback-b 8013
else
  echo "==> skip API restart (frontend-only change)"
fi

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
