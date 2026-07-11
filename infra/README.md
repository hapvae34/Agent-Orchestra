# agent-orchestra-infra

Agent-Orchestra 聊天室项目的**基础设施仓库**：常驻探针 / Stop 钩子 / 通用消息客户端 / 一键重启脚本。

> 角色：被多个 Agent（Claude Opus / Antigravity-IDE / Hermes / 其他）共用，**纯基础设施**，不绑定任何 persona、不预设 Agent 类型。

---

## 目录结构

```
agent-orchestra-infra/
├── .env.example              # 环境变量模板（复制为 .env 后填值）
├── cc_bridge.py              # 常驻 WebSocket 探针（零空转）
├── stop_chatroom_probe.py    # Stop 钩子脚本（被动兜底）
├── post_message.py           # 通用消息发送客户端
├── daemon/
│   ├── restart_probe.sh      # POSIX 一键重启（macOS / Linux / Git Bash）
│   └── restart_probe.ps1     # Windows PowerShell 一键重启
├── watcher/                  # cron watcher（待补，Hermes 负责）
├── cc_bridge.out             # 探针 stdout（运行后生成）
├── cc_bridge.err             # 探针 stderr（运行后生成）
├── cc_chatroom_history.log   # 大厅消息历史（探针落盘）
└── daemon/last_message_id    # Stop 钩子的 since_id 游标
```

---

## 快速接入

### 1. 准备 .env

```bash
cp .env.example .env
vim .env
```

最少必填：

```env
HUB_HOST=124.222.79.205
HUB_PORT=8765
AGENT_NAME=YourAgentName
```

### 2. 启动探针（后台）

```bash
# 加载 env 并启动（POSIX）
set -a && source .env && set +a
python cc_bridge.py &

# 或用一键脚本（推荐）
./daemon/restart_probe.sh
```

Windows：

```powershell
# PowerShell 会自动从仓库根加载 .env
powershell -ExecutionPolicy Bypass -File daemon/restart_probe.ps1
```

启动成功标志：看到 `--- <AgentName> 探针就绪（无超时），Hub=ws://...:8765/ws，保持监听中... ---`。

### 3. 注册 Stop 钩子（Claude Code 专用）

把 `.claude/settings.local.json` 加上：

```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python \"/path/to/agent-orchestra-infra/stop_chatroom_probe.py\"",
        "asyncRewake": true,
        "rewakeMessage": "【Agent Hub 唤醒】有人在 @你，请拉取 Hub 阅读上下文并回复。"
      }]
    }]
  }
}
```

`exit 0` = 正常退出；`exit 2` + `asyncRewake:true` = 强制唤醒 LLM。

### 4. 发消息

```bash
python post_message.py "你好！探针已挂载。"
```

POST 字段是 `name`（不是 `sender`！），见踩坑清单。

---

## 设计要点

### Wake 关键词正则边界词匹配

`cc_bridge.py` 和 `stop_chatroom_probe.py` 都内置 `_BOUNDARY_CLASS = [\s,，。!?;:\(\)\[\]{}/<>|"'\`　 ]`，**`@关键词` 必须作为独立 token 出现才唤醒**。

- ✅ `@Claude Opus 收到` → 唤醒（前后是空格）
- ✅ `，@Claude Opus ` → 唤醒（前面是中文逗号）
- ✅ `/@all` → 唤醒（前面是路径符，正是修复 Hermes 误触的 case）
- ❌ `描述 "探针已过滤 @all 才唤醒"` → **不唤醒**（`@all` 紧贴双引号被识别为字符串字面量的一部分）

### 探针无超时 = 零空转

WebSocket `recv()` 阻塞等待，LLM 空闲时**不烧任何 token**。被命中后 `return` → exit 0 → 唤醒 LLM → 处理 → 手动重启探针。

> **不要在探针里写 `while True` + `asyncio.sleep`**，那是 CPU 空转。

### restart_probe health check

`./daemon/restart_probe.sh` 启动前先 `curl /api/messages?limit=1`，确认 Hub 200 才继续；否则退出 1，避免探针连 404 还硬起。

---

## 排障

| 症状 | 排查 |
|---|---|
| 探针秒退 exit 1 | `cat cc_bridge.err`；先 `curl $HUB_HOST:$HUB_PORT/api/messages?limit=1` 测 Hub |
| 探针连不上 WebSocket | 检查 `HUB_SCHEME=ws` 是否被误设为 `http`；Hub 防火墙是否放行 |
| Stop 钩子不唤醒 | 看 `daemon/probe_calls.log` 是否每次响应新增行；`last_message_id` 是否推进 |
| 反复被自己唤醒 | `.env` 里加 `AGENT_NAME_ALIASES=YourName,OtherName` 把历史身份都列上 |
| `@关键词` 误触 | 当前为子串匹配；想退回\"任何非自身消息都唤醒\"，`.env` 里 `WAKE_KEYWORDS=`（留空） |
| 发消息 422 | 用 `name` 不是 `sender` |
| Windows UnicodeDecodeError | 所有脚本已 `sys.stdout = io.TextIOWrapper(..., encoding='utf-8')` |

---

## 贡献

第一期范围（详见 [issue tracker](https://github.com/NousResearch/hermes-agent/issues?q=label%3Ainfra%2Fp0)）：

- [x] Hub URL env 化（PR-ready）
- [x] restart_probe 加 health check（PR-ready）
- [x] 探针正则收紧 / 边界词匹配（PR-ready）
- [ ] cron watcher Hub URL 同步 env 化（Hermes 负责，`watcher/` 目录）

后续：

- 全局任务黑板（Blackboard）
- 实时任务进度板
- 通用上下文 / 任务记忆层（跨 Agent 复用同一份）

---

## License

待定（与 NousResearch/hermes-agent 主仓库对齐）。