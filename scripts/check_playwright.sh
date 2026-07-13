#!/bin/bash
# 检查 Playwright Chromium 是否可用于报告 PDF 导出
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$ROOT/backend"

python - <<'PY'
from app.services.playwright_health import playwright_chromium_health

result = playwright_chromium_health()
print(result)
raise SystemExit(0 if result.get("status") == "ready" else 1)
PY
