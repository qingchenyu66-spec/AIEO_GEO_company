#!/usr/bin/env bash
# ============================================================
# GEO 选词智能体 · 一键启动脚本
# 用法： bash start.sh   （建议在 keyword-miner 目录下执行）
# ============================================================
set -e

# 切换到脚本所在目录（无论在哪里调用）
cd "$(cd "$(dirname "$0")" && pwd)"

# 优先使用本工具自带的 venv python（已装 python-docx + pycryptodome）
VENV_PY="/Users/aidiya/.workbuddy/binaries/python/envs/default/bin/python"
if [ ! -x "$VENV_PY" ]; then
  VENV_PY="python3"
fi

# ---------- 按需取消注释并填写以下环境变量 ----------
# 大模型（不填则演示模式）
# export LLM_API_KEY="sk-xxxx"
# export LLM_BASE_URL="https://api.deepseek.com/v1"
# export LLM_MODEL="deepseek-chat"

# 钉钉交互式机器人（群里 @ 出词）
# export DINGTALK_TOKEN="你的Token"
# export DINGTALK_AES_KEY="你的43位EncodingAESKey"
# export DINGTALK_RECEIVE_ID="机器人chatbotUserId"
# export DINGTALK_DEFAULT_COMPANY="艾迪亚控股集团"
# export DINGTALK_DEFAULT_PRODUCT=""

# 公网地址：配置后 @ 出词回复里会附带「完整 Word 报告」下载链接
# export PUBLIC_BASE_URL="https://geo.your-company.com"

# 端口（默认 8080）
# export PORT=8080

# 若已有实例在跑，先停掉再启动，避免端口冲突
pkill -f "keyword-miner/app.py" 2>/dev/null || true
pkill -f "/app.py" 2>/dev/null || true
sleep 1

echo "▶ 启动 GEO 选词智能体 ($(basename "$VENV_PY"))…"
exec "$VENV_PY" app.py
