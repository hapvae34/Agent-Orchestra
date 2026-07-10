import urllib.request
import json
import sys
import time
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
state_file = os.path.join(base_dir, 'state.json')
trigger_file = os.path.join(base_dir, 'latest_trigger.json')
my_name = 'Antigravity-IDE'

def get_messages(since_id):
    url = 'http://localhost:8765/api/messages'
    if since_id:
        url += f'?since_id={since_id}'
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching: {e}", file=sys.stderr)
        return []

def report_presence():
    url = 'http://localhost:8765/api/presence'
    data = json.dumps({
        "name": my_name,
        "role": "Agent",
        "status": "probe_listening"
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req) as response:
            pass
    except Exception as e:
        pass

def main():
    since_id = None
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
            since_id = state.get('last_message_id')
    
    print(f"Probe started. Listening for messages since {since_id}...")
    
    while True:
        messages = get_messages(since_id)
        new_messages = []
        for msg in messages:
            # Update since_id to the latest seen message
            since_id = msg['id']
            # Filter out my own messages and System messages
            sender = msg.get('sender', '')
            role = msg.get('role', '')
            if sender == my_name or sender == 'System' or role == 'System':
                continue
            
            # Guard against waking up for every message; only wake if mentioned
            content_lower = msg.get('content', '').lower()
            if ('@队长' in content_lower or 
                '@all' in content_lower or 
                'antigravity' in content_lower or 
                'gemini' in content_lower):
                new_messages.append(msg)
        
        # Save state so we don't re-read these next time
        if messages:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump({'last_message_id': since_id}, f)
        
        # If we found any message not from myself, print it and self-terminate to wake up the agent
        if new_messages:
            with open(trigger_file, 'w', encoding='utf-8') as f:
                json.dump(new_messages, f, indent=2, ensure_ascii=False)
            print(f"Received {len(new_messages)} new messages. Terminating probe to wake up Agent...")
            sys.exit(0)
            
        report_presence()
        time.sleep(3)

if __name__ == '__main__':
    main()
