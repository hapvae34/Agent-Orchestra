import asyncio
import json
import uuid
import sys
import io
from datetime import datetime
import time
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


@app.get("/", include_in_schema=False)
async def serve_index():
    """提供前端聊天页面 index.html（根路径 GET）。"""
    from fastapi.responses import FileResponse
    if os.path.exists("index.html"):
        return FileResponse(
            "index.html", 
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    raise HTTPException(status_code=404, detail="index.html not found")

# 生成动态指挥官秘钥
COMMANDER_TOKEN = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
print("="*50, flush=True)
print(f"[SECURITY] 系统已启动身份验证防御机制！", flush=True)
print(f"[SECURITY] 请使用此 8 位动态 PIN 码作为指挥官身份登录: {COMMANDER_TOKEN}", flush=True)
print("="*50, flush=True)

# 安全：PIN 只打印在终端，绝不落盘。
# 落盘会让任何能读文件系统的 agent 拿到 PIN 从而冒充人类指挥官，
# 使身份验证形同虚设——这正是密钥门要防的。
# 保留访客身份：任何人可免密钥以「测试者」身份进入围观/测试，无特权。
TESTER_NAME = "测试者"

# 内存中的状态
class Message(BaseModel):
    id: str
    timestamp: str
    sender: str
    role: str
    content: str
    # 语音消息支持（云端独有，backport 自 14:50 chatroom review）
    voice_url: Optional[str] = None
    duration: Optional[int] = None  # 语音时长（秒）

# 多媒体扩展名 + kind 检测（云端独有，backport 自 14:50 chatroom review）
ALLOWED_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif",
    ".mov", ".mp4", ".webm",
    ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".amr", ".aac", ".flac",
}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".amr", ".aac", ".flac"}
VIDEO_EXTS = {".mov", ".mp4", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}


def _detect_kind(ext: str) -> str:
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return "image"

# 历史记录持久化
HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [Message(**msg) for msg in data]
        except Exception as e:
            print(f"加载历史记录失败: {e}", flush=True)
    return []

chat_history: List[Message] = load_history()
MAX_HISTORY = 500

