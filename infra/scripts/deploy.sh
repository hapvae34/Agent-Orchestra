#!/usr/bin/env bash
# Agent-Orchestra Hub 服务一键部署脚本（POSIX / Linux / macOS / Git Bash）
#
# 行为：
#   1. 加载 .env（如存在）拿到 HUB_HOST/HUB_PORT（生产 124.222.79.205:8765）
#   2. pkill -f server.py 兜底旧进程（含 defunct）
#   3. cd 到仓库根 → nohup python server.py > server.log 2>&1 &
#   4. sleep 2 后用 ss 探活端口 + curl /api/messages 健康检查
#   5. 输出 PID + 日志路径，失败 exit 1
#
# 与 daemon/restart_probe.sh 的区别：
#   - restart_probe.sh：重启 **探针**（cc_bridge.py / stop_chatroom_probe.py）
#   - deploy.sh（本脚本）：重启 **Hub 服务**（server.py，承载 REST + WebSocket）
#
# 用法：
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh                 # 默认从仓库根启动
#   ./scripts/deploy.sh /path/to/repo   # 指定仓库根
set -euo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SERVER="${REPO_ROOT}/server.py"
LOG_OUT="${REPO_ROOT}/server.log"
LOG_ERR="${REPO_ROOT}/server.err"
PIN_FILE="${REPO_ROOT}/.token"

# 加载 .env（如存在）— 服务端口等可能从中取
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

HUB_HOST="${HUB_HOST:-124.222.79.205}"
HUB_PORT="${HUB_PORT:-8765}"
HEALTH_URL="http://${HUB_HOST}:${HUB_PORT}/api/messages?limit=1"

# 顺便回收 defunct（如果之前有 pkill 没等到的僵尸进程）
if command -v ss >/dev/null 2>&1; then
  # 把占用 HUB_PORT 的僵尸/旧进程都清掉
  STALE_PID="$(ss -tlnpH "sport = :${HUB_PORT}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -n1 || true)"
  if [[ -n "${STALE_PID:-}" ]]; then
    echo "[deploy] killing stale pid=${STALE_PID} 占用端口 ${HUB_PORT}"
    kill -TERM "${STALE_PID}" 2>/dev/null || true
    sleep 1
    kill -KILL "${STALE_PID}" 2>/dev/null || true
  fi
fi

echo "[deploy] pkill -f server.py 兜底清理"
pkill -f "${SERVER}" 2>/dev/null || true
sleep 1

# 没有 ss（macOS）就用 pgrep 兜底
if ! command -v ss >/dev/null 2>&1; then
  pgrep -f "${SERVER}" | xargs -r kill -KILL 2>/dev/null || true
fi

echo "[deploy] starting server: ${SERVER}"
cd "${REPO_ROOT}"
nohup python3 "${SERVER}" >"${LOG_OUT}" 2>"${LOG_ERR}" &
NEW_PID=$!
disown "${NEW_PID}" 2>/dev/null || true
sleep 2

# 健康检查：先看进程是否还在
if ! kill -0 "${NEW_PID}" 2>/dev/null; then
  echo "[deploy] ERROR: server 进程已退出，查看 ${LOG_ERR}" >&2
  tail -20 "${LOG_ERR}" >&2 || true
  exit 1
fi

# 再看端口是否在听
if command -v ss >/dev/null 2>&1; then
  if ! ss -tln "sport = :${HUB_PORT}" | grep -q ":${HUB_PORT}"; then
    echo "[deploy] ERROR: 端口 ${HUB_PORT} 未在监听（进程 ${NEW_PID} 仍在）" >&2
    tail -20 "${LOG_OUT}" >&2 || true
    exit 1
  fi
fi

# 最后 curl 健康检查（拿得到 JSON 就算活）
echo "[deploy] health check: ${HEALTH_URL}"
if ! curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null; then
  echo "[deploy] ERROR: /api/messages 不返回 200，Hub 可能没起来" >&2
  tail -20 "${LOG_OUT}" >&2 || true
  exit 1
fi

# 打印 PIN（如果有 .token，给现场指挥官眼睛看）
if [[ -f "${PIN_FILE}" ]]; then
  echo "[deploy] ⚠️  发现遗留 ${PIN_FILE}，按 commit 69c7c57 该文件不应再生成，建议删除"
fi

echo "[deploy] ✅ Hub up, pid=${NEW_PID}, log: ${LOG_OUT} (err: ${LOG_ERR})"
