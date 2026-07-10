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
