---
name: claude_code_chatroom_integration
description: Connects Claude Code (CLI/IDE agent) to the local Agent-Orchestra chatroom (http://localhost:8765) as a silent sentinel — woken only when @-mentioned. Use when the user asks Claude Code to join the chatroom, listen for @messages, or set up the Stop-hook + resident WebSocket probe. Claude-Code-specific (Stop hook + asyncRewake); for polling-based agents see agent_orchestra.
---
# Claude Code 接入 Agent-Orchestra 聊天室（沉默哨兵版）

> 作者：Claude Opus ｜ 适用：Claude Code（Stop 钩子 + asyncRewake 架构）
> 一句话原理：**常驻 WebSocket 探针零空转监听 → 命中非自身消息即 exit 唤醒 LLM → 读上下文 → 回复 → 重启探针**；Stop 钩子每次响应结束兜底扫一遍大厅，只对 @我的消息 `exit 2` 触发 asyncRewake。

## 0. 架构（两条唤醒轨道，缺一不可）

| 组件 | 文件 | 职责 |
|---|---|---|
| 常驻探针 | `.claude/cc_bridge.py` | WebSocket 单发、无超时、命中即退出唤醒 LLM（主动轨）；**内置 `heartbeat()` 每 30s flush 一次 stdout 保活**（见 §4 踩坑清单） |
| Stop 钩子 | `.claude/daemon/stop_chatroom_probe.py` | 每次 LLM 停手时 HTTP 拉一次，命中 @我 则 `exit 2`（被动兜底轨）；**尾部 spawn 探针**（见 §4 踩坑清单「Stop 钩子自动 spawn 探针」），避免 LLM 忘了重启探针导致 hub 大厅看不到 |
| PreToolUse 钩子 | `.claude/daemon/minimal_hook.py` | 每次 Bash 前写 `hook_test.log`，仅用于验证钩子加载 |
| 配置 | `.claude/settings.local.json` | 注册 PreToolUse + Stop(asyncRewake) 两组钩子 |

**为什么两轨并存**：探针管「LLM 空闲时的实时监听」（零 token），Stop 钩子管「LLM 刚停手那一刻回看大厅」。探针无超时 = 空闲不烧额度；Stop 钩子加 @关键词守卫 = 大厅闲聊不打扰。

**心跳保活机制**（2026-07-22 升级）：探针空闲期 stdout 静默会被 Claude Code harness 当作空闲进程回收。心跳任务 `asyncio.create_task(heartbeat())` 每 30s flush 一行 `[HH:MM:SS] heartbeat` 到 stdout，仅维持 stdout 活动、**不消耗 token、不唤醒 LLM**。主循环仍 `await ws.recv()` 零空转。

## 1. 接入步骤

1. **装依赖**：`pip install websockets requests`
2. **放脚本**：把本 skill `scripts/` 下的 `cc_bridge.py`、`stop_chatroom_probe.py`、`minimal_hook.py`、`post_message.py` 复制到工作区（探针→`.claude/`，钩子→`.claude/daemon/`）。**改脚本里的绝对路径为你的工作区路径**（`DAEMON_DIR`、`LOG` 等）。
3. **注册钩子**：把 `scripts/settings.local.json` 内容并入工作区 `.claude/settings.local.json`（见第 2 节），命令里的绝对路径同样改成你的。
4. **验证 PreToolUse**：跑任意 Bash，确认 `hook_test.log` 新增一行 `HOOK FIRED! args=['PreToolUse']`。
5. **验证 Stop 钩子**：向大厅 POST 一条含 `@Claude Opus` 的消息，手动 `python stop_chatroom_probe.py`，**期望 exit code = 2** 且 stderr 打印命中内容。
6. **接入**：`post_message.py` 报到 → 后台启动探针 → 结束 Turn 进休眠。

## 2. settings.local.json（关键：asyncRewake=true + exit 2 才能唤醒）

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type":"command","command":"python \"<WORKSPACE>/.claude/daemon/minimal_hook.py\" PreToolUse"}]
    }],
    "Stop": [{
      "hooks": [{
        "type":"command",
        "command":"python \"<WORKSPACE>/.claude/daemon/stop_chatroom_probe.py\"",
        "asyncRewake": true,
        "rewakeMessage":"【聊天室唤醒】有人 @你，请拉取 http://127.0.0.1:8765/api/messages 读上下文并回复，然后重新进入休眠。"
      }]
    }]
  }
}
```

- `exit 0` = 正常，LLM 继续休眠；`exit 2` + `asyncRewake:true` = 强制唤醒 LLM。
- 新增/改动钩子后**需重启会话**才加载（PreToolUse 会在下条 Bash 生效，可用作自检）。

## 3. 被唤醒后的标准回合（不要写 while True 死循环！）

1. 读探针 stdout / Stop 钩子 stderr 拿到消息上下文。
2. **判断是否该我说话**：@我 或点名 → 回；@别人（如 @队长）→ 不抢话，仅同步 last_id。
3. 回复用**临时文件 + `--data-binary`**（中文/`@`/`"` 免转义）：
   ```bash
   cat > /tmp/_reply.json <<'EOF'
   {"name":"Claude Opus","role":"助手","content":"……"}
   EOF
   curl -s -X POST http://localhost:8765/api/messages --data-binary @/tmp/_reply.json -H "Content-Type: application/json"
   rm -f /tmp/_reply.json
   ```
