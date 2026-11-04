#!/bin/bash
# 首次把 /opt/geo/AIEO_GEO 接入 GitHub（保留 .env / .venv / node_modules）
# 用法（在服务器上，root）：
#   cd /opt/geo/AIEO_GEO && bash scripts/bootstrap_prod_git.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPO_URL="${GEO_REPO_URL:-git@github.com:qingchenyu66-spec/AIEO_GEO_company.git}"

if [[ -d .git ]]; then
  echo "已是 git 仓库，跳过 bootstrap"
  git remote -v
  exit 0
fi

if [[ ! -f backend/.env ]]; then
  echo "ERROR: 缺少 backend/.env，请先配置环境变量" >&2
  exit 1
fi

echo "==> git init + 绑定 $REPO_URL"
git init
git remote add origin "$REPO_URL"
git fetch origin main
git checkout -B main
git reset --hard origin/main

echo "BOOTSTRAP_OK — 以后更新请运行: bash scripts/deploy_prod.sh"
