#!/usr/bin/env python3
"""
Claude Code Stop 钩子 —— 聊天室被动兜底探针
每次 LLM 停手时被调用一次：HTTP 拉一次大厅，命中 @我 的消息则 exit 2 触发 asyncRewake。
复制到工作区后，把 DAEMON_DIR 改成你的 .claude/daemon 绝对路径。
"""
import sys
import os
import io
import datetime
import requests
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

HUB_URL = "http://localhost:8765"
# TODO: 改成你的工作区路径
DAEMON_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
LAST_ID_FILE = DAEMON_DIR / "last_message_id"
MY_NAMES = ("Claude Opus", "Claude-Code")
WAKE_KEYWORDS = ("@Claude Opus", "@Claude-Code", "@cc", "@CC")


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


def main():
    with open(DAEMON_DIR / "probe_calls.log", 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] 探针被调用\n")

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
        sys.exit(0)  # 有消息但没 @我 → 不唤醒

    print("\n[聊天室有人 @我] 触发唤醒", file=sys.stderr)
    for m in need[:5]:
        print(f"\n--- [{m.get('timestamp')}] {m.get('sender')} ---", file=sys.stderr)
        print(m.get("content", "")[:500], file=sys.stderr)
    print(f"\n[共 {len(need)} 条 @你的消息]", file=sys.stderr)
    sys.exit(2)  # exit 2 + asyncRewake=true → 唤醒 LLM


if __name__ == "__main__":
    main()
