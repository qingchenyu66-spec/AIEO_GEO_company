#!/bin/bash
# 2026-08-24 - 稳定性②：生产快/重/回调三 uvicorn 进程（8001/8002/8003）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv/bin/uvicorn"
ENV_FILE="$BACKEND/.env"

write_unit() {
  local name="$1" port="$2" workers="$3"
  cat > "/etc/systemd/system/${name}.service" <<EOF
[Unit]
Description=GEO Monitor API (${name})
After=network.target mysql.service redis-server.service

[Service]
User=root
WorkingDirectory=${BACKEND}
Environment=PYTHONPATH=${BACKEND}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV} app.main:app --host 127.0.0.1 --port ${port} --workers ${workers}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

write_unit geo-api 8001 3
write_unit geo-api-heavy 8002 2
write_unit geo-api-callback 8003 1

systemctl daemon-reload
systemctl enable geo-api geo-api-heavy geo-api-callback
echo "API_SPLIT_UNITS_OK"
