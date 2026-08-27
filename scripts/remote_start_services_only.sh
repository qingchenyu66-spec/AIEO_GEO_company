#!/bin/bash
set -euo pipefail

# 2026-08-10 - 持久化目录在 /data/geo/storage；勿 mkdir 空 backend/storage 冲掉软链
mkdir -p /data/geo/storage/knowledge /data/geo/storage/logs
if [[ ! -L /opt/geo/AIEO_GEO/backend/storage ]]; then
  if [[ -d /opt/geo/AIEO_GEO/backend/storage ]]; then
    rsync -a --ignore-existing /opt/geo/AIEO_GEO/backend/storage/ /data/geo/storage/
    mv /opt/geo/AIEO_GEO/backend/storage "/opt/geo/AIEO_GEO/backend/storage.broken-$(date +%Y%m%d%H%M%S)"
  fi
  ln -sfn /data/geo/storage /opt/geo/AIEO_GEO/backend/storage
fi

cat > /etc/systemd/system/geo-api.service <<'EOF'
[Unit]
Description=GEO Monitor API
After=network.target mysql.service redis-server.service

[Service]
User=root
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/geo-celery-beat.service <<'EOF'
[Unit]
Description=GEO Celery Beat
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/celery -A app.celery_app beat --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/geo-celery-submit.service <<'EOF'
[Unit]
Description=GEO Celery Submit Worker
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/celery -A app.celery_app worker -Q submit -n submit@%%h -c 4 --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/geo-celery-sync.service <<'EOF'
[Unit]
Description=GEO Celery Sync Worker
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/celery -A app.celery_app worker -Q sync -n sync@%%h -c 4 --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/geo-celery-default.service <<'EOF'
[Unit]
Description=GEO Celery Default Worker
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/celery -A app.celery_app worker -Q default -n default@%%h -c 4 --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/geo-http.conf <<'EOF'
upstream geo_api {
    server 127.0.0.1:8001;
    keepalive 32;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name www.aieokj.com aieokj.com 101.200.152.71 _;

    client_max_body_size 32m;
    root /opt/geo/AIEO_GEO/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://geo_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/geo-http.conf /etc/nginx/sites-enabled/geo-http.conf
nginx -t
systemctl enable --now nginx
systemctl reload nginx

systemctl daemon-reload
systemctl enable --now geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default
sleep 3
systemctl is-active geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default nginx
echo '--- health ---'
curl -sS http://127.0.0.1:8001/api/v1/health || true
echo
curl -sS -o /dev/null -w "local_http:%{http_code}\n" http://127.0.0.1/
curl -sS -o /dev/null -w "api_via_nginx:%{http_code}\n" http://127.0.0.1/api/v1/health
echo SERVICES_OK
