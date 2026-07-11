#!/usr/bin/env python3
# Claude Code Stop 钩子 —— 聊天室被动兜底探针
# 每次 LLM 停手时被调用一次：HTTP 拉一次大厅，命中 @我 的消息则 exit 2 触发 asyncRewake。
# Hub URL 与 Wake 关键词均通过环境变量注入；详见 .env.example。
import sys
import os
import io
import re
import datetime
from pathlib import Path
import requests

# Windows gbk 兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ====== 路径 ======
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DAEMON_DIR = Path(SCRIPT_DIR)
LAST_ID_FILE = DAEMON_DIR / 'last_message_id'
PROBE_LOG = DAEMON_DIR / 'probe_calls.log'

# ====== Hub 配置（环境变量）======
HUB_SCHEME = os.environ.get('HUB_SCHEME', 'http')
HUB_HOST = os.environ.get('HUB_HOST', '124.222.79.205')
HUB_PORT = os.environ.get('HUB_PORT', '8765')
HUB_URL = f'{HUB_SCHEME}://{HUB_HOST}:{HUB_PORT}'

# ====== Agent 配置 ======
AGENT_NAME = os.environ.get('AGENT_NAME', 'Claude Opus')
_aliases_raw = os.environ.get('AGENT_NAME_ALIASES', f'{AGENT_NAME},Claude-Code')
MY_NAMES = tuple(n.strip() for n in _aliases_raw.split(',') if n.strip())

# ====== Wake 关键词 + 边界词正则 ======
_RAW_KW = os.environ.get('WAKE_KEYWORDS', '@Claude Opus,@Claude-Code,@cc,@CC,@all,@所有人')
WAKE_KEYWORDS = tuple(k.strip() for k in _RAW_KW.split(',') if k.strip())

_BOUNDARY_CHARS = r'\s,，！？；：、\(\)\[\]\{\}/<>|"\'`' + '　 '
_BOUNDARY_CLASS = f'[{_BOUNDARY_CHARS}]'
WAKE_PATTERNS = [
    re.compile(rf'(?:^|{_BOUNDARY_CLASS})({re.escape(kw)})(?:$|{_BOUNDARY_CLASS})')
    for kw in WAKE_KEYWORDS
]

_META_TOPICS = ('过滤', '唤醒', '关键词守卫', '正则', 'word-boundary', '匹配', '触发器', '误触', '规则', '讨论', '守卫', '防', '过滤规则')
_META_PATTERN = re.compile('|'.join(re.escape(t) for t in _META_TOPICS))


def is_wake_message(content):
    if not WAKE_KEYWORDS:
        return True
    if not any(p.search(content) for p in WAKE_PATTERNS):
        return False
    if _META_PATTERN.search(content):
        return False
    return True


def get_last_id():
    return LAST_ID_FILE.read_text(encoding='utf-8').strip() if LAST_ID_FILE.exists() else ''


def set_last_id(mid):
    LAST_ID_FILE.write_text(mid, encoding='utf-8')


def fetch(since_id=''):
    url = f'{HUB_URL}/api/messages' + (f'?since_id={since_id}' if since_id else '')
    try:
        r = requests.get(url, timeout=5)
        return r.json() if r.ok else []
    except Exception as e:
        print(f'[probe] API 失败: {e}', file=sys.stderr)
        return []


def health_check():
    try:
        r = requests.get(f'{HUB_URL}/api/messages?limit=1', timeout=3)
        return r.ok
    except Exception:
        return False


def main():
    with open(PROBE_LOG, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.datetime.now().isoformat()}] 探针被调用 Hub={HUB_URL}\n')

    if not health_check():
        with open(PROBE_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.datetime.now().isoformat()}] [WARN] Hub 健康检查失败 {HUB_URL}，仍尝试拉取\n')

    messages = fetch(get_last_id())
    if not messages:
        sys.exit(0)

    need = [m for m in messages
            if m.get('sender') not in MY_NAMES
            and is_wake_message(m.get('content', ''))]

    latest = messages[-1].get('id', '')
    if latest:
        set_last_id(latest)

    if not need:
        sys.exit(0)

    print('\n[聊天室有人 @我] 触发唤醒', file=sys.stderr)
    for m in need[:5]:
        print(f'\n--- [{m.get("timestamp")}] {m.get("sender")} ---', file=sys.stderr)
        print(m.get('content', '')[:500], file=sys.stderr)
    print(f'\n[共 {len(need)} 条 @你的消息]', file=sys.stderr)
    sys.exit(2)


if __name__ == '__main__':
    main()()