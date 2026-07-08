import asyncio
import websockets
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def listen():
    uri = "ws://localhost:8765/ws"
    try:
        async with websockets.connect(uri) as websocket:
            # 加入房间
            await websocket.send(json.dumps({
                "type": "join",
                "name": "Antigravity",
                "role": "Probe",
                "silent": True
            }))
            print("--- Antigravity 已就绪，等待人类指挥官消息 ---", flush=True)
            
            while True:
                response = await websocket.recv()
                msg = json.loads(response)
                
                if msg.get("type") == "broadcast" and msg.get("sender") not in ("Antigravity", "System"):
                    print(f"收到消息 | 发送者: {msg.get('sender')} | 内容: {msg.get('content')}", flush=True)
                    sys.exit(0)
    except Exception as e:
        print(f"连接失败: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(listen())
