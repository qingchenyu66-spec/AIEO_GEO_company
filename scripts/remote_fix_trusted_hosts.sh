#!/bin/bash
set -euo pipefail
cd /opt/geo/AIEO_GEO/backend
python3 <<'PY'
from pathlib import Path
p = Path(".env")
out = []
for line in p.read_text().splitlines():
    if line.startswith("TRUSTED_HOSTS="):
        out.append(
            'TRUSTED_HOSTS=["www.aieokj.com","aieokj.com","101.200.152.71","127.0.0.1","localhost"]'
        )
    else:
        out.append(line)
p.write_text("\n".join(out) + "\n")
print("patched")
PY
systemctl restart geo-api
sleep 3
systemctl is-active geo-api
curl -sS http://127.0.0.1:8001/api/v1/health
echo
curl -sS -H 'Host: 101.200.152.71' http://127.0.0.1/api/v1/health
echo
