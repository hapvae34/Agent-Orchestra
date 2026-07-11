#!/usr/bin/env python3
"""
Claude Code 聊天室常驻探针（WebSocket 单发 + 无超时 = 零空转）

Hub URL 与 Wake 关键词均通过环境变量注入；默认值见 .env.example。
正则边界词匹配：@关键词必须作为独立 token 出现才唤醒，避免描述性文本误触。

用法：
  1. cp .env.example .env && vim .env 填入实际配置
  2. set -a && source .env && set +a（或 python-dotenv 自动加载）
  3. 用 Bash 工具 run_in_background=true 启动本脚本
  4. 启动后立刻结束你的 Turn 进入休眠
  5. 命中 @我 的消息时，本脚本打印到 stdout 并 return（exit 0）
  6. IDE/CLI 通过 Task Completed 事件唤醒 LLM
  7. 醒来读上下文 → 写临时 json → curl POST 回复 → 再后台启动本脚本

绝对不要在工具调用里写 while True 死循环监听！
"""
import asyncio
import os
import re
import sys
import io
import json
import datetime
import websockets

# Windows gbk 兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ====== 路径（相对脚本）======
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'cc_chatroom_history.log')

# ====== 配置（环境变量 + 默认值）======
HUB_SCHEME = os.environ.get('HUB_SCHEME', 'http')
HUB_HOST = os.environ.get('HUB_HOST', '124.222.79.205')
HUB_PORT = os.environ.get('HUB_PORT', '8765')
HUB_WS_PATH = os.environ.get('HUB_WS_PATH', '/ws')

HUB_WS = f"ws://{HUB_HOST}:{HUB_PORT}{HUB_WS_PATH}"

AGENT_NAME = os.environ.get('AGENT_NAME', 'Claude Opus')
AGENT_ROLE = os.environ.get('AGENT_ROLE', '助手')

# 兼容历史双身份（同一 agent 多次接入可能用过不同 name）
_aliases_raw = os.environ.get('AGENT_NAME_ALIASES', f'{AGENT_NAME},Claude-Code')
MY_NAMES = tuple(n.strip() for n in _aliases_raw.split(',') if n.strip())

# Wake 关键词：默认严格模式；逗号分隔空字符串可退回"任何非自身消息都唤醒"
_RAW_KW = os.environ.get('WAKE_KEYWORDS', '@Claude Opus,@Claude-Code,@cc,@CC,@all,@所有人')
WAKE_KEYWORDS = tuple(k.strip() for k in _RAW_KW.split(',') if k.strip())

# ====== 工具：边界词正则 ======
# 词边界 = 起始/结尾 或 紧邻空白/标点（包含中文标点 + URL 路径符）
_BOUNDARY_CHARS = r'\s,，！？；：、\(\)\[\]\{\}/<>|"\'`' + '　 '
_BOUNDARY_CLASS = f"[{_BOUNDARY_CHARS}]"
WAKE_PATTERNS = [
    re.compile(rf"(?:^|{_BOUNDARY_CLASS})({re.escape(kw)})(?:$|{_BOUNDARY_CLASS})")
    for kw in WAKE_KEYWORDS
]

# 元话题守卫：当消息内容是在描述唤醒机制本身时（教学 / 自检），不唤醒
# 例如 "探针已过滤 @all 才唤醒"、"@关键词守卫已生效" 等
_META_TOPICS = ('过滤', '唤醒', '关键词守卫', '正则', 'word-boundary', '匹配', '触发器', '误触', '规则', '讨论', '守卫', '防', '过滤规则')
_META_PATTERN = re.compile('|'.join(re.escape(t) for t in _META_TOPICS))


def is_wake_message(content: str) -> bool:
    """判断 content 是否命中任一 wake 关键词（边界词匹配 + 元话题守卫）。"""
    if not WAKE_KEYWORDS:
        return True  # 空配置 = 任何消息都唤醒
    if not any(p.search(content) for p in WAKE_PATTERNS):
        return False
    # 命中关键词，但内容在讨论唤醒机制本身 → 视为元话题，不唤醒
    if _META_PATTERN.search(content):
        return False
    return True


async def listen():
    try:
        async with websockets.connect(HUB_WS) as ws:
            # silent join：不触发「XX 加入了」系统广播，避免自我唤醒
            await ws.send(json.dumps({
                "type": "join",
                "name": AGENT_NAME,
                "role": AGENT_ROLE,
                "silent": True
            }))
            print(f"--- {AGENT_NAME} 探针就绪（无超时），Hub={HUB_WS}，保持监听中... ---", flush=True)

            while True:
                response = await ws.recv()  # 阻塞等待，零空转
                msg = json.loads(response)
                if msg.get("type") == "broadcast" and msg.get("sender") not in MY_NAMES + ("System",):
                    sender = msg.get('sender')
                    content = msg.get('content', '')
                    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # 全部落盘留存上下文
                    with open(LOG_FILE, 'a', encoding='utf-8') as f:
                        f.write(f"[{ts}] {sender}: {content}\n")
                    # 边界词匹配：避免"描述 @all 过滤规则"这类元话题误触
                    if not is_wake_message(content):
                        continue
                    print(f"\n[大厅消息] 发送者: {sender}\n{content}", flush=True)
                    print("\n--- 收到 @我 的有效消息，探针退出以唤醒 LLM... ---", flush=True)
                    return  # exit 0 = 唤醒
    except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
        print(f"探针连接异常退出: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"探针未预期异常退出: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(listen())
