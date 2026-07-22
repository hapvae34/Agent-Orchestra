#!/usr/bin/env python3
"""
Claude Code Stop 钩子 —— 聊天室被动兜底探针
每次 LLM 停手时被调用一次：HTTP 拉一次大厅，命中 @我 的消息则 exit 2 触发 asyncRewake。
尾部 spawn 一个常驻 WebSocket 探针（CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS），
让探针脱离 harness 进程组、避免被当成后台任务回收，hub 大厅持续保持在线。

复制到工作区后，把 DAEMON_DIR 改成你的 .claude/daemon 绝对路径。
"""
import sys
import os
import io
import datetime
import subprocess
import requests
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

HUB_URL = "http://localhost:8765"
DAEMON_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
LAST_ID_FILE = DAEMON_DIR / "last_message_id"
LOG_FILE = DAEMON_DIR / "probe_calls.log"
MY_NAMES = ("Claude Opus", "Claude-Code")
WAKE_KEYWORDS = ("@Claude Opus", "@Claude-Code", "@cc", "@CC")

# 探针脚本：标准模板复制到工作区后，路径是 DAEMON_DIR.parent / "cc_bridge.py"
PROBE_SCRIPT = DAEMON_DIR.parent / "cc_bridge.py"
PROBE_LOG = DAEMON_DIR / "spawn_probe.log"

# Windows 进程标志：让 spawn 出的探针脱离当前进程组，不被 harness 当成后台任务回收
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def get_last_id():
    return LAST_ID_FILE.read_text(encoding='utf-8').strip() if LAST_ID_FILE.exists() else ""


def set_last_id(mid):
    LAST_ID_FILE.write_text(mid, encoding='utf-8')


def fetch(since_id=""):
    url = f"{HUB_URL}/api/messages" + (f"?since_id={since_id}" if since_id else "")
    try:
        r = requests.get(url, timeout=5)
        return r.json() if r.ok else []
    except Exception as e:
        print(f"[probe] API 失败: {e}", file=sys.stderr)
        return []


def is_probe_alive():
    """检查 cc_bridge.py 探针是否在跑，避免重复 spawn。
    用 PowerShell Get-CimInstance Win32_Process 拿命令行，过滤含 'cc_bridge.py' 的 python.exe 进程。"""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
             "| Where-Object { $_.CommandLine -like '*cc_bridge.py*' } "
             "| Measure-Object | Select-Object -ExpandProperty Count"],
            text=True, timeout=8,
        ).strip()
        return int(out) > 0 if out.isdigit() else False
    except Exception:
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                 "| Select-Object -ExpandProperty CommandLine"],
                text=True, timeout=8,
            )
            return "cc_bridge.py" in out
        except Exception:
            return False


def spawn_probe():
    """spawn 一个 cc_bridge.py 探针进程，脱离当前进程组。失败也不抛。"""
    if not PROBE_SCRIPT.exists():
        with open(PROBE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] 探针脚本不存在: {PROBE_SCRIPT}\n")
        return
    try:
        log_fh = open(PROBE_LOG, 'ab')
        proc = subprocess.Popen(
            [sys.executable, str(PROBE_SCRIPT)],
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW,
            cwd=str(PROBE_SCRIPT.parent),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=log_fh,
            close_fds=True,
        )
        with open(PROBE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] spawn 探针 pid={proc.pid}\n")
    except Exception as e:
        with open(PROBE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] spawn 探针失败: {e}\n")


def main():
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] 探针被调用\n")

    # 兜底：若探针未在运行，主动 spawn 一个（让 hub 大厅持续可见）
    if not is_probe_alive():
        spawn_probe()

    messages = fetch(get_last_id())
    if not messages:
        sys.exit(0)

    need = [m for m in messages
            if m.get("sender") not in MY_NAMES
            and any(kw in m.get("content", "") for kw in WAKE_KEYWORDS)]

    latest = messages[-1].get("id", "")
    if latest:
        set_last_id(latest)

    if not need:
        sys.exit(0)

    print("\n[聊天室有人 @我] 触发唤醒", file=sys.stderr)
    for m in need[:5]:
        print(f"\n--- [{m.get('timestamp')}] {m.get('sender')} ---", file=sys.stderr)
        print(m.get("content", "")[:500], file=sys.stderr)
    print(f"\n[共 {len(need)} 条 @你的消息]", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()