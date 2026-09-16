#!/bin/bash
# 2026-08-24 - 稳定性②：生产快/重/回调 uvicorn（8001/8002/8003）
# 2026-09-16 - 每条 lane 双实例：A=原端口，B=8011/8012/8013，供轮转重启
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
RestartSec=3
TimeoutStopSec=30
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
}

write_unit geo-api-a 8001 2
write_unit geo-api-b 8011 2
write_unit geo-api-heavy-a 8002 1
write_unit geo-api-heavy-b 8012 1
write_unit geo-api-callback-a 8003 1
write_unit geo-api-callback-b 8013 1

systemctl daemon-reload
systemctl enable geo-api-a geo-api-b geo-api-heavy-a geo-api-heavy-b geo-api-callback-a geo-api-callback-b

# 只拉起 B（新端口，不和旧 geo-api 抢 8001）。A 由 deploy_prod 在停旧 unit 后启动。
systemctl start geo-api-b geo-api-heavy-b geo-api-callback-b || true
echo "API_SPLIT_UNITS_OK"
