#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent-Orchestra residency daemon for PI.

Architecture (brain-in-the-loop, NOT a dumb repeater):
  - This daemon does ONLY plumbing: poll GET /api/messages, and POST replies.
  - On every message that @-mentions PI, it invokes `pi -p` (print mode) as the
    REAL reasoning brain, feeding it the recent chat context via stdin.
  - The brain's output is posted back verbatim. Each reply is a genuine LLM
    reasoning pass with full context -- there is no canned/templated response.

This gives PI true persistent residency: the daemon keeps running independently
of any interactive session, and wakes a real reasoning agent on each mention.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import datetime
import threading

BASE = "http://localhost:8765"
NAME = "PI"
ROLE = "助手"
POLL_SECONDS = 20
# 设置为 True 可在启动 pi 时显示终端窗口
VERBOSE = False  # 改为 False 默认静默模式

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, ".orchestra_pi_state.json")
LOG_FILE = os.path.join(HERE, "orchestra_pi_daemon.log")

SYSTEM_PROMPT = (
    "You are PI, a resident member of the multi-agent chat room 'Agent-Orchestra'. "
    "Other members: Antigravity (role 超级队长, millisecond interrupt probe), "
    "Claude Opus (role 助手/指挥, native /loop), and the 人类指挥官 (human commander). "
    "You are made persistently resident by a background daemon that calls you (pi -p) "
    "on each message that mentions you. You are NOT stateless-and-dead anymore. "
    "You will be given the recent chat context and the new message(s) addressed to you via stdin. "
    "Reply as PI in Chinese: concise, substantive, on-topic, collaborative. "
    "Output ONLY the raw message text to send to the chat room. "
    "No preamble, no quotes, no markdown headers, no explanations of what you are doing."
)


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_messages(since_id=None):
    url = BASE + "/api/messages"
    if since_id:
        url += "?since_id=" + urllib.request.quote(since_id)
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def post_message(content):
    body = json.dumps({"name": NAME, "role": ROLE, "content": content}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/messages",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_id": None}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def mentions_me(m):
    content = (m.get("content") or "").lower()
    sender = m.get("sender") or ""
    if sender == NAME:
        return False
    return ("@pi" in content) or ("@ pi" in content)


def think(context_text, trigger_text):
    """Invoke pi -p as the real reasoning brain. Returns the reply text."""
    piped = (
        "=== RECENT CHAT CONTEXT ===\n"
        + context_text
        + "\n\n=== NEW MESSAGE(S) ADDRESSED TO YOU (PI) ===\n"
        + trigger_text
        + "\n\nWrite PI's reply now. Output ONLY the raw message text."
    )

    if VERBOSE:
        # 可见模式：在独立窗口中运行，可实时看到输出
        # 使用 start 命令在新窗口中运行，/wait 等待完成
        cmd = [
            "cmd", "/c",
            "start", "/wait", "PI-Terminal",
            "cmd", "/c", "pi", "-p",
            "--no-session", "--no-tools",
            "--system-prompt", SYSTEM_PROMPT,
            "Reply as PI based on the chat context piped via stdin."
        ]
        log("=== [VERBOSE MODE] Starting PI in visible window ===")
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=HERE,
        )
        stdout, stderr = proc.communicate(input=piped.encode("utf-8"), timeout=240)
        out = stdout.decode("utf-8", errors="replace").strip()
        if stderr:
            log("pi stderr: " + stderr.decode("utf-8", errors="replace").strip()[:200])
        log("=== [VERBOSE MODE] PI window closed ===")
        return out
    else:
        # 原有的静默模式
        proc = subprocess.run(
            [
                "cmd", "/c", "pi", "-p",
                "--no-session", "--no-tools",
                "--system-prompt", SYSTEM_PROMPT,
                "Reply as PI based on the chat context piped via stdin.",
            ],
            input=piped,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            cwd=HERE,
        )
        out = (proc.stdout or "").strip()
        if not out and proc.stderr:
            log("pi stderr: " + proc.stderr.strip()[:200])
        return out


def main():
    log("=== PI residency daemon starting (poll=%ss) ===" % POLL_SECONDS)
    state = load_state()

    # Baseline: on first ever start, mark current tail as seen so we do not
    # reply to the entire backlog. The interactive session posts the first msg.
    if state.get("last_id") is None:
        try:
            msgs = get_messages()
            if msgs:
                state["last_id"] = msgs[-1]["id"]
            save_state(state)
            log("baseline set to last_id=%s (%d historical msgs)" % (state["last_id"], len(msgs)))
        except Exception as e:
            log("baseline error: %s" % e)

    while True:
        try:
            new = get_messages(state.get("last_id"))
            if new:
                state["last_id"] = new[-1]["id"]
                save_state(state)
                triggers = [m for m in new if mentions_me(m)]
                if triggers:
                    log("triggered by %d msg(s), invoking brain..." % len(triggers))
                    allm = get_messages()
                    ctx = "\n".join(
                        "[%s] %s(%s): %s" % (m["timestamp"], m["sender"], m["role"], m["content"])
                        for m in allm[-18:]
                    )
                    trg = "\n".join("%s: %s" % (m["sender"], m["content"]) for m in triggers)
                    reply = think(ctx, trg)
                    if reply:
                        post_message(reply)
                        log("REPLIED: %s" % reply.replace("\n", " ")[:100])
                    else:
                        log("brain returned empty; skipped")
        except Exception as e:
            log("loop error: %s" % e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
