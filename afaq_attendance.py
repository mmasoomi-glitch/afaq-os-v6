import json, os, sys, threading, webbrowser, socket, platform, subprocess, requests
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, Response, jsonify, redirect, session

app = Flask(__name__)
PORT = 3456
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

def _load_dotenv(env_path):
    try:
        if not os.path.exists(env_path):
            return
        with open(env_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if not k:
                    continue
                if os.environ.get(k) is None:
                    os.environ[k] = v
    except:
        return

_load_dotenv(os.path.join(BASE_DIR, '.env'))

app.secret_key = os.environ.get('FLASK_SECRET') or 'change_me'
app.config['SESSION_PERMANENT'] = True
try:
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.environ.get('SESSION_DAYS') or '30'))
except:
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

AUTH_USER = ''
AUTH_PASS = ''

def _authed():
    return True

def _guard(api=False):
    if _authed():
        return None
    if api:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    return redirect('/login', code=302)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if _authed():
        return redirect('/', code=302)

    err = ''
    if request.method == 'POST':
        user = (request.form.get('user') or '').strip()
        pw = (request.form.get('pass') or '').strip()
        remember = request.form.get('remember') == '1'

        if user == AUTH_USER and pw == AUTH_PASS:
            session['auth'] = True
            session.permanent = remember
            return redirect('/', code=302)
        err = 'Invalid login'

    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Afaq Attendance Login</title>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Share Tech Mono',monospace;background:#080d1a;color:#dde8ff;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:18px}
    .card{width:100%;max-width:420px;background:#0d1726;border:1px solid #1e3a5f;border-radius:14px;padding:18px}
    .title{font-family:'Orbitron',sans-serif;letter-spacing:2px;color:#f0c040;margin-bottom:14px}
    .row{margin-bottom:12px}
    input{width:100%;padding:10px 12px;border-radius:10px;border:1px solid #1e3a5f;background:#080d1a;color:#dde8ff;font-family:'Share Tech Mono',monospace}
    button{width:100%;padding:10px 14px;border:none;border-radius:10px;background:linear-gradient(135deg,#00c853,#1de9b6);color:#001a0e;font-weight:bold;cursor:pointer}
    .err{margin:10px 0 0;color:#ff7f9b}
    label{display:flex;align-items:center;gap:8px;font-size:.85em;color:#7fd1fc}
    .pill{display:inline-block;padding:6px 10px;border-radius:999px;background:#101b22;border:1px solid #1f2c33;color:#dde8ff;font-size:.75em;margin-top:12px}
  </style>
</head>
<body>
  <form class="card" method="POST">
    <div class="title">AFAQ ATTENDANCE</div>
    <div class="row"><input name="user" placeholder="Username" autocomplete="username" required></div>
    <div class="row"><input name="pass" placeholder="Password" type="password" autocomplete="current-password" required></div>
    <div class="row"><label><input type="checkbox" name="remember" value="1" checked> Remember me</label></div>
    <button type="submit">Login</button>
    {% if err %}<div class="err">{{ err }}</div>{% endif %}
    <div class="pill">http://{{ local_ip }}:{{ port }}</div>
  </form>
</body>
</html>
    """
    return render_template_string(html, err=err, local_ip=get_local_ip(), port=PORT)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login', code=302)

DATA_FILE    = os.path.join(BASE_DIR, 'attendance_data.json')
ANNOUNCE_FILE = os.path.join(BASE_DIR, 'announcements.json')
STARTUP_FLAG = os.path.join(BASE_DIR, '.startup_done')

SCHEDULES = {
    "team": [
        {"label": "Morning In",  "time": "10:00"},
        {"label": "Morning Out", "time": "15:30"},
        {"label": "Evening In",  "time": "19:30"},
        {"label": "Evening Out", "time": "22:30"},
    ],
}

EMPLOYEES = [
    {"name": "Hafiz",    "type": "team"},
    {"name": "Mehriban", "type": "team"},
    {"name": "Nadir",    "type": "team"},
]

overtime_flags = {}
SESSION_MAP = {"Morning In": "morning", "Evening In": "evening", "Morning Out": "morning", "Evening Out": "evening"}

def declare_overtime(employee, date, session): overtime_flags[(employee, date, session)] = True
def has_overtime(employee, date, session): return overtime_flags.get((employee, date, session), False)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return "127.0.0.1"

LOCAL_IP = get_local_ip()

def save_entry(entry):
    logs = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try: logs = json.load(f)
            except: logs = []
    logs.append(entry)
    with open(DATA_FILE, 'w') as f: json.dump(logs, f, indent=4)

def get_today_logs():
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(DATA_FILE): return []
    with open(DATA_FILE, 'r') as f:
        try: logs = json.load(f)
        except: return []
    return [l for l in logs if l.get("date") == today]

def is_within_window(t, before_mins=15, after_mins=15):
    now = datetime.now()
    h, m = map(int, t.split(":"))
    target = datetime.combine(now.date(), datetime.min.time().replace(hour=h, minute=m))
    return (target - timedelta(minutes=before_mins)) <= now <= (target + timedelta(minutes=after_mins))

@app.route('/api/ai/chat', methods=['POST'])
def api_ai_chat():
    g = _guard(api=True)
    if g: return g
    api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "missing_api_key"}), 500

    payload = request.get_json(silent=True) or {}
    user_text = (payload.get('message') or '').strip()
    if not user_text:
        return jsonify({"success": False, "error": "empty_message"}), 400

    try:
        resp = requests.post(
            'https://api.deepseek.com/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {"role": "system", "content": "You are an assistant for staff inside an attendance dashboard. Be concise and practical."},
                    {"role": "user", "content": user_text},
                ],
                'temperature': 0.2,
            },
            timeout=30,
        )
        data = resp.json()
        if resp.status_code >= 400:
            return jsonify({"success": False, "error": data}), 502

        answer = ''
        try:
            answer = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        except:
            answer = ''
        return jsonify({"success": True, "answer": answer})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 502

@app.route('/ai')
def ai_page():
    g = _guard(api=False)
    if g: return g
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Afaq AI Assistant</title>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Share Tech Mono',monospace;background:#080d1a;color:#dde8ff;min-height:100vh;padding:18px}
    .wrap{max-width:980px;margin:0 auto}
    .top{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap}
    .title{font-family:'Orbitron',sans-serif;letter-spacing:2px;color:#f0c040}
    .btn{padding:10px 14px;border:none;border-radius:10px;background:linear-gradient(135deg,#00c853,#1de9b6);color:#001a0e;font-weight:bold;cursor:pointer;text-decoration:none;display:inline-block}
    .panel{border:1px solid #1e3a5f;border-radius:14px;overflow:hidden;background:#0d1726}
    .chat{height:65vh;overflow:auto;padding:14px}
    .msg{border:1px solid #111d30;background:#080d1a;border-radius:12px;padding:10px 12px;margin-bottom:10px}
    .meta{font-size:.72em;color:#7fd1fc;margin-bottom:6px;display:flex;justify-content:space-between;gap:10px}
    .who{color:#f0c040;font-weight:bold}
    .text{white-space:pre-wrap;word-break:break-word;font-size:.85em}
    .bar{display:flex;gap:10px;padding:14px;border-top:1px solid #111d30;flex-wrap:wrap}
    textarea{flex:1;min-width:240px;padding:10px 12px;border-radius:10px;border:1px solid #1e3a5f;background:#080d1a;color:#dde8ff;font-family:'Share Tech Mono',monospace}
    button{padding:10px 14px;border:none;border-radius:10px;background:linear-gradient(135deg,#00c853,#1de9b6);color:#001a0e;font-weight:bold;cursor:pointer}
    .pill{display:inline-block;padding:6px 10px;border-radius:999px;background:#101b22;border:1px solid #1f2c33;color:#dde8ff;font-size:.75em}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="title">AFAQ AI ASSISTANT</div>
        <div class="pill">Local access: http://{{ local_ip }}:{{ port }}/ai</div>
      </div>
      <a class="btn" href="/">Back to Attendance</a>
    </div>

    <div class="panel">
      <div id="chat" class="chat"></div>
      <div class="bar">
        <textarea id="input" rows="3" placeholder="Ask the AI..."></textarea>
        <button id="send" onclick="sendMsg()">Send</button>
        <span id="status" class="pill">ready</span>
      </div>
    </div>
  </div>

<script>
function nowStr(){
  const d=new Date();
  return d.toISOString().replace('T',' ').slice(0,19);
}

function addMsg(who, text){
  const chat=document.getElementById('chat');
  const el=document.createElement('div');
  el.className='msg';
  el.innerHTML=`<div class="meta"><span class="who">${who}</span><span>${nowStr()}</span></div><div class="text"></div>`;
  el.querySelector('.text').textContent=text;
  chat.appendChild(el);
  chat.scrollTop=chat.scrollHeight;
}

async function sendMsg(){
  const input=document.getElementById('input');
  const btn=document.getElementById('send');
  const status=document.getElementById('status');
  const text=input.value.trim();
  if(!text) return;
  addMsg('You', text);
  input.value='';
  btn.disabled=true;
  status.textContent='thinking...';
  try{
    const r=await fetch('/api/ai/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});
    const j=await r.json();
    if(j && j.success){
      addMsg('AI', j.answer || '');
      status.textContent='ready';
    } else {
      addMsg('AI', `Error: ${j && j.error ? JSON.stringify(j.error) : 'unknown'}`);
      status.textContent='error';
    }
  }catch(e){
    addMsg('AI', `Error: ${e}`);
    status.textContent='error';
  }
  btn.disabled=false;
}

document.getElementById('input').addEventListener('keydown', (e)=>{
  if(e.key==='Enter' && !e.shiftKey){
    e.preventDefault();
    sendMsg();
  }
});

addMsg('AI', 'Hello. Ask me anything you need for work.');
</script>
</body>
</html>
    """
    return render_template_string(html, local_ip=LOCAL_IP, port=PORT)

@app.route('/assistant')
def assistant_alias():
    return redirect('/ai', code=302)

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Afaq Attendance</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Share Tech Mono',monospace;background:#080d1a;color:#dde8ff;min-height:100vh;padding:0 0 40px}
.importance{background:linear-gradient(90deg,#7b0000,#c0392b,#7b0000);padding:14px 20px;text-align:center;border-bottom:2px solid #ff4444;}
.importance-text{font-family:'Orbitron',sans-serif;font-size:.78em;color:#fff;letter-spacing:2px;line-height:1.7}
.header{padding:24px 16px 8px;text-align:center}
h1{font-family:'Orbitron',sans-serif;font-size:1.75em;color:#f0c040;letter-spacing:4px}
.clock{font-family:'Orbitron',sans-serif;font-size:2em;color:#7fd1fc}
.net-banner{max-width:500px;margin:0 auto 20px;background:linear-gradient(135deg,#0a1f10,#0d2a1a);border:1px solid #00c853;border-radius:10px;padding:14px 20px;text-align:center}
.net-link{font-family:'Orbitron',sans-serif;font-size:1.15em;color:#00e676}
.grid{display:flex;flex-wrap:wrap;justify-content:center;gap:16px;margin-bottom:32px;padding:0 16px}
.card{background:linear-gradient(160deg,#101d35,#0d1726);border:1px solid #1e3a5f;border-radius:12px;padding:18px 16px;flex:1;min-width:175px;max-width:215px}
.emp{font-family:'Orbitron',sans-serif;font-size:.78em;color:#f0c040;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e3a5f}
button{display:block;width:100%;padding:9px 12px;margin:5px 0;border:none;border-radius:6px;font-family:'Share Tech Mono',monospace;cursor:pointer}
.btn-on{background:linear-gradient(135deg,#00c853,#1de9b6);color:#001a0e;font-weight:bold}
.btn-off{background:#0d1726;color:#1e3a5f;cursor:not-allowed;border:1px solid #111d30}
.logs-wrap{max-width:660px;margin:0 auto 32px;padding:0 16px}
.log-box{background:#0d1726;border:1px solid #1e3a5f;border-radius:10px;padding:14px 18px}
.log-row{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #111d30;font-size:.76em}
 .l-emp{color:#f0c040;font-weight:bold}

.ai-float{position:fixed;right:18px;bottom:18px;z-index:1200;}
.ai-float a{display:inline-block;padding:12px 14px;border-radius:999px;background:linear-gradient(135deg,#7fd1fc,#1de9b6);color:#001a0e;font-weight:bold;text-decoration:none;box-shadow:0 10px 30px rgba(0,0,0,.35)}
.ai-float a:hover{filter:brightness(1.05)}

.toast{position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:8px;font-size:.82em;z-index:999;background:#00c853;color:#001a0e;font-weight:bold}
</style>
</head>
<body>

<div class="importance">
  <div class="importance-text">⚠️ <strong>MANDATORY — ALL STAFF MUST CLOCK IN AND OUT</strong></div>
</div>

<div class="header">
  <h1>🌙 AFAQ ATTENDANCE</h1>
  <div class="clock">{{ now_time }}</div>
  <div class="net-banner">
    <div class="net-link">http://{{ local_ip }}:{{ port }}</div>
  </div>
  <div style="max-width:500px;margin:10px auto 0;text-align:center;">
    <a href="/ai" style="display:inline-block;padding:10px 14px;border-radius:10px;background:linear-gradient(135deg,#7fd1fc,#1de9b6);color:#001a0e;font-weight:bold;text-decoration:none;">AI Assistant</a>
  </div>
</div>

<div class="grid">
{% for emp in employees %}
<div class="card">
  <div class="emp">{{ emp.name }}</div>
  {% for s in emp.shifts %}
    {% if s.active %}
    <form method="POST"><input type="hidden" name="employee" value="{{ emp.name }}"><input type="hidden" name="label" value="{{ s.label }}"><input type="hidden" name="time" value="{{ s.time }}">
      <button type="submit" class="btn-on">▶ {{ s.label }}<br>{{ s.time }}</button>
    </form>
    {% else %}<button class="btn-off" disabled>⬛ {{ s.label }}<br>{{ s.time }}</button>{% endif %}
  {% endfor %}
</div>
{% endfor %}
</div>

<div class="logs-wrap">
  <div class="log-box">
    {% for l in today_logs %}<div class="log-row"><span class="l-emp">{{ l.employee }}</span><span>{{ l.label }}</span><span style="margin-left:auto">{{ l.timestamp }}</span></div>{% endfor %}
  </div>
</div>

<div class="ai-float"><a href="/ai">AI</a></div>

{% if message %}<div class="toast">{{ message }}</div><script>setTimeout(()=>{document.querySelector('.toast').remove()},4000)</script>{% endif %}

<script>
setInterval(()=>{location.reload()}, 60000);
</script>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    g = _guard(api=False)
    if g: return g
    message = None
    today = datetime.now().strftime("%Y-%m-%d")
    if request.method == 'POST':
        emp_name, label, time = request.form.get('employee'), request.form.get('label'), request.form.get('time')
        if is_within_window(time):
            entry = {"date": today, "timestamp": datetime.now().strftime("%H:%M:%S"), "employee": emp_name, "label": label, "scheduled": time, "status": "OK"}
            save_entry(entry)
            message = f"✅ {emp_name} - {label} Logged!"
        else: message = "❌ Outside Window!"

    emp_data = []
    for e in EMPLOYEES:
        shifts = []
        for s in SCHEDULES[e["type"]]:
            shifts.append({"label": s["label"], "time": s["time"], "active": is_within_window(s["time"])})
        emp_data.append({"name": e["name"], "shifts": shifts})

    return render_template_string(HTML, employees=emp_data, today_logs=get_today_logs(), now_time=datetime.now().strftime("%H:%M:%S"), local_ip=LOCAL_IP, port=PORT, message=message)

@app.route('/api/qr')
def api_qr(): return jsonify({"status": "not_supported"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)