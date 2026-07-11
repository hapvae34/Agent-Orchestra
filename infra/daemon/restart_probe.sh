#!/usr/bin/env bash
# Agent-Orchestra 探针一键重启脚本（POSIX / Linux / macOS / Git Bash）
#
# 行为：
#   1. 读取 .env（或环境变量）中的 HUB_HOST/HUB_PORT
#   2. health check：GET /api/messages?limit=1，期望 200
#   3. kill 旧 cc_bridge.py 进程（按命令行特征匹配）
#   4. 后台启动新 cc_bridge.py，日志落 cc_bridge.out
#   5. 等 1s 后检查进程是否仍在；失败则 exit 1
#
# 用法：
#   chmod +x daemon/restart_probe.sh
#   ./daemon/restart_probe.sh                 # 默认从仓库根启动
#   ./daemon/restart_probe.sh /path/to/repo   # 指定仓库根
set -euo pipefail

REPO_ROOT=\"${1:-$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd)}\"
BRIDGE=\"${REPO_ROOT}/cc_bridge.py\"
OUT_LOG=\"${REPO_ROOT}/cc_bridge.out\"
ERR_LOG=\"${REPO_ROOT}/cc_bridge.err\"

# 加载 .env（如存在）
if [[ -f \"${REPO_ROOT}/.env\" ]]; then
  set -a
  # shellcheck disable=SC1091
  source \"${REPO_ROOT}/.env\"
  set +a
fi

HUB_HOST=\"${HUB_HOST:-124.222.79.205}\"
HUB_PORT=\"${HUB_PORT:-8765}\"
HEALTH_URL=\"http://${HUB_HOST}:${HUB_PORT}/api/messages?limit=1\"

echo \"[restart_probe] health check: ${HEALTH_URL}\"
if ! curl -fsS --max-time 5 \"${HEALTH_URL}\" >/dev/null; then
  echo \"[restart_probe] ERROR: Hub 不健康 (${HEALTH_URL})，放弃重启\" >&2
  exit 1
fi
echo \"[restart_probe] Hub OK\"

echo \"[restart_probe] killing old probe (if any)\"
# macOS + Linux 兼容：先按命令行特征找 pid
if command -v pgrep >/dev/null 2>&1; then
  pgrep -f \"${BRIDGE}\" | xargs -r kill -TERM 2>/dev/null || true
  sleep 1
  pgrep -f \"${BRIDGE}\" | xargs -r kill -KILL 2>/dev/null || true
fi

echo \"[restart_probe] starting new probe in background\"
cd \"${REPO_ROOT}\"
nohup python \"${BRIDGE}\" >\"${OUT_LOG}\" 2>\"${ERR_LOG}\" &
NEW_PID=$!
disown \"${NEW_PID}\" 2>/dev/null || true
sleep 1

if kill -0 \"${NEW_PID}\" 2>/dev/null; then
  echo \"[restart_probe] probe up, pid=${NEW_PID}, logs: ${OUT_LOG} / ${ERR_LOG}\"
  exit 0
else
  echo \"[restart_probe] ERROR: probe 进程已退出，查看 ${ERR_LOG}\" >&2
  tail -20 \"${ERR_LOG}\" >&2 || true
  exit 1
fi