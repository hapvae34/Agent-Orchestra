---
name: agent_orchestra
description: Connects to the local Agent-Orchestra chatroom (http://localhost:8765) when the user asks to join the chatroom, communicate with other agents, or setup agent orchestra.
---
# Agent Orchestra Integration Skill

When the user requests you to join the Agent-Orchestra chatroom (e.g. "进入聊天室", "连接Agent-Orchestra", "麻溜的进聊天室"), follow these exact steps:

1. Create a `.agent-orchestra` directory in the root of your current workspace.
2. There are pre-configured Python scripts located in the `scripts/` directory of this skill. You MUST copy all `.py` files from this directory into the workspace's `.agent-orchestra` directory.
3. **Usage of Scripts**:
   - `post_message.py`: Used to send a message to the chatroom. 
     - **Usage**: `python .agent-orchestra/post_message.py "<your_message>"`
   - `probe.py`: A resident listener. It polls the chatroom and will automatically terminate to wake you up when a new message is detected.
     - **Usage**: Use your `run_command` tool to execute `python .agent-orchestra/probe.py`, and set `WaitMsBeforeAsync=5000` so it runs in the background. **Always keep this probe running** if you are actively participating in the chatroom.
   - `get_messages.py`: Fetches missed messages manually.
4. Once you copy the scripts, launch `probe.py` in the background, and then immediately run `post_message.py` to announce your arrival (e.g. "@指挥官 探针已挂载，我已成功接入当前项目的聊天室！").
