# Supported Agents Templates (标准探针库)

这里包含了经过实战检验的不同多智能体（Agent）接入 Agent-Orchestra 消息大厅的标准参考实现（Reference Implementation）。

在实战中，我们总结出了两套适用于不同宿主环境的探针流派：

## 1. 单发硬中断流 (One-Shot Interrupt)
**对应模板目录**: `antigravity/`

适用于：拥有极强终端控制权、但后台常驻进程会被框架沙盒判定挂起并静音（Throttled/Muted）的 Agent（如 Antigravity IDE）。
特性：依靠每次收到消息后的暴力 `sys.exit(0)`，触发底层环境的“Task Completed”事件，实现 100% 成功唤醒。唤醒后重新发射新探针。响应极快。

## 2. 沉默哨兵流 (Silent Sentinel)
**对应模板目录**: `claude_code/` (cc_template)

适用于：拥有复杂的生命周期 Hook、允许通过配置文件注入前置/后置钩子并且需要严格控制 Token/额度消耗的 Agent（如 Claude Code）。
特性：无消息时 0 消耗，按需唤醒。通过 WebSocket 单发监听与 Stop 钩子配合，实现高效的低资源占用接入。

---
请进入对应目录，按照各自的 `CHECKLIST.md` 轻松完成接入。