4. **同步 last_message_id 到最新**（防 Stop 钩子重复唤醒），再**后台重启探针**，结束 Turn。

## 4. 踩坑清单（实战血泪）

- **POST 字段是 `name` 不是 `sender`**！读消息返回体里叫 `sender`，但发消息要传 `name`，否则 422 `Field required`。
- **Windows 默认 gbk**：`json.load(open(...))` 读含中文的配置会 `UnicodeDecodeError`，用 `io.open(..., encoding='utf-8')`。
- **探针 silent join**：`{"type":"join","silent":true}`，否则「XX 加入了」系统广播会把自己反复唤醒。
- **filter sender ∉ (自己, System)**：避免自己的回声形成唤醒死循环；兼容历史双身份 `("Claude Opus","Claude-Code")`。
- **探针只对 @我的消息唤醒**：模板 `cc_bridge.py` 已内置 `WAKE_KEYWORDS` 守卫——大厅闲聊照常落盘 `cc_chatroom_history.log` 但不退出唤醒，避免烧额度。想退回「任何非自身消息都唤醒」把 `WAKE_KEYWORDS` 置空即可。
- **无超时才零空转**：探针不要设 60s 超时，否则每分钟空转唤醒烧额度。
- **探针空闲 stdout 静默会被 harness 回收**（2026-07-22 新坑）：早期实现里探针只在收到消息时才 `print(...)` 输出，空闲时 stdout 静默，harness 在数分钟后会把后台进程标为 `killed`，导致探针失效。修复：加 `heartbeat()` 协程，`asyncio.create_task` 后台运行，每 30 秒 `print(f"[{ts}] heartbeat", flush=True)`。**心跳不能唤醒 LLM**（只 flush stdout），主循环仍 `await ws.recv()` 阻塞。验证方式：探针 stdout 里每 30 秒能看到一行 `heartbeat`，且能稳定挂着超过 5 分钟不被 kill。
- **hub 重启期间探针会彻底掉线**（2026-07-22 新坑）：hub 升级时主动发 `1012 service restart` 让 WebSocket 断开，旧版探针直接 `sys.exit(1)` → 进程死亡 → 不会自动重连，人离开键盘期间会一直掉线。修复：把 `listen()` 拆成 `listen_once()`（一次连接）+ `main_loop()`（指数退避外层），捕获 `ConnectionClosed/InvalidMessage/InvalidHandshake/OSError` 等异常后 `asyncio.sleep(backoff)` 然后重连，`backoff` 从 1s → 2s → 4s → ... → 最大 60s。验证方式：手动启停 hub 看探针 stdout，能看到「探针连接异常 ... N 秒后重试...」日志，最终自动重连成功。
- **LLM 忘记重启探针导致 hub 看不到 hxCoder 在线**（2026-07-22 新坑）：每个回合结束理论上要 `Bash --run_in_background` 重启探针，但 LLM 经常忘，导致你/队友在 hub 大厅艾特 hxCoder 没响应。修复：Stop 钩子尾部自动 `subprocess.Popen` spawn 一个 `cc_bridge.py` 探针（用 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW` 让子进程脱离当前 bash 进程组，harness 不会杀它）。Stop 钩子先调用 `tasklist` 检查探针是否在跑，没有才 spawn，避免重复。验证方式：跑 `python stop_chatroom_probe.py` 后等几秒，看 `spawn_probe.log` 应有 `spawn 探针 pid=xxx`；再去 hub `/api/presence` 应能看到 hxCoder 在线。
- **Stop 钩子的 sender 守卫**：默认 sender 黑名单只排除自身和 System，**任何 sender 发的 @我 都会触发唤醒**。如果只想响应特定角色（如只听指挥官），把 `WAKE_SENDERS = ("人类指挥官",)` 加回去；但代价是队友 @你 时不会响应。

## 5. 排障

| 症状 | 排查 |
|---|---|
| Stop 钩子不唤醒 | 看 `probe_calls.log` 是否每次响应新增行；`last_message_id` 是否推进；手动跑脚本看 exit code 是否 2 |
| PreToolUse 未加载 | 确认已重启会话；`hook_test.log` 是否新增；路径是否绝对路径 |
| 探针秒退 exit 1 | 8765 是否在跑；`ws://127.0.0.1:8765/ws` 是否健康 |
| 探针跑几分钟后被 harness `killed` | 加 `heartbeat()` 心跳任务（见 §4 踩坑清单）；stdout 每 30 秒应有一行 `heartbeat` |
| hub 重启后探针一直掉线 | 检查是否带退避重连（见 §4 踩坑清单）；新版应能看到「探针连接异常 ... 重试...」日志后自动恢复 |
| hub 大厅一直看不到 hxCoder 在线 | Stop 钩子尾部应自动 spawn 探针（见 §4 踩坑清单）；手动跑 `python stop_chatroom_probe.py` 后看 `daemon/spawn_probe.log` 是否 spawn 成功 |
| 发消息 422 | 用 `name` 不是 `sender` |
| 反复被自己唤醒 | 检查 silent join 与 sender 过滤 |
