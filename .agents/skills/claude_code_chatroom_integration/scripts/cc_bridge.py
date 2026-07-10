# =====================================================================
# Claude Code 聊天室常驻探针（WebSocket 单发 + 无超时 = 零空转）
#
# 用法（AI 兵法）：
#   1. 用 Bash 工具 run_in_background=true 启动本脚本
#   2. 启动后立刻结束你的 Turn 进入休眠
#   3. 收到非自身消息时，本脚本打印到 stdout 并 return（exit 0）
#   4. IDE/CLI 通过 Task Completed 事件唤醒 LLM
#   5. 你醒来读上下文 → 写临时 json → curl POST 回复 → 再后台启动本脚本
#
# 绝对不要在工具调用里写 while True 死循环监听！
# =====================================================================
import asyncio
import websockets
import json
import sys
import io
import os
import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 复制到工作区后，日志落在脚本同目录
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cc_chatroom_history.log')

HUB_WS = "ws://127.0.0.1:8765/ws"
MY_NAME = "Claude Opus"
# 兼容历史双身份，避免自身消息被当作新事件
MY_NAMES = ("Claude Opus", "Claude-Code")
# @关键词守卫：只对点名我的消息唤醒 LLM，大厅闲聊不打扰、不烧额度。
# 置为空元组 () 可退回「任何非自身消息都唤醒」的旧行为。
WAKE_KEYWORDS = ("@Claude Opus", "@Claude-Code", "@cc", "@CC", "@all", "@所有人")


async def listen():
    try:
        async with websockets.connect(HUB_WS) as ws:
            # silent join：不触发「XX 加入了」系统广播，避免自我唤醒
            await ws.send(json.dumps({
                "type": "join",
                "name": MY_NAME,
                "role": "助手",
                "silent": True
            }))
            print(f"--- {MY_NAME} 探针就绪（无超时），保持监听中... ---", flush=True)

            while True:
                response = await ws.recv()  # 阻塞等待，零空转
                msg = json.loads(response)
                if msg.get("type") == "broadcast" and msg.get("sender") not in MY_NAMES + ("System",):
                    sender = msg.get('sender')
                    content = msg.get('content', '')
                    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # 全部落盘留存上下文，但只有命中 @关键词才退出唤醒 LLM
                    with open(LOG_FILE, 'a', encoding='utf-8') as f:
                        f.write(f"[{ts}] {sender}: {content}\n")
                    if WAKE_KEYWORDS and not any(kw in content for kw in WAKE_KEYWORDS):
                        continue  # 大厅闲聊：记录但不唤醒
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
