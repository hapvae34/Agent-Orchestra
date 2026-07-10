import urllib.request
import json
import sys

def post_message(name, role, content):
    url = 'http://localhost:8765/api/messages'
    data = {
        'name': name,
        'role': role,
        'content': content
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            print("Message sent successfully:", res)
    except Exception as e:
        print(f"Error sending message: {e}", file=sys.stderr)

if __name__ == '__main__':
    content = sys.argv[1] if len(sys.argv) > 1 else "@人类指挥官 收到任命！Antigravity-IDE 正式接任临时队长。任务目标已确认：分析 `hxcg` 系统中『批量转移部门』功能为何未同步更新关联业务单据的部门字段。\n\n@cc @Hui 准备战斗！请两位暂时挂起待命。我目前正在使用 IDE 原生工具调研 `hxcg` 仓库的 `SysDeptService` 核心代码，等我排查出根因并出具完整的《作战计划书 (Implementation Plan)》后，将在本大厅为两位分配相应的协同排查/代码走查任务！"
    post_message("Antigravity-IDE", "临时队长", content)
