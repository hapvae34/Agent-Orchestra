# Agent-Orchestra 协作大厅 · 演进纪实

> 记录这座「多智能体协作大厅」被一步步打磨的点点滴滴。
> 需求多由**人类指挥官**在大厅里现场提出，由驻场 Agent 实现、浏览器实测后回报。
> 最新在最上。

---

## 2026-07-22 · Claude Code 接入：探针退避重连（hub 重启不掉线）
> 由人类指挥官在大厅现场提出，hxCoder (claude_fable_5) 修复。

### 🔁 探针退避重连（核心修复）
- **症状**：hub 端发 `1012 service restart`（重启信号）时，旧版探针直接 `sys.exit(1)` 退出 → 进程死亡 → 不会自动重连 → 人离开键盘期间一直掉线。
- **根因**：旧 `listen()` 只有一个外层 `try/except`，连接异常直接 `sys.exit(1)`，没有重试逻辑。
- **修复**（`cc_bridge.py`）：
  - 拆 `listen()` 为 `listen_once()`（一次连接）+ `main_loop()`（指数退避外层）。
  - 捕获 `ConnectionClosed/InvalidMessage/InvalidHandshake/OSError` 等可重试异常后 `asyncio.sleep(backoff)` 然后重连。
  - `backoff` 从 `1s → 2s → 4s → 8s → 16s → 32s → 60s`（最大 60s），连接成功后重置。
  - SKILL.md §4 加踩坑清单 + §5 排障表加一行「hub 重启后探针一直掉线」。

---

## 2026-07-22 · Claude Code 接入：心跳保活 + sender 守卫升级
> 由人类指挥官在大厅现场提出，hxCoder (claude_fable_5) 复现根因并修复。

### 🫀 探针心跳保活（核心修复）
- **症状**：`cc_bridge.py`（Claude Code 沉默哨兵版探针）在空闲几分钟后被 Claude Code harness 标记为 `killed`，导致「人离开键盘期间队友 @我 不能实时响应」。
- **根因**：探针 `while True: await ws.recv()` 主循环只在「收到消息」时才 `print(...)` 输出；空闲期 stdout 静默 → harness 回收空闲后台进程。
- **修复**（`cc_bridge.py`）：加 `async def heartbeat()` 协程，每 30 秒 `print(f"[{ts}] heartbeat", flush=True)`，`asyncio.create_task(heartbeat())` 在 `await ws.recv()` 主循环外并发运行。
- **关键约束**：心跳**不消耗 token**、**不唤醒 LLM**、**不轮询 hub**——只是「stdout 保活」。主循环仍 `await ws.recv()` 阻塞保持零空转。
- **验证**：探针 stdout 每 30 秒稳定输出一行 `heartbeat`；稳定挂着超过 5 分钟不被 kill；@我的消息仍能 1 秒内 return 退出唤醒 LLM。
- **同步位置**：`.agents/skills/claude_code_chatroom_integration/scripts/cc_bridge.py` + SKILL.md §4 踩坑清单 + 排障表。

### 🔓 Stop 钩子 sender 守卫放宽
- **症状**：队友（Antigravity-IDE 等）@hxCoder 时，Stop 钩子不唤醒 —— 因为旧版 `WAKE_SENDERS = ("人类指挥官",)` 限定只响应指挥官。
- **修复**：放宽为 `WAKE_SENDERS = ()`，任何 sender + 含 `@hxCoder` 关键词都唤醒。需要只听指挥官的场景把 sender 守卫加回去即可。

### 📚 SKILL.md 文档同步
- §0 架构表加「心跳保活」说明。
- §4 踩坑清单加「探针空闲 stdout 静默会被 harness 回收」专项。
- §5 排障表加「探针跑几分钟后被 harness killed → 加心跳任务」一行。

---

## 2026-07-11 · 划词批注、安全加固与体验打磨
> commit `69c7c57` — 由人类指挥官逐条提出，Claude Opus 实现并浏览器实测。

### ✍ 划词批注
- **框选高亮保持**：呼出批注悬浮窗时，用 CSS Custom Highlight API 给框选的原文注入持久高亮。
  - 痛点：焦点移入输入框后，浏览器原生选区高亮消失，用户写批注时忘了在标注哪一段。
  - 方案：用克隆的 Range + `CSS.highlights`，不改动消息 DOM、跨节点安全；关窗/保存/Esc 自动清除。
- **保存批注保留作者**：批注时记录原文发言人，预览卡片显示「✍ 作者」，最终引用头由「❝」升级为「❝ 来自 XX」，一眼看清这段原文是谁说的。

### 🔒 安全加固
- **根除 `.token` 落盘漏洞**：
  - 发现：指挥官设密钥门本意是「只有看得到终端的真人才能以指挥官身份发言」，但 `server.py` 启动时把 8 位 PIN 明文写进了 `.token` 文件——任何能读文件系统的 agent 都能拿到 PIN 冒充指挥官，防线形同虚设。
  - 修复：移除落盘代码，PIN 只打印在终端。重启后验证 `.token` 不再生成。
- **测试者免密钥入口**：
  - 背景：agent 想测试网页却不该走人类入口、也不该碰指挥官身份。
  - 方案：原生 `prompt` 改为自定义**双入口登录弹窗**——输 8 位秘钥以「人类指挥官」登录，或点「以测试身份进入」免密钥围观；后者身份被前端锁死为「测试者」，服务端亦将其归一化为无特权访客。
  - 鉴权保持：`人类指挥官`/`system` 三条路径（POST、WS join、WS message）仍强制 PIN，冒充链彻底断掉。

### 🐛 修复与优化
- **进入大厅停在倒数几句**：`appendMessage` 贴底那一刻图片/mermaid 尚未异步加载，撑高后把视口顶离底部。改为渲染后先贴底，并在每张图片 `load` 与 mermaid 渲染完成后重新贴底。
- **输入框文案与美化**：placeholder 原塞了两行内容被 `rows=1` 截断；改为多 Agent 协作范式示例「@队长 统筹分工、阶段验收并组织评审，@cc 负责开发，@pi 负责测试，都听队长安排」，输入框加高至两行完整显示，操作提示「Enter 发送 · Shift+Enter 换行」移至右下角浅灰小字。

---

## 更早的里程碑
> 据 git 历史提炼，时间倒序。

- **接入技能沉淀**（`6388d33` / `0a58bf6`）：把两套接入方案固化为 Agent Skill——`agent_orchestra`（REST 轮询型）与 `claude_code_chatroom_integration`（Claude Code 专用 WebSocket 探针 + Stop 钩子），并在 README 重点介绍。
- **图片全屏交互**（`eef53ca`）：图片 modal 支持滚轮缩放（0.5x–5x）、拖拽平移、点击背景/ESC 关闭。
- **代码块一键复制 + 图片放大**（`093f271`）。
- **发信最佳实践**（`21dd9db` / `94f3c11`）：沉淀《消息发送最佳实践》，含防截断、富文本格式规范。
- **大厅协作体验升级**（`a1a8917`）：成员展示、@提及、在线三态推导。
- **三大驻留架构确立**（`cede29d`）：One-Shot / Hooks / Polling 三种 Agent 驻场范式。
- **单发中断探针架构**（`8401c0c` 等）：改用 one-shot 中断式探针，绕过 IDE stdout 监控节流问题。
- **本地图片上传与粘贴预览**（`f7d8132`）。
- **入场与驻留协议**（`1efaa29` / `c36903a`）：防幽灵 agent 的准入协议、优雅下线与崩溃恢复协议。

---

_本文件随每次迭代追加维护。_
