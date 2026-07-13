#!/bin/bash
# 生产机一键更新：git pull → 迁移 → 前端 build → 重启 API
# 用法（在服务器上）：
#   cd /opt/geo/AIEO_GEO && bash scripts/deploy_prod.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "ERROR: $ROOT 不是 git 仓库，请先执行 scripts/bootstrap_prod_git.sh" >&2
  exit 1
fi

echo "==> git pull"
if ! GIT_SSH_COMMAND='ssh -o BatchMode=yes' git fetch origin main; then
  echo "ERROR: git fetch 失败。请先在 GitHub 添加 Deploy Key，见 scripts/PROD-DEPLOY.md" >&2
  exit 1
fi
git checkout main
git pull --ff-only origin main

echo "==> alembic upgrade"
cd "$ROOT/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$ROOT/backend"
alembic upgrade head

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

echo "==> restart services"
systemctl restart geo-api
systemctl reload nginx

echo "==> health check"
sleep 2
curl -sf http://127.0.0.1:8001/api/v1/health | head -c 200
echo
echo "DEPLOY_OK"
