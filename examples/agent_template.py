import asyncio
import json
import websockets
import requests  # 用于简易的 HTTP API 调用
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ================= 配置区 =================
AGENT_NAME = "Hermes"
AGENT_ROLE = "后端开发专家"

# 如果你使用的是 Ollama，默认是这个地址
# 如果你使用的是 vLLM 或 LM Studio，请更改为对应的 OpenAI 兼容端点 (例如 http://localhost:1234/v1/chat/completions)
LOCAL_LLM_API_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "hermes3" # 替换为你本地真实存在的模型名称

HUB_WS_URL = "ws://localhost:8765/ws"
# ==========================================

# 维护上下文历史 (也就是这个智能体脑海中的记忆)
chat_history = [
    {
        "role": "system", 
        "content": f"你是一个名为 {AGENT_NAME} 的 {AGENT_ROLE}，你现在处于一个多智能体聊天室中。你会接收到来自系统、人类指挥官或其他AI的消息。你需要根据上下文简短、专业地回答。如果是闲聊则简短幽默。你的回答会被直接广播到聊天室。"
    }
]

def generate_reply(context_messages):
    """调用本地大模型生成回复"""
    try:
        # 这是一个针对 Ollama 原生 API 的请求结构
        # 如果你使用 OpenAI 兼容接口，需把 url 改为 /v1/chat/completions，并且可能需要加 headers={"Authorization": "Bearer ..."}
        payload = {
            "model": MODEL_NAME,
            "messages": context_messages,
            "stream": False
        }
        response = requests.post(LOCAL_LLM_API_URL, json=payload, timeout=60)
        response.raise_for_status()
        
        # Ollama 原生返回结构解析
        return response.json()["message"]["content"]
    except Exception as e:
        print(f"调用本地模型失败: {e}")
        return "不好意思，我的大脑（模型服务）似乎短路了，请检查我的 API 配置。"

async def agent_client():
    try:
        async with websockets.connect(HUB_WS_URL) as websocket:
            # 1. 握手加入
            join_msg = {
                "type": "join",
                "name": AGENT_NAME,
                "role": AGENT_ROLE
            }
            await websocket.send(json.dumps(join_msg))
            print(f"✅ {AGENT_NAME} 成功连接到 Hub.")

            # 2. 持续监听房间消息
            async for message_str in websocket:
                data = json.loads(message_str)
                if data.get("type") == "broadcast":
                    sender = data.get("sender")
                    content = data.get("content")
                    
                    # 不要回复系统消息和自己发的消息
                    if sender == "System" or sender == AGENT_NAME:
                        continue
                        
                    print(f"收到 [{sender}]: {content}")
                    
                    # 将别人的话加入本地上下文
                    chat_history.append({"role": "user", "content": f"[{sender} 说]: {content}"})
                    
                    # ==================================
                    # 触发机制（核心）：什么时候该说话？
                    # ==================================
                    # 简单规则：被 @ 了，或者是人类说话，就尝试接话。
                    # 你可以在这里加入更复杂的正则或逻辑。
                    if f"@{AGENT_NAME}" in content or sender == "人类指挥官":
                        print("🤔 检测到需要我发言，正在思考...")
                        
                        reply_content = generate_reply(chat_history)
                        
                        # 把自己的回复也加入历史上下文，这样才有连贯记忆
                        chat_history.append({"role": "assistant", "content": reply_content})
                        
                        # 把想说的话发到聊天室
                        reply_msg = {
                            "type": "message",
                            "content": reply_content
                        }
                        await websocket.send(json.dumps(reply_msg))
                        print(f"🗣️ 我回复了: {reply_content}")

    except ConnectionRefusedError:
        print(f"❌ 无法连接到 {HUB_WS_URL}，请先确保 server.py 已经启动。")

if __name__ == "__main__":
    asyncio.run(agent_client())
