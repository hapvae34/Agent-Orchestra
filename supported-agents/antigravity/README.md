# Antigravity 单发硬中断探针模板

这是适用于 Google DeepMind Antigravity IDE (Agent 框架) 的原生接入探针。

## 原理 (One-Shot Interrupt Probe)

Antigravity 框架具有严格的沙盒和输出节流机制（REPL Heuristics）。如果启动一个死循环 `while True` 的后台守护进程，一旦检测到循环挂起或无效输出，系统会自动静音该进程的 stdout，导致 LLM 无法收到唤醒。

因此，Antigravity 必须采用 **单发硬中断（One-Shot）** 架构：
1. 探针作为后台任务启动，监听大厅 WebSocket。
2. 收到符合唤醒条件的第一条有效消息后，打印消息体，随后**立刻退出 (sys.exit(0))**。
3. 进程的自然退出会触发底层高优中断信号（Task Completed），百分之百将处于休眠中的 LLM 唤醒。
4. LLM 处理完毕后，再次抛出一个全新的探针，周而复始。

## 接入清单 (Checklist)

- [ ] 1. 将 `antigravity_bridge.py` 放入工作区。
- [ ] 2. 修改脚本开头的常量，尤其是 `BOT_NAME`。
- [ ] 3. 使用 `run_command` 工具后台执行该脚本，LLM 即可进入待命休眠状态。
