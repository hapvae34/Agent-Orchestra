import urllib.request
import json
import sys
import os

state_file = 'state.json'
since_id = None

if os.path.exists(state_file):
    with open(state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)
        since_id = state.get('last_message_id')

url = 'http://localhost:8765/api/messages'
if since_id:
    url += f'?since_id={since_id}'

try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        with open('messages.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if data:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump({'last_message_id': data[-1]['id']}, f)
except Exception as e:
    print(f"Error fetching messages: {e}", file=sys.stderr)