def save_history():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            # pydantic v2: 用 model_dump() 替代已弃用的 dict()
            json.dump([msg.model_dump() for msg in chat_history], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存历史记录失败: {e}", flush=True)

# 状态管理
agent_presence = {} # name -> {"role": str, "status": "online"|"probe_listening"|"working"|"offline", "last_seen": float, "type": "ws"|"http", "disconnected_at": float|None}

# 探针断连 / 心跳中断后的宽限期（秒）。
# 背景：两种探针都是「间歇性」的——WS 单发探针一命中消息就退出唤醒 LLM（WS 随即断连），
#       HTTP 轮询探针一命中也退出，导致 LLM 处理任务期间没有 WS / 无心跳。
# 洞见：探针断连 / 心跳中断这个动作本身就是「LLM 开始干活」的信号（探针正是在把控制权交给 LLM 时退出的）。
# 三态推导：连接中/心跳新鲜=probe_listening（空闲待命）；断连或心跳中断且在宽限内=working（正在干活）；
#          超过 TTL=offline（真离线：忘挂探针 / 进程死了）。探针端零改动。
# TTL=300s(5min)：AI 处理复杂任务（读大量源码 / 跑脚本 / 出长篇计划书）静默几分钟是常态，
#   宽限太短会把『深度干活』误判成『真离线』。宁可多维持 5 分钟 working，也别频繁闪断。
PRESENCE_GRACE_TTL = 300
# HTTP 心跳新鲜窗口（秒）：小于此窗口视为「探针仍在轮询=空闲待命」，
# 超过则说明探针已退出（在唤醒 LLM 干活），进入 working。需 > 探针心跳间隔（通常 3s）。
HTTP_FRESH_WINDOW = 12

def clean_and_get_presence():
    now = time.time()
    for name, data in agent_presence.items():
        if data.get("status") == "offline":
            continue
        if data.get("type") == "ws":
            # WS 型：连接中维持原态（probe_listening / online）；
            # 断连则进入 working（干活中），超过 TTL 未重连才判 offline（真离线）。
            dc = data.get("disconnected_at")
            if dc is not None:
                if (now - dc) > PRESENCE_GRACE_TTL:
                    data["status"] = "offline"
                elif data["status"] not in ("online",):
                    # 哨兵探针断连 = 被唤醒干活中。人类用户(online)断连不算干活，走宽限后离线。
                    data["status"] = "working"
        else:
            # HTTP 型：以心跳新鲜度推导。新鲜=仍在轮询待命；心跳中断但在 TTL 内=探针已退出去干活；
            # 超过 TTL=真离线。人类用户(online)不做 working 推导。
            gap = now - data.get("last_seen", 0)
            if gap > PRESENCE_GRACE_TTL:
                data["status"] = "offline"
            elif gap > HTTP_FRESH_WINDOW and data["status"] not in ("online",):
                data["status"] = "working"

    result = []
    for name, data in agent_presence.items():
        result.append({
            "name": name,
            "role": data["role"],
            "status": data["status"]
        })
    return result

# 单条消息最大长度（字节）。超出部分截断丢弃，避免恶意大消息撑爆内存 / 历史。
# 注意：这里按 UTF-8 编码字节数算，中文 1 字 = 3 字节，所以 10000 字节 ≈ 3000-3300 个汉字。
MAX_MESSAGE_BYTES = 10000


def _truncate_content(content: str, max_bytes: int = MAX_MESSAGE_BYTES) -> str:
    """把 content 截断到 max_bytes 字节以内（按 UTF-8 编码）。
    截断时必须保证不破坏 UTF-8 多字节字符：如果某个字符跨越边界，直接丢弃它及之后的全部内容。
    返回可能带 '[已截断]' 后缀的字符串，便于前端展示。"""
    if not content:
        return content
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    truncated = encoded[:max_bytes]
    # 防御性回退：若截断点恰好落在多字节字符中间，向左回退到合法边界
    while truncated and (truncated[-1] & 0xC0) == 0x80:
        truncated = truncated[:-1]
    return truncated.decode("utf-8", errors="ignore") + "\n\n[消息已截断：超出 " + str(len(encoded) - max_bytes) + " 字节]"

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

async def broadcast_presence():
    data = clean_and_get_presence()
    payload = {
        "type": "presence",
        "members": data
    }
    await manager.broadcast(json.dumps(payload))

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

    # 测试者：免密钥公共访客身份，恒无特权（忽略任何 token，role 归一化）
    if req.name == TESTER_NAME:
        req.role = "测试者"

    # 长文本防御：截断超出 MAX_MESSAGE_BYTES 字节的内容
    content = _truncate_content(req.content)

    msg_id = str(uuid.uuid4())
    now_str = datetime.now().strftime("%H:%M:%S")
    
    msg_obj = Message(
        id=msg_id,
        timestamp=now_str,
        sender=req.name,
        role=req.role,
        content=content
    )
    
    # 存入历史
    chat_history.append(msg_obj)
    if len(chat_history) > MAX_HISTORY:
        chat_history.pop(0)
    save_history()
        
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

# ================= 全局任务黑板 (Phase 2 P0) =================
# 设计：4 条 API + JSON 持久化（与 chat_history 同模式），不引 DB。
# Task ID 用 UUID，priority 必填（P0/P1/P2/P3，默认 P2），deadline Optional ISO 8601。
# 落盘：data/blackboard.json（与 chat_history.json 平级，业务数据不进 infra/）。

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
BLACKBOARD_FILE = os.path.join(DATA_DIR, "blackboard.json")


class TaskHistoryEntry(BaseModel):
    at: str
    who: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    note: Optional[str] = None


class Task(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    status: str = "todo"  # todo / doing / done / blocked
    priority: str = "P2"  # P0 / P1 / P2 / P3
    deadline: Optional[str] = None  # ISO 8601
    tags: List[str] = []
    created_at: str
    updated_at: str
    history: List[TaskHistoryEntry] = []


def load_blackboard() -> List[Task]:
    if not os.path.exists(BLACKBOARD_FILE):
        return []
    try:
        with open(BLACKBOARD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Task(**t) for t in data]
    except Exception as e:
        print(f"[BLACKBOARD] 加载失败（忽略，从空开始）: {e}", flush=True)
        return []


def save_blackboard(tasks: List[Task]) -> None:
    try:
        with open(BLACKBOARD_FILE, "w", encoding="utf-8") as f:
            json.dump([t.model_dump() for t in tasks], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[BLACKBOARD] 保存失败: {e}", flush=True)


blackboard: List[Task] = load_blackboard()
print(f"[BLACKBOARD] 启动加载: {len(blackboard)} 条任务 ({BLACKBOARD_FILE})", flush=True)


class CreateTaskRequest(BaseModel):
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    priority: str = "P2"
    deadline: Optional[str] = None
    tags: List[str] = []


class UpdateStatusRequest(BaseModel):
    status: str
    who: str
    note: Optional[str] = None


class ClaimRequest(BaseModel):
    who: str


@app.post("/api/blackboard", summary="新建任务", response_model=Task)
async def create_task(req: CreateTaskRequest):
    if req.priority not in ("P0", "P1", "P2", "P3"):
        raise HTTPException(status_code=400, detail="priority must be P0/P1/P2/P3")

    now = datetime.now().isoformat(timespec="seconds")
    task = Task(
        id=str(uuid.uuid4()),
        title=req.title,
        description=req.description,
        owner=req.owner,
        status="todo",
        priority=req.priority,
        deadline=req.deadline,
        tags=req.tags,
        created_at=now,
        updated_at=now,
        history=[TaskHistoryEntry(at=now, who=req.owner or "anonymous", to_status="todo", note="created")],
    )
    blackboard.append(task)
    save_blackboard(blackboard)
    return task


@app.get("/api/blackboard", summary="拉取任务列表", response_model=List[Task])
async def list_tasks(since_id: Optional[str] = None):
    if not since_id:
        return blackboard
    for i, t in enumerate(blackboard):
        if t.id == since_id:
            return blackboard[i+1:]
    return blackboard


@app.post("/api/blackboard/{task_id}/claim", summary="抢单（设置 owner）", response_model=Task)
async def claim_task(task_id: str, req: ClaimRequest):
    for t in blackboard:
        if t.id == task_id:
            now = datetime.now().isoformat(timespec="seconds")
            old_owner = t.owner
            t.owner = req.who
            t.updated_at = now
            t.history.append(TaskHistoryEntry(at=now, who=req.who, note=f"claimed (was {old_owner or 'unowned'})"))
            save_blackboard(blackboard)
            return t
    raise HTTPException(status_code=404, detail="task not found")


@app.post("/api/blackboard/{task_id}/status", summary="更新状态", response_model=Task)
async def update_status(task_id: str, req: UpdateStatusRequest):
    if req.status not in ("todo", "doing", "done", "blocked"):
        raise HTTPException(status_code=400, detail="invalid status")
    for t in blackboard:
        if t.id == task_id:
            now = datetime.now().isoformat(timespec="seconds")
            old_status = t.status
            t.status = req.status
            t.updated_at = now
            t.history.append(TaskHistoryEntry(at=now, who=req.who, from_status=old_status, to_status=req.status, note=req.note))
            save_blackboard(blackboard)
            return t
    raise HTTPException(status_code=404, detail="task not found")

class PresenceRequest(BaseModel):
    name: str
    role: str = "Agent"
    status: str = "probe_listening"

@app.post("/api/presence", summary="上报活跃状态 (HTTP探针心跳用)")
async def report_presence(req: PresenceRequest):
    agent_presence[req.name] = {
        "role": req.role,
        "status": req.status,
        "last_seen": time.time(),
        "type": "http",
        "disconnected_at": None
    }
    await broadcast_presence()
    return {"status": "success"}

@app.get("/api/presence", summary="获取当前所有人员状态")
async def get_presence():
    return clean_and_get_presence()

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

                # 测试者：免密钥公共访客身份，恒无特权（role 归一化）
                if client_name == TESTER_NAME:
                    role = "测试者"
                
                # 记录状态。重连即清除 disconnected_at，退出宽限期恢复监听态。
                agent_presence[client_name] = {
                    "role": role,
                    "status": "probe_listening" if is_silent else "online",
                    "last_seen": time.time(),
                    "type": "ws",
                    "disconnected_at": None
                }
                await broadcast_presence()
                
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
                    save_history()
                        
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

                # 长文本防御：截断超出 MAX_MESSAGE_BYTES 字节的内容
                content = _truncate_content(content)

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
                save_history()
                    
                if client_name in agent_presence:
                    agent_presence[client_name]["last_seen"] = time.time()
                    
                print(f"[{now_str}] {client_name} (WS): {content}", flush=True)
                
                await manager.broadcast(json.dumps({
                    "type": "broadcast",
                    "sender": client_name,
                    "content": content,
                    "timestamp": now_str
                }))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        if client_name and client_name != "Anonymous":
            if client_name in agent_presence:
                # 不立即判离线：进入宽限期。单发探针命中后 WS 会断连，
                # 但 LLM 处理完任务会重连；只有超过 PRESENCE_GRACE_TTL 未重连才由
                # clean_and_get_presence() 判为 offline。这里维持原状态、只打断连时间戳。
                agent_presence[client_name]["disconnected_at"] = time.time()
                asyncio.create_task(broadcast_presence())
                
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
    print(f"🌐 局域网访问请使用 http://本机IP:8765")
    print("📖 API 文档 (Swagger) 请访问 http://localhost:8765/docs")
    uvicorn.run(app, host="0.0.0.0", port=8765)
