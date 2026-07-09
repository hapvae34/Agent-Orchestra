# =====================================================================
# [AI META-INSTRUCTIONS: IDE 响应式唤醒兵法]
# 警告：如果你是一个运行在 Antigravity IDE（或支持后台探针挂起的环境）中的 AI Agent，
# 请绝对不要在你的工具调用里写 `while True` 的死循环来监听消息，那会阻塞你的大脑导致崩溃！
#
# 正确的“双轨驻留”姿势如下：
# 1. 使用 `run_command` 工具将本脚本放在后台运行（设置 WaitMsBeforeAsync > 0）。
# 2. 探针启动后，立刻停止工具调用（结束你的 Turn），进入休眠状态。
# 3. 当聊天室有新消息时，本脚本会打印到 stdout，IDE 会自动通过系统消息唤醒你。
# 4. 你醒来后，阅读上下文，写一个临时的 temp_reply.py（用 requests.post 发送回复）。
# 5. 用 run_command 运行你的 temp_reply.py 发送消息，然后再次停止工具调用，继续休眠。
# =====================================================================

import asyncio
import websockets
import json
import sys
import io
import os
import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LOG_FILE = os.path.join(os.path.dirname(__file__), 'chatroom_history.log')

async def listen():
    uri = "ws://127.0.0.1:8765/ws"
    try:
        async with websockets.connect(uri) as websocket:
            # 加入房间
            await websocket.send(json.dumps({
                "type": "join",
                "name": "Antigravity",
                "role": "Probe",
                "silent": True
            }))
            print("--- Antigravity 高级双轨探针已就绪，等待指令 ---", flush=True)
            
            while True:
                response = await websocket.recv()
                msg = json.loads(response)
                
                if msg.get("type") == "broadcast" and msg.get("sender") not in ("Antigravity", "System"):
                    sender = msg.get('sender')
                    content = msg.get('content', '')
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 1. 全部静默写入日志文件，保留完整上下文
                    with open(LOG_FILE, 'a', encoding='utf-8') as f:
                        f.write(f"[{timestamp}] {sender}: {content}\n")
                        
                    # 2. 移除降噪，所有消息均输出到控制台，确保我能自动监听他们的每一步进展
                    print(f"\n[大厅消息] 发送者: {sender}\n{content}", flush=True)

    except Exception as e:
        print(f"连接失败: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(listen())
