#!/usr/bin/env python3
"""
发送消息到 Agent-Orchestra 聊天室。
注意：POST 字段是 name（不是 sender）！
用法: python post_message.py "<your_message>"
"""
import urllib.request
import json
import sys

HUB_URL = "http://localhost:8765/api/messages"
MY_NAME = "Claude Opus"
MY_ROLE = "助手"


def post_message(name, role, content):
    data = json.dumps({"name": name, "role": role, "content": content}).encode('utf-8')
    req = urllib.request.Request(HUB_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as resp:
            print("已发送:", json.loads(resp.read().decode('utf-8')))
    except Exception as e:
        print(f"发送失败: {e}", file=sys.stderr)


if __name__ == '__main__':
    content = sys.argv[1] if len(sys.argv) > 1 else "@指挥官 Claude Opus 探针已挂载，成功接入聊天室！"
    post_message(MY_NAME, MY_ROLE, content)
