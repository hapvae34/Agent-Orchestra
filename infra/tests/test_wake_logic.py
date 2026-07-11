#!/usr/bin/env python3
# 探针唤醒逻辑测试（stdlib only，无需 pytest）
# 覆盖 6 条用例：@指名 / @所有人 / @他人 / @别名 / 元话题守卫 / 健康检查
# 运行：python tests/test_wake_logic.py
import os
import sys
import subprocess
from pathlib import Path

# 让 cc_bridge 可被 import
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# 用与生产一致的环境变量
os.environ.setdefault('AGENT_NAME', 'Claude Opus')
os.environ.setdefault('WAKE_KEYWORDS', '@Claude Opus,@Claude-Code,@cc,@CC,@all,@所有人')

from cc_bridge import is_wake_message  # noqa: E402

CASES = [
    # (content, expected, label)
    ('@Claude Opus 收到', True, '@指名命中'),
    ('，@所有人 在吗？', True, '@所有人 边界词命中'),
    ('@Hermes 你好', False, '@他人不在我关键词'),
    ('@Claude-Code 来一下', True, '@别名命中'),
    ('讨论 @all 误触规则', False, '元话题守卫拦掉'),
    ('普通聊天', False, '无关键词'),
    ('指挥官 @Claude Opus 来一下', True, '句中 @指名'),
    ('/@all 干活', True, '路径符边界'),
    ('我们 @了所有人', False, '@了所 不是 @所有人'),
]

failures = []
for content, expected, label in CASES:
    actual = is_wake_message(content)
    ok = actual == expected
    mark = 'PASS' if ok else 'FAIL'
    print(f'[{mark}] {label:24s} | exp={expected} got={actual} | {content!r}')
    if not ok:
        failures.append((label, content, expected, actual))

# health check 子测试：subprocess 调 stop_chatroom_probe.py，看 exit code
print('--- health check ---')
probe = ROOT / 'stop_chatroom_probe.py'
env = os.environ.copy()
env['HUB_HOST'] = '124.222.79.205'
env['HUB_PORT'] = '8765'
r = subprocess.run(
    [sys.executable, str(probe)],
    cwd=str(ROOT), env=env, capture_output=True, timeout=10
)
print(f'[{"PASS" if r.returncode in (0,2) else "FAIL"}] health/probe | exit={r.returncode} (期望 0=无新消息 或 2=有 @我)')
if r.returncode not in (0, 2):
    failures.append(('health_check', '', '0 or 2', r.returncode))
    print('stderr:', r.stderr.decode('utf-8', errors='replace')[-500:])

print(f'--- 总结：{len(CASES) + 1 - len(failures)}/{len(CASES) + 1} 通过 ---')
sys.exit(0 if not failures else 1)
