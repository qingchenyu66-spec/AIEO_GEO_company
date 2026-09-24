#!/usr/bin/env bash
# ============================================================
# GEO 选词智能体 · 生产启动脚本（服务器通用，不依赖本机绝对路径）
# 用法： bash start-prod.sh   （在 keyword-miner 目录下）
# 依赖： Python3 + python-docx + pycryptodome（建议建 venv）
# 密钥： LLM_API_KEY 等只走环境变量 / 同级 .env，勿提交到仓库
# ============================================================
set -e
cd "$(cd "$(dirname "$0")" && pwd)"

# 1) 定位 Python（优先本地 venv，否则系统 python3）
if [ -x "./.venv/bin/python" ]; then PY="./.venv/bin/python"
elif [ -x "./venv/bin/python" ]; then PY="./venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then PY="python3"
else PY="python"; fi

# 2) 依赖检查（仅提示，不在生产环境自动联网安装）
"$PY" - <<'PYEOF' || true
import importlib.util as u
miss=[m for m in ("docx","Crypto") if u.find_spec(m) is None]
if miss:
    print("⚠️ 缺少依赖:", ", ".join(miss), "-> 请先执行: pip install python-docx pycryptodome")
PYEOF

# 3) 若同级有 .env 则加载（仅本机使用，勿提交到仓库）
if [ -f ".env" ]; then set -a; . ./.env; set +a; fi

# 4) 停掉旧实例，避免端口冲突（仅匹配本目录的 app.py）
pkill -f "keyword-miner/app[.]py" 2>/dev/null || true
pkill -f "/app[.]py" 2>/dev/null || true
sleep 1

# 5) 起服务（HOST/PORT 走环境变量，默认 0.0.0.0:8080）
echo "▶ 启动 GEO 选词智能体 ($PY) ..."
exec "$PY" app.py
