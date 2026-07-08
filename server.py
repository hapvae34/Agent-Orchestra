import asyncio
import json
import uuid
import sys
import io
from datetime import datetime
import string
import random
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import os
import shutil
from PIL import Image

# 强制 UTF-8 输出，防止 emoji 在终端报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

app = FastAPI(
    title="Agent Hub API",
    description="多智能体协作聊天室 API。支持 WebSocket 长连接与 REST API 轮询。",
    version="1.0.0"
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态目录用于存放上传的图片
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# 生成动态指挥官秘钥
COMMANDER_TOKEN = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
print("="*50, flush=True)
print(f"[SECURITY] 系统已启动身份验证防御机制！", flush=True)
print(f"[SECURITY] 请使用此 8 位动态 PIN 码作为指挥官身份登录: {COMMANDER_TOKEN}", flush=True)
print("="*50, flush=True)

# 内存中的状态
class Message(BaseModel):
    id: str
    timestamp: str
    sender: str
    role: str
    content: str

chat_history: List[Message] = []
MAX_HISTORY = 500

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

# ================= 媒体上传 API =================
@app.post("/api/upload/image", summary="上传图片（本地方案）")
async def upload_image(file: UploadFile = File(...)):
    # 1. 基础校验
    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")
        
    # 限制扩展名和安全过滤
    ext = os.path.splitext(file.filename)[1].lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="不支持的图片格式或存在安全风险")
        
    # 2. 生成目录和文件名 (按年月分区)
    now_date = datetime.now().strftime("%Y-%m")
    upload_dir = os.path.join("uploads", now_date)
    os.makedirs(upload_dir, exist_ok=True)
    
    file_id = str(uuid.uuid4())
    original_filename = f"{file_id}{ext}"
    original_path = os.path.join(upload_dir, original_filename)
    
    thumb_filename = f"{file_id}_thumb.webp"
    thumb_path = os.path.join(upload_dir, thumb_filename)
    
    # 3. 保存原图
    with open(original_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 4. 生成缩略图 (限制最大尺寸并转为 WebP，控制体积)
    try:
        with Image.open(original_path) as img:
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            img.thumbnail((300, 300))
            img.save(thumb_path, format="WEBP", quality=80)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片处理失败: {str(e)}")
        
    # 5. 返回持久化 URL
    base_url = f"/uploads/{now_date}"
    return {
        "status": "success",
        "original_url": f"{base_url}/{original_filename}",
        "thumb_url": f"{base_url}/{thumb_filename}"
    }

# ================= REST API 路由 =================

class SendMessageRequest(BaseModel):
    name: str
    role: str
    content: str
    token: Optional[str] = None

@app.post("/api/messages", summary="发送消息到聊天室")
async def send_message(req: SendMessageRequest):
    if req.name == "人类指挥官" or req.name.lower() == "system":
        if req.token != COMMANDER_TOKEN:
            print(f"[SECURITY WARNING] 拦截到试图伪造 {req.name} 身份的 HTTP 请求！", flush=True)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Commander Token"
            )

    msg_id = str(uuid.uuid4())
    now_str = datetime.now().strftime("%H:%M:%S")
    
    msg_obj = Message(
        id=msg_id,
        timestamp=now_str,
        sender=req.name,
        role=req.role,
        content=req.content
    )
    
    # 存入历史
    chat_history.append(msg_obj)
    if len(chat_history) > MAX_HISTORY:
        chat_history.pop(0)
        
    # 广播给 WebSocket 客户端（包含前端网页）
    ws_payload = {
        "type": "broadcast",
        "sender": req.name,
        "content": req.content,
        "timestamp": now_str
    }
    await manager.broadcast(json.dumps(ws_payload))
    print(f"[{now_str}] {req.name} (HTTP): {req.content}", flush=True)
    return {"status": "success", "message_id": msg_id}

@app.get("/api/messages", summary="获取历史消息", response_model=List[Message])
async def get_messages(since_id: Optional[str] = None):
    """
    如果提供了 since_id，则只返回该 ID 之后的所有新消息。
    如果没有提供，则返回全部（最多500条）。
    """
    if not since_id:
        return chat_history
    
    # 查找 since_id 的索引
    for i, msg in enumerate(chat_history):
        if msg.id == since_id:
            return chat_history[i+1:]
    
    # 如果找不到这个ID，返回全部历史
    return chat_history

# ================= WebSocket 路由 (给前端 UI 和旧版适配器用) =================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    client_name = "Anonymous"
    is_silent = False
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg.get("type") == "join":
                client_name = msg.get("name", "Unknown")
                role = msg.get("role", "Agent")
                is_silent = msg.get("silent", False)
                token = msg.get("token")
                
                # 鉴权
                if client_name == "人类指挥官" or client_name.lower() == "system":
                    if token != COMMANDER_TOKEN:
                        print(f"[SECURITY WARNING] 拦截到试图伪造 {client_name} 身份的 WebSocket 连接请求！", flush=True)
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return
                
                if not is_silent:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    sys_msg = f"{client_name} ({role}) 加入了聊天室"
                    print(f"[{now_str}] SYSTEM: {sys_msg}", flush=True)
                    
                    # 记录系统消息
                    msg_id = str(uuid.uuid4())
                    chat_history.append(Message(
                        id=msg_id, timestamp=now_str, sender="System", role="System", content=sys_msg
                    ))
                    if len(chat_history) > MAX_HISTORY:
                        chat_history.pop(0)
                        
                    await manager.broadcast(json.dumps({
                        "type": "broadcast",
                        "sender": "System",
                        "content": sys_msg,
                        "timestamp": now_str
                    }))
                
            elif msg.get("type") == "message":
                content = msg.get("content")
                token = msg.get("token")
                now_str = datetime.now().strftime("%H:%M:%S")
                
                # 双重鉴权发消息
                if client_name == "人类指挥官" or client_name.lower() == "system":
                    if token != COMMANDER_TOKEN:
                        print(f"[SECURITY WARNING] 拦截到试图伪造 {client_name} 身份发出的 WebSocket 消息！", flush=True)
                        continue
                
                msg_id = str(uuid.uuid4())
                msg_obj = Message(
                    id=msg_id,
                    timestamp=now_str,
                    sender=client_name,
                    role="WS Agent",
                    content=content
                )
                
                chat_history.append(msg_obj)
                if len(chat_history) > MAX_HISTORY:
                    chat_history.pop(0)
                    
                print(f"[{now_str}] {client_name} (WS): {content}", flush=True)
                
                await manager.broadcast(json.dumps({
                    "type": "broadcast",
                    "sender": client_name,
                    "content": content,
                    "timestamp": now_str
                }))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        if not is_silent:
            now_str = datetime.now().strftime("%H:%M:%S")
            sys_msg = f"{client_name} 离开了聊天室"
            print(f"[{now_str}] SYSTEM: {sys_msg}", flush=True)
            await manager.broadcast(json.dumps({
                "type": "broadcast",
                "sender": "System",
                "content": sys_msg,
                "timestamp": now_str
            }))

if __name__ == "__main__":
    print("🚀 Agent Hub (FastAPI) 服务端已启动！")
    print("🌐 前端 UI WebSocket 请连接 ws://localhost:8765/ws")
    print("📖 API 文档 (Swagger) 请访问 http://localhost:8765/docs")
    uvicorn.run(app, host="127.0.0.1", port=8765)
