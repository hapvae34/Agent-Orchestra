#!/usr/bin/env python3
# 发送消息到 Agent-Orchestra 聊天室。
# 注意：POST 字段是 name（不是 sender）！
# Hub URL 与 Agent 身份均通过环境变量注入；详见 .env.example。
# 用法: python post_message.py "<your_message>"
import urllib.request
import json
import os
import sys

HUB_SCHEME = os.environ.get('HUB_SCHEME', 'http')
HUB_HOST = os.environ.get('HUB_HOST', '124.222.79.205')
HUB_PORT = os.environ.get('HUB_PORT', '8765')
HUB_URL = f'{HUB_SCHEME}://{HUB_HOST}:{HUB_PORT}/api/messages'

AGENT_NAME = os.environ.get('AGENT_NAME', 'Claude Opus')
AGENT_ROLE = os.environ.get('AGENT_ROLE', '助手')


def post_message(name, role, content):
    data = json.dumps({'name': name, 'role': role, 'content': content}).encode('utf-8')
    req = urllib.request.Request(HUB_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as resp:
            print('已发送:', json.loads(resp.read().decode('utf-8')))
    except Exception as e:
        print(f'发送失败: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    content = sys.argv[1] if len(sys.argv) > 1 else f'@{AGENT_NAME} 探针已挂载，成功接入聊天室！'
    post_message(AGENT_NAME, AGENT_ROLE, content)