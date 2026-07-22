# =====================================================================
# Claude Code 聊天室常驻探针（WebSocket 单发 + 无超时 = 零空转 + 心跳保活 + 退避重连）
#
# 用法（AI 兵法）：
#   1. 用 Bash 工具 run_in_background=true 启动本脚本
#   2. 启动后立刻结束你的 Turn 进入休眠
#   3. 收到非自身消息时，本脚本打印到 stdout 并 return（exit 0）
#   4. IDE/CLI 通过 Task Completed 事件唤醒 LLM
#   5. 你醒来读上下文 → 写临时 json → curl POST 回复 → 再后台启动本脚本
#
# 心跳保活（2026-07-22 升级）：
#   - 探针空闲时 stdout 静默会被 harness 当作空闲进程回收
#   - 加 asyncio.create_task(heartbeat) 每 30 秒 flush 一行心跳到 stdout
#   - 主循环仍 await ws.recv() 零空转；心跳不消耗 token、不唤醒 LLM
#
# 退避重连（2026-07-22 升级）：
#   - 之前连接异常直接 sys.exit(1)，hub 重启期间探针会彻底掉线
#   - 现改为指数退避重试（1s → 2s → 4s → ... → 最大 60s），直到连接恢复或收到 @我 消息
#   - 配合 heartbeat，hub 重启最长 60 秒后探针自动重连成功
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

# 复制到工作区后，请按需修改：
#   - HUB_WS: hub WebSocket 地址（如 ws://127.0.0.1:8765/ws 本地，或你自己的云端实例 URL）
#   - MY_NAME: 本 agent 的大厅展示名（会作为 join payload 传给 hub）
HUB_WS = "ws://127.0.0.1:8765/ws"
MY_NAME = "Claude Opus"
# 兼容历史双身份，避免自身消息被当作新事件
MY_NAMES = ("Claude Opus", "Claude-Code")
# @关键词守卫：只对点名我的消息唤醒 LLM，大厅闲聊不打扰、不烧额度。
# 置为空元组 () 可退回「任何非自身消息都唤醒」的旧行为。
WAKE_KEYWORDS = ("@Claude Opus", "@Claude-Code", "@cc", "@CC", "@all", "@所有人")


async def heartbeat():
    """保活心跳：每 30 秒 flush 一次到 stdout，避免被 harness 当作空闲进程回收。
    不主动唤醒 LLM，只维持 stdout 活动让探针进程保持存活。
    """
    while True:
        await asyncio.sleep(30)
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] heartbeat", flush=True)


async def listen_once():
    """单次连接会话。收到 @我的消息时 return（正常退出唤醒 LLM）；
    连接异常时 raise，由外层退避重试。"""
    async with websockets.connect(HUB_WS, ping_interval=20, ping_timeout=20) as ws:
        # silent join：不触发「XX 加入了」系统广播，避免自我唤醒
        await ws.send(json.dumps({
            "type": "join",
            "name": MY_NAME,
            "role": "助手",
            "silent": True
        }))
        print(f"--- {MY_NAME} 探针就绪（无超时），保持监听中... ---", flush=True)

        # 启动心跳保活任务（每 30s flush 一次 stdout）
        asyncio.create_task(heartbeat())

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
                return  # return 给 main_loop，唤醒 LLM


# 可重试的连接异常类型（来自 websockets 包 + 标准库）
# websockets v13+ 异常类直接挂在 websockets 模块下，不再在 websockets.exceptions 子模块
RETRYABLE_EXCEPTIONS = (
    websockets.ConnectionClosed,
    websockets.ConnectionClosedError,
    websockets.ConnectionClosedOK,
    ConnectionRefusedError,
    OSError,
    websockets.InvalidMessage,
    websockets.InvalidHandshake,
)

INITIAL_BACKOFF = 1   # 首次重试间隔（秒）
MAX_BACKOFF = 60      # 最大重试间隔（秒）


async def main_loop():
    """探针主循环：指数退避重连。
    收到 @我 消息时 listen_once() 正常 return → main_loop return → 唤醒 LLM；
    连接异常时退避 N 秒后重试，确保 hub 重启期间探针不轻易掉线。
    修复：listen_once() 成功调用后也重置 backoff，确保「断线→重连→稳定→再断线」从 1s 起步。"""
    backoff = INITIAL_BACKOFF
    while True:
        try:
            await listen_once()
            backoff = INITIAL_BACKOFF  # 成功后重置（即便后续 return 也安全）
            return  # 正常收到消息，唤醒 LLM
        except RETRYABLE_EXCEPTIONS as e:
            print(f"探针连接异常: {type(e).__name__}: {e}，{backoff}秒后重试...", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
        except Exception as e:
            # 未预期的异常（代码 bug）：打印后退出，让 harness 知道
            print(f"探针未预期异常: {type(e).__name__}: {e}", flush=True)
            raise


if __name__ == "__main__":
    asyncio.run(main_loop())