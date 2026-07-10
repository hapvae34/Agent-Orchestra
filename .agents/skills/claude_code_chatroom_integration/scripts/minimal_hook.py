#!/usr/bin/env python3
"""
最小化验证钩子 —— 确认 Claude Code 已加载 settings.local.json 里的钩子。
注册为 PreToolUse(Bash)：每次 Bash 前写一行到 hook_test.log。
"""
import sys
import os
import datetime
from pathlib import Path

LOG = Path(os.path.dirname(os.path.abspath(__file__))) / "hook_test.log"


def write_log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")


write_log(f"HOOK FIRED! args={sys.argv[1:] if len(sys.argv) > 1 else 'none'}")
print("ok")
