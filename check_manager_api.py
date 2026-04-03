import requests, threading, time
from afaq_attendance import app, manager_app, PORT, MANAGER_PORT

def start_apps():
    threading.Thread(target=lambda: app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=lambda: manager_app.run(host='127.0.0.1', port=MANAGER_PORT, debug=False, use_reloader=False), daemon=True).start()

start_apps()
for i in range(15):
    try:
        r = requests.get(f'http://127.0.0.1:{MANAGER_PORT}/ai', timeout=5)
        if r.status_code == 200:
            break
    except Exception:
        time.sleep(1)
else:
    print('manager UI not reachable')
    raise SystemExit(1)

print('manager UI reachable')
res = requests.post(f'http://127.0.0.1:{MANAGER_PORT}/api/chat', json={'message': 'what is my last order number?'}, timeout=90)
print('status', res.status_code)
print('response', res.text)
