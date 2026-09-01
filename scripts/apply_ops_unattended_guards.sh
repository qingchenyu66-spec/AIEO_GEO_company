#!/bin/bash
# 把 deploy/ops 里的 UU 黑名单 + needrestart 保护应用到本机（生产）。
# 用法：cd /opt/geo/AIEO_GEO && bash scripts/apply_ops_unattended_guards.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
install -m 644 "$ROOT/deploy/ops/99geo-unattended-upgrades" /etc/apt/apt.conf.d/99geo-unattended-upgrades
install -d /etc/needrestart/conf.d
install -m 644 "$ROOT/deploy/ops/needrestart-geo.conf" /etc/needrestart/conf.d/geo.conf
echo "OK: UU blacklist + needrestart overrides installed"
echo "--- UU blacklist ---"
grep -A20 'Package-Blacklist' /etc/apt/apt.conf.d/99geo-unattended-upgrades | head -20
echo "--- needrestart geo ---"
cat /etc/needrestart/conf.d/geo.conf
