#!/bin/bash
# 安装 / 更新 GEO 选词服务 (keyword-miner)
# 用法（服务器）：cd /opt/geo/AIEO_GEO && bash scripts/setup_keyword_miner.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="$ROOT/deploy/systemd/geo-keyword-miner.service"
UNIT_DST="/etc/systemd/system/geo-keyword-miner.service"
DATA_DIR="/data/geo/keyword-miner"
ENV_FILE="$ROOT/services/keyword-miner/.env"
PY="$ROOT/backend/.venv/bin/python"

if [[ ! -f "$ROOT/services/keyword-miner/app.py" ]]; then
  echo "ERROR: missing $ROOT/services/keyword-miner/app.py" >&2
  exit 1
fi
if [[ ! -x "$PY" ]]; then
  echo "ERROR: missing venv python $PY" >&2
  exit 1
fi

mkdir -p "$DATA_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> create $ENV_FILE from example (请填 LLM_API_KEY)"
  cp "$ROOT/services/keyword-miner/.env.example" "$ENV_FILE"
  # 尝试从 backend/.env 带出 DeepSeek
  if [[ -f "$ROOT/backend/.env" ]]; then
    key="$(grep -E '^DEEPSEEK_API_KEY=' "$ROOT/backend/.env" | head -n1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
    if [[ -n "${key:-}" ]]; then
      # shellcheck disable=SC2016
      sed -i "s|^LLM_API_KEY=.*|LLM_API_KEY=${key}|" "$ENV_FILE"
      echo "filled LLM_API_KEY from backend/.env DEEPSEEK_API_KEY"
    fi
  fi
fi

# 生产默认只监听本机，由 nginx /keyword-miner/ 反代
if ! grep -q '^HOST=' "$ENV_FILE"; then
  echo 'HOST=127.0.0.1' >> "$ENV_FILE"
fi
if ! grep -q '^PORT=' "$ENV_FILE"; then
  echo 'PORT=8088' >> "$ENV_FILE"
fi
if ! grep -q '^HISTORY_BACKEND=' "$ENV_FILE"; then
  echo 'HISTORY_BACKEND=off' >> "$ENV_FILE"
fi
if ! grep -q '^GEO_GATE_URL=' "$ENV_FILE"; then
  echo 'GEO_GATE_URL=http://127.0.0.1:8001/api/v1/keyword-miner/gate' >> "$ENV_FILE"
fi
# 兼容旧配置；HISTORY_BACKEND=off 时不再写 SQLite
if ! grep -q '^HISTORY_DB=' "$ENV_FILE"; then
  echo "HISTORY_DB=${DATA_DIR}/history.db" >> "$ENV_FILE"
fi
# 已有 .env 若仍默认 sqlite，生产切到 off（历史走 GEO 主库）
if grep -q '^HISTORY_BACKEND=sqlite' "$ENV_FILE"; then
  sed -i 's|^HISTORY_BACKEND=sqlite|HISTORY_BACKEND=off|' "$ENV_FILE"
fi

# 生产用 backend venv；补齐选词服务额外依赖（钉钉加解密）
"$ROOT/backend/.venv/bin/pip" install -q "pycryptodome>=3.20.0"

cp "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable geo-keyword-miner
systemctl restart geo-keyword-miner

ok=0
for i in $(seq 1 20); do
  if curl -sf "http://127.0.0.1:8088/api/health" >/dev/null; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" != "1" ]]; then
  echo "ERROR: keyword-miner health failed on :8088" >&2
  systemctl status geo-keyword-miner --no-pager -l || true
  exit 1
fi

echo "keyword-miner OK: http://127.0.0.1:8088/api/health"
curl -sS "http://127.0.0.1:8088/api/health"
echo
