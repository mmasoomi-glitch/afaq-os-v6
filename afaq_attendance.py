import json, os, sys, threading, webbrowser, socket, platform, subprocess, requests
import google.generativeai as genai
from services.shopify_ai_agent import ShopifyAIAgent
from services.shopify_profit import ProfitEngine
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, Response, jsonify, redirect, session

app = Flask(__name__)
manager_app = Flask('manager')

PORT = 3456
MANAGER_PORT = 6789
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

def _load_dotenv(env_path):
    try:
        if not os.path.exists(env_path): return
        with open(env_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line: continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and os.environ.get(k) is None: os.environ[k] = v
    except: return

_load_dotenv(os.path.join(BASE_DIR, '.env'))

API_KEY = os.environ.get('GEMINI_API_KEY')
if API_KEY and API_KEY != 'your_key_here':
    genai.configure(api_key=API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.5-flash')
else:
    ai_model = None

app.secret_key = os.environ.get('FLASK_SECRET') or 'change_me'
manager_app.secret_key = app.secret_key

DATA_FILE    = os.path.join(BASE_DIR, 'attendance_data.json')
ANNOUNCE_FILE = os.path.join(BASE_DIR, 'announcements.json')

SCHEDULES = {
    "team": [
        {"label": "Morning In",  "time": "09:30"},
        {"label": "Morning Out", "time": "14:00"},
        {"label": "Evening In",  "time": "16:30"},
        {"label": "Evening Out", "time": "21:00"},
    ],
}

def get_today_schedule(team_type):
    base = SCHEDULES.get(team_type) or []
    if datetime.now().weekday() == 4:
        out = []
        for s in base:
            if s.get('label') == 'Morning Out': out.append({"label": s.get("label"), "time": "12:00"})
            else: out.append({"label": s.get("label"), "time": s.get("time")})
        return out
    return base

EMPLOYEES = [
    {"name": "Hafiz",    "type": "team"},
    {"name": "Mehriban", "type": "team"},
    {"name": "Nadir",    "type": "team"},
]

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

def load_attendance_logs():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        raw = f.read()
    try:
        logs = json.loads(raw)
        return logs
    except Exception:
        start = raw.find('[')
        if start == -1:
            return []
        # Prefer the first complete JSON array block
        first_end = raw.find(']', start)
        while first_end != -1:
            candidate = raw[start:first_end+1]
            try:
                logs = json.loads(candidate)
                # Save cleaned data for stability
                with open(DATA_FILE, 'w', encoding='utf-8') as fw:
                    json.dump(logs, fw, indent=4)
                return logs
            except Exception:
                first_end = raw.find(']', first_end + 1)
        # Fallback: parse remainder to last array
        end = raw.rfind(']')
        if end != -1 and end > start:
            try:
                logs = json.loads(raw[start:end+1])
                with open(DATA_FILE, 'w', encoding='utf-8') as fw:
                    json.dump(logs, fw, indent=4)
                return logs
            except Exception:
                return []
        return []

def get_today_logs():
    today = datetime.now().strftime("%Y-%m-%d")
    logs = load_attendance_logs()
    return [l for l in logs if l.get("date") == today]

REQUIRED_LABELS = ["Morning In", "Morning Out", "Evening In", "Evening Out"]

def get_monthly_kpi(emp_name):
    now = datetime.now()
    current_month_prefix = now.strftime("%Y-%m")
    logs = load_attendance_logs()
    emp_logs = [l for l in logs if l.get("employee") == emp_name and l.get("date", "").startswith(current_month_prefix)]
    active_dates = sorted(list(set(l.get("date") for l in emp_logs)))
    if not active_dates: return {"pct": 0.0, "color": "#ef4444", "text": "0.0%"}
    start_day = int(active_dates[0].split("-")[2])
    expected_shifts = 0
    for d in range(start_day, now.day + 1):
        if d < now.day: expected_shifts += len(REQUIRED_LABELS)
        elif d == now.day:
            for s in get_today_schedule("team"):
                h, m = map(int, s["time"].split(":"))
                shift_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if now > shift_time: expected_shifts += 1
    daily_completed = {}
    for l in emp_logs:
        d = l.get("date")
        lbl = l.get("label")
        if lbl in REQUIRED_LABELS: daily_completed.setdefault(d, set()).add(lbl)
    completed = sum(len(labels) for labels in daily_completed.values())
    pct = (completed / expected_shifts * 100.0) if expected_shifts > 0 else 100.0
    if pct >= 90: color = "var(--brand-green)"
    elif pct >= 75: color = "var(--brand-peach)"
    else: color = "#ef4444" 
    return {"pct": round(pct, 1), "color": color, "text": f"{round(pct, 1)}%"}

def get_punctuality_kpi(emp_name):
    logs = load_attendance_logs()
    emp_logs = [l for l in logs if l.get("employee") == emp_name]
    if not emp_logs: return {"score": 0, "color": "#ef4444", "text": "0%", "evidence": []}
    
    total_score = 0
    count = 0
    evidence = []
    
    for log in emp_logs:
        scheduled = log.get("scheduled")
        timestamp = log.get("timestamp")
        date = log.get("date")
        label = log.get("label")
        if not scheduled or not timestamp: continue
        
        try:
            sched_h, sched_m = map(int, scheduled.split(":"))
            actual_h, actual_m, actual_s = map(int, timestamp.split(":"))
            sched_time = sched_h * 60 + sched_m
            actual_time = actual_h * 60 + actual_m
            diff_minutes = actual_time - sched_time
            if diff_minutes <= 0:
                score = 100  # On time or early
            elif diff_minutes <= 15:
                score = max(50, 100 - diff_minutes * 3)  # Late but within grace
            else:
                score = max(0, 50 - (diff_minutes - 15))  # Very late
            total_score += score
            count += 1
            if diff_minutes > 0:
                evidence.append(f"{date} {label}: Late by {diff_minutes} min")
        except:
            continue
    
    if count == 0: return {"score": 0, "color": "#ef4444", "text": "0%", "evidence": []}
    avg_score = total_score / count
    if avg_score >= 90: color = "var(--brand-green)"
    elif avg_score >= 70: color = "var(--brand-peach)"
    else: color = "#ef4444"
    return {"score": round(avg_score, 1), "color": color, "text": f"{round(avg_score, 1)}%", "evidence": evidence[-10:]}  # Last 10 bad records

def is_within_window(t, before_mins=15, after_mins=15):
    now = datetime.now()
    h, m = map(int, t.split(":"))
    target = datetime.combine(now.date(), datetime.min.time().replace(hour=h, minute=m))
    return (target - timedelta(minutes=before_mins)) <= now <= (target + timedelta(minutes=after_mins))

# ---------------------------------------------------------
# HTML TEMPLATES
# ---------------------------------------------------------
COMMON_CSS = """
:root { --brand-peach: #ffd6a5; --brand-green: #b8d58d; --brand-purple: #bdb2ff; --bg-dark: #0f172a; --text-light: #f8fafc; }
body { font-family: 'Montserrat', sans-serif; background-color: var(--bg-dark); color: var(--text-light); min-height: 100vh; padding: 0 0 40px; margin: 0; }
.glass-card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(189, 178, 255, 0.3); border-radius: 1rem; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); padding: 1.5rem; }
.btn-primary { background: linear-gradient(135deg, var(--brand-green), var(--brand-purple)); color: #001a0e; font-weight: bold; border: none; border-radius: 0.5rem; padding: 0.75rem 1rem; cursor: pointer; transition: transform 0.2s, filter 0.2s; display: block; width: 100%; margin: 8px 0; text-decoration: none; text-align: center; box-sizing: border-box; }
.btn-primary:hover { transform: translateY(-2px); filter: brightness(1.1); }
.btn-off { background: rgba(30, 41, 59, 0.4); border: 1px dashed rgba(189, 178, 255, 0.4); color: rgba(248, 250, 252, 0.4); border-radius: 0.5rem; padding: 0.75rem 1rem; cursor: not-allowed; display: block; width: 100%; margin: 8px 0; font-weight: 600; text-align: center; box-sizing: border-box; }
.brand-logo { max-height: 48px; width: auto; object-fit: contain; margin: 0 auto 10px auto; display: block; }
.importance { padding: 14px 20px; text-align: center; border-bottom: 1px solid rgba(189, 178, 255, 0.35); background: rgba(30,41,59,0.55); }
.importance-text { font-size: .85em; color: var(--text-light); letter-spacing: 1px; line-height: 1.7; }
.header { padding: 24px 16px 24px; text-align: center; }
.clock { font-weight: 800; font-size: 2.2em; margin-bottom: 10px; }
.net-banner { max-width: 400px; margin: 0 auto 20px; text-align: center; padding: 10px; }
.net-link { font-weight: 800; font-size: 1.1em; color: var(--brand-peach); text-decoration: none; }
.grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin-bottom: 32px; padding: 0 16px; }
.card { flex: 1; min-width: 220px; max-width: 260px; text-align: center; }
.emp { font-weight: 800; font-size: 1.2em; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(189, 178, 255, 0.25); display: flex; flex-direction: column; align-items: center; gap: 8px; }
.kpi-badge { font-size: 0.65em; padding: 4px 10px; border: 1px solid; border-radius: 12px; background: rgba(15, 23, 42, 0.5); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
.logs-wrap { max-width: 760px; margin: 0 auto 32px; padding: 0 16px; }
.log-box { padding: 14px 18px; }
.log-row { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid rgba(189,178,255,0.18); font-size: .9em; }
.log-row:last-child { border-bottom: none; }
.l-emp { font-weight: 800; color: var(--brand-peach); }
.toast { position: fixed; top: 20px; right: 20px; padding: 12px 20px; border-radius: 0.75rem; font-size: .9em; z-index: 999; background: rgba(30,41,59,0.95); color: var(--text-light); border: 1px solid rgba(189,178,255,0.5); font-weight: 600; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
.shift-readonly { padding: 8px; margin: 4px 0; background: rgba(30,41,59,0.4); border-radius: 6px; font-size: 0.9em; border: 1px solid rgba(189,178,255,0.1); }
.ticker-wrap { width: 100%; overflow: hidden; background: rgba(15, 23, 42, 0.9); border-bottom: 1px solid rgba(189,178,255,0.2); padding: 8px 0; box-sizing: border-box; }
.ticker { display: inline-block; white-space: nowrap; padding-left: 100%; animation: ticker 30s linear infinite; }
.ticker-item { display: inline-block; padding: 0 2rem; font-weight: 600; font-size: 0.9em; color: var(--brand-peach); border-right: 1px solid rgba(248,250,252,0.2); }
.ticker-item:last-child { border-right: none; }
@keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }
"""

EMPLOYEE_HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Afaq Attendance - Staff</title><link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;800&display=swap" rel="stylesheet"><style>{COMMON_CSS}</style></head><body>
<div style="text-align:center; padding-top: 10px; background: rgba(30,41,59,0.55);">
  <a href="/ai" class="btn-primary" style="display:inline-block; width:auto; padding:6px 20px; border-radius:20px; font-size:0.85em;">🤖 Office AI Assistant</a>
  <a href="/kpi" class="btn-primary" style="display:inline-block; width:auto; padding:6px 20px; border-radius:20px; font-size:0.85em;">📊 KPI Dashboard</a>
</div>
<div class="importance"><div class="importance-text">⚠️ <strong>MANDATORY — ALL STAFF MUST CLOCK IN AND OUT</strong></div></div>
<div class="header">
  <img class="brand-logo" src="https://cdn.shopify.com/s/files/1/0911/0215/0954/files/Afaq_official_logo.png?v=1770887488" alt="Logo">
  <div class="clock">{{{{ now_time }}}}</div>
  <div class="net-banner glass-card"><div class="net-link">http://{{{{ local_ip }}}}:{{{{ port }}}}</div></div>
</div>
<div class="grid">
{{% for emp in employees %}}
<div class="card glass-card">
  <div class="emp">{{{{ emp.name }}}}<div class="kpi-badge" style="color: {{{{ emp.kpi.color }}}}; border-color: {{{{ emp.kpi.color }}}};">{{{{ emp.kpi.text }}}} Monthly KPI</div></div>
  {{% for s in emp.shifts %}}
    {{% if s.active %}}
    <form method="POST"><input type="hidden" name="employee" value="{{{{ emp.name }}}}"><input type="hidden" name="label" value="{{{{ s.label }}}}"><input type="hidden" name="time" value="{{{{ s.time }}}}"><button type="submit" class="btn-primary">▶ {{{{ s.label }}}} ({{{{ s.time }}}})</button></form>
    {{% else %}}<button class="btn-off" disabled>🔒 {{{{ s.label }}}} ({{{{ s.time }}}})</button>{{% endif %}}
  {{% endfor %}}
</div>
{{% endfor %}}
</div>
<div class="logs-wrap"><div class="log-box glass-card"><div style="margin-bottom: 10px; font-weight: 800; color: var(--brand-purple);">Today's Logs</div>
    {{% for l in today_logs %}}<div class="log-row"><span class="l-emp">{{{{ l.employee }}}}</span><span>{{{{ l.label }}}}</span><span style="margin-left:auto">{{{{ l.timestamp }}}}</span></div>{{% else %}}<div style="font-size: 0.85em; opacity: 0.7;">No entries yet today.</div>{{% endfor %}}
</div></div>
{{% if message %}}<div class="toast">{{{{ message }}}}</div><script>setTimeout(()=>{{document.querySelector('.toast').remove()}},4000)</script>{{% endif %}}
<script>setInterval(() => {{ location.reload(); }}, 60000);</script></body></html>"""

MANAGER_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Afaq Attendance - Executive Dashboard</title><link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;800&display=swap" rel="stylesheet"><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
:root { --brand-peach: #ffd6a5; --brand-green: #b8d58d; --brand-purple: #bdb2ff; --bg-dark: #0f172a; --text-light: #f8fafc; }
body { font-family: 'Montserrat', sans-serif; background-color: var(--bg-dark); color: var(--text-light); min-height: 100vh; padding: 0 0 40px; margin: 0; }
.glass-card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(189, 178, 255, 0.3); border-radius: 1rem; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); padding: 1.5rem; }
.btn-primary { background: linear-gradient(135deg, var(--brand-green), var(--brand-purple)); color: #001a0e; font-weight: bold; border: none; border-radius: 0.5rem; padding: 0.75rem 1rem; cursor: pointer; transition: transform 0.2s, filter 0.2s; display: block; width: 100%; margin: 8px 0; text-decoration: none; text-align: center; box-sizing: border-box; }
.btn-primary:hover { transform: translateY(-2px); filter: brightness(1.1); }
.btn-off { background: rgba(30, 41, 59, 0.4); border: 1px dashed rgba(189, 178, 255, 0.4); color: rgba(248, 250, 252, 0.4); border-radius: 0.5rem; padding: 0.75rem 1rem; cursor: not-allowed; display: block; width: 100%; margin: 8px 0; font-weight: 600; text-align: center; box-sizing: border-box; }
.brand-logo { max-height: 48px; width: auto; object-fit: contain; margin: 0 auto 10px auto; display: block; }
.importance { padding: 14px 20px; text-align: center; border-bottom: 1px solid rgba(189, 178, 255, 0.35); background: rgba(30,41,59,0.55); }
.importance-text { font-size: .85em; color: var(--text-light); letter-spacing: 1px; line-height: 1.7; }
.header { padding: 24px 16px 24px; text-align: center; }
.clock { font-weight: 800; font-size: 2.2em; margin-bottom: 10px; }
.net-banner { max-width: 400px; margin: 0 auto 20px; text-align: center; padding: 10px; }
.net-link { font-weight: 800; font-size: 1.1em; color: var(--brand-peach); text-decoration: none; }
.grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin-bottom: 32px; padding: 0 16px; }
.card { flex: 1; min-width: 220px; max-width: 260px; text-align: center; }
.emp { font-weight: 800; font-size: 1.2em; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(189, 178, 255, 0.25); display: flex; flex-direction: column; align-items: center; gap: 8px; }
.kpi-badge { font-size: 0.65em; padding: 4px 10px; border: 1px solid; border-radius: 12px; background: rgba(15, 23, 42, 0.5); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
.logs-wrap { max-width: 760px; margin: 0 auto 32px; padding: 0 16px; }
.log-box { padding: 14px 18px; }
.log-row { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid rgba(189,178,255,0.18); font-size: .9em; }
.log-row:last-child { border-bottom: none; }
.l-emp { font-weight: 800; color: var(--brand-peach); }
.toast { position: fixed; top: 20px; right: 20px; padding: 12px 20px; border-radius: 0.75rem; font-size: .9em; z-index: 999; background: rgba(30,41,59,0.95); color: var(--text-light); border: 1px solid rgba(189,178,255,0.5); font-weight: 600; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
.shift-readonly { padding: 8px; margin: 4px 0; background: rgba(30,41,59,0.4); border-radius: 6px; font-size: 0.9em; border: 1px solid rgba(189,178,255,0.1); }
.ticker-wrap { width: 100%; overflow: hidden; background: rgba(15, 23, 42, 0.9); border-bottom: 1px solid rgba(189,178,255,0.2); padding: 8px 0; box-sizing: border-box; }
.ticker { display: inline-block; white-space: nowrap; padding-left: 100%; animation: ticker 30s linear infinite; }
.ticker-item { display: inline-block; padding: 0 2rem; font-weight: 600; font-size: 0.9em; color: var(--brand-peach); border-right: 1px solid rgba(248,250,252,0.2); }
.ticker-item:last-child { border-right: none; }
@keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }
</style></head><body>

<div class="ticker-wrap">
  <div class="ticker">
    <span class="ticker-item">🌤️ Dubai: 38°C, Clear</span>
    <span class="ticker-item">💱 USD/AED: 3.67</span>
    <span class="ticker-item">💱 EUR/AED: 4.05</span>
    <span class="ticker-item">📈 DFMGI: 4,215.30 (+1.2%)</span>
    <span class="ticker-item">🛢️ Brent Crude: $82.50</span>
    <span class="ticker-item">🚗 E11 SZR: Heavy Traffic Southbound</span>
    <span class="ticker-item">📉 Gold (Ounce): $2,340.10</span>
  </div>
</div>

<div style="text-align:center; padding-top: 15px;">
  <a href="/ai" class="btn-primary" style="display:inline-block; width:auto; padding:10px 30px; border-radius:20px;">👑 Owner AI & Business Analyst</a>
  <a href="/kpi" class="btn-primary" style="display:inline-block; width:auto; padding:10px 30px; border-radius:20px;">📊 KPI Dashboard</a>
</div>
<div class="header" style="padding-bottom: 10px;">
  <img class="brand-logo" src="https://cdn.shopify.com/s/files/1/0911/0215/0954/files/Afaq_official_logo.png?v=1770887488" alt="Logo">
  <div class="clock">{{ now_time }}</div>
</div>

<div style="max-width: 900px; margin: 0 auto 20px; padding: 0 16px;">
  <div style="display: flex; gap: 20px; flex-wrap: wrap;">
    <div class="glass-card" style="flex: 2; min-width: 300px; padding: 1rem;">
      <div style="margin-bottom: 10px; font-weight: 800; color: var(--brand-peach);">Shopify Sales & Fulfillments (7 Days)</div>
      <div style="position: relative; height: 220px; width: 100%;"><canvas id="salesChart"></canvas></div>
    </div>
    <div class="glass-card" style="flex: 1; min-width: 250px; padding: 1rem;">
      <div style="margin-bottom: 10px; font-weight: 800; color: var(--brand-green);">Warehouse Top 10</div>
      <ul style="list-style: none; padding: 0; margin: 0; font-size: 0.85em; opacity: 0.9; line-height: 2.2;">
        <li>1. Premium Item A <span style="float:right; color:var(--brand-green)">95% Stock</span></li>
        <li>2. Standard Part B <span style="float:right; color:var(--brand-green)">82% Stock</span></li>
        <li>3. Accessory Bundle C <span style="float:right; color:var(--brand-peach)">40% Stock</span></li>
        <li>4. Fragile Unit D <span style="float:right; color:var(--brand-peach)">35% Stock</span></li>
        <li>5. Clearance Item E <span style="float:right; color:#ef4444">10% Stock</span></li>
        <li style="text-align:center; margin-top:10px; opacity:0.5;">(Pending API Integration)</li>
      </ul>
    </div>
  </div>
</div>

<div class="grid">
{% for emp in employees %}
<div class="card glass-card">
  <div class="emp">{{ emp.name }}<div class="kpi-badge" style="color: {{ emp.kpi.color }}; border-color: {{ emp.kpi.color }};">{{ emp.kpi.text }} Monthly KPI</div></div>
  {% for s in emp.shifts %}<div class="shift-readonly">{{ s.label }} ({{ s.time }})</div>{% endfor %}
</div>
{% endfor %}
</div>
<div class="logs-wrap"><div class="log-box glass-card"><div style="margin-bottom: 10px; font-weight: 800; color: var(--brand-purple);">Today's Logs</div>
    {% for l in today_logs %}<div class="log-row"><span class="l-emp">{{ l.employee }}</span><span>{{ l.label }}</span><span style="margin-left:auto">{{ l.timestamp }}</span></div>{% else %}<div style="font-size: 0.85em; opacity: 0.7;">No entries yet today.</div>{% endfor %}
</div></div>
<script>
  const ctx = document.getElementById('salesChart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      datasets: [{
        label: 'Sales Velocity (AED)',
        data: [12000, 19000, 15000, 22000, 18000, 25000, 21000],
        borderColor: '#ffd6a5',
        backgroundColor: 'rgba(255, 214, 165, 0.15)',
        tension: 0.4, fill: true
      },
      {
        label: 'Fulfillments',
        data: [40, 55, 42, 60, 46, 70, 58],
        borderColor: '#b8d58d',
        tension: 0.4, borderDash: [5, 5]
      }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#f8fafc' }} }, scales: { x: { ticks: { color: '#f8fafc' } }, y: { ticks: { color: '#f8fafc' }} } }
  });
</script></body></html>"""

AI_CHAT_HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{{{ title }}}}</title><link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;800&display=swap" rel="stylesheet"><style>{COMMON_CSS}
.chat-container {{ max-width: 800px; margin: 20px auto; height: 65vh; display: flex; flex-direction: column; }}
.messages {{ flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; }}
.msg {{ max-width: 80%; padding: 12px 16px; border-radius: 12px; font-size: 0.95em; line-height: 1.5; }}
.msg.user {{ align-self: flex-end; background: linear-gradient(135deg, var(--brand-purple), var(--brand-peach)); color: #0f172a; font-weight: 600; border-bottom-right-radius: 2px; }}
.msg.ai {{ align-self: flex-start; background: rgba(30, 41, 59, 0.8); border: 1px solid rgba(189, 178, 255, 0.3); color: var(--text-light); border-bottom-left-radius: 2px; }}
.input-area {{ display: flex; gap: 10px; margin-top: 15px; }}
.chat-input {{ flex: 1; background: rgba(15, 23, 42, 0.6); border: 1px solid var(--brand-purple); color: var(--text-light); padding: 12px 16px; border-radius: 8px; font-family: 'Montserrat', sans-serif; outline: none; font-size: 16px; }}
.chat-input:focus {{ border-color: var(--brand-peach); }}
.send-btn {{ width: 100px; margin: 0; }}
</style></head><body>
<div class="header" style="padding-bottom: 0;">
  <img class="brand-logo" src="https://cdn.shopify.com/s/files/1/0911/0215/0954/files/Afaq_official_logo.png?v=1770887488" alt="Logo">
  <div class="clock" style="font-size: 1.5em;">{{{{ title }}}}</div>
  <div class="net-banner glass-card" style="padding: 5px;"><a href="/" class="net-link" style="font-size: 0.9em;">⬅ Back to Dashboard</a></div>
</div>
<div class="chat-container glass-card">
  <div class="messages" id="chat-box">
    <div class="msg ai">Hello! I am the {{{{ title }}}}. How can I assist you today?</div>
  </div>
  <div class="input-area">
    <input type="text" id="chat-input" class="chat-input" placeholder="Type your message..." onkeypress="if(event.key === 'Enter') sendMessage()">
    <button class="btn-primary send-btn" onclick="sendMessage()">Send</button>
  </div>
</div>
<script>
async function sendMessage() {{
  const input = document.getElementById('chat-input');
  const box = document.getElementById('chat-box');
  const text = input.value.trim();
  if(!text) return;
  const uDiv = document.createElement('div'); uDiv.className = 'msg user'; uDiv.textContent = text; box.appendChild(uDiv);
  input.value = ''; box.scrollTop = box.scrollHeight;
  try {{
    const res = await fetch('/api/chat', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{message: text}}) }});
    const data = await res.json();
    const aDiv = document.createElement('div'); aDiv.className = 'msg ai'; aDiv.textContent = data.response; box.appendChild(aDiv);
    box.scrollTop = box.scrollHeight;
  }} catch(e) {{
    const eDiv = document.createElement('div'); eDiv.className = 'msg ai'; eDiv.style.color = '#ef4444'; eDiv.textContent = "Error: AI Backend not connected yet."; box.appendChild(eDiv);
  }}
}}
</script></body></html>"""

KPI_HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Attendance KPI Dashboard</title><link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;800&display=swap" rel="stylesheet"><style>{COMMON_CSS}
.kpi-container {{ max-width: 1000px; margin: 20px auto; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
.kpi-card {{ padding: 20px; border-radius: 10px; }}
.kpi-score {{ font-size: 2em; font-weight: 800; margin-bottom: 10px; }}
.evidence {{ margin-top: 15px; }}
.evidence-item {{ font-size: 0.85em; color: rgba(248,250,252,0.7); margin: 5px 0; }}
</style></head><body>
<div class="kpi-container">
  <h1 style="text-align: center; margin-bottom: 30px;">Attendance KPI Dashboard</h1>
  <div class="kpi-grid">
    {{% for emp in employees %}}
    <div class="glass-card kpi-card">
      <h3>{{{{ emp.name }}}}</h3>
      <div class="kpi-score" style="color: {{{{ emp.punctuality.color }}}};">{{{{ emp.punctuality.text }}}}</div>
      <div>Punctuality Score</div>
      <div style="margin-top: 10px;">Attendance: {{{{ emp.attendance.text }}}}</div>
      {{% if emp.punctuality.evidence %}}
      <div class="evidence">
        <strong>Lateness Records:</strong>
        {{% for ev in emp.punctuality.evidence %}}
        <div class="evidence-item">• {{{{ ev }}}}</div>
        {{% endfor %}}
      </div>
      {{% endif %}}
    </div>
    {{% endfor %}}
  </div>
</div>
</body></html>"""

# ---------------------------------------------------------
# ROUTES: EMPLOYEE APP (Port 3456)
# ---------------------------------------------------------
@app.route('/', methods=['GET', 'POST'])
def index():
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
        shifts = [{"label": s["label"], "time": s["time"], "active": is_within_window(s["time"])} for s in get_today_schedule(e["type"])]
        emp_data.append({"name": e["name"], "shifts": shifts, "kpi": get_monthly_kpi(e["name"])})

    return render_template_string(EMPLOYEE_HTML, employees=emp_data, today_logs=get_today_logs(), now_time=datetime.now().strftime("%H:%M:%S"), local_ip=LOCAL_IP, port=PORT, message=message)

@app.route('/ai')
def ai_page():
    return render_template_string(AI_CHAT_HTML, title="Office AI Assistant")

@app.route('/kpi')
def kpi_page():
    emp_data = []
    for e in EMPLOYEES:
        punctuality = get_punctuality_kpi(e["name"])
        attendance = get_monthly_kpi(e["name"])
        emp_data.append({"name": e["name"], "punctuality": punctuality, "attendance": attendance})
    return render_template_string(KPI_HTML, employees=emp_data)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message', '')
    if not ai_model:
        return jsonify({"response": "Error: GEMINI_API_KEY is missing or invalid in your .env file."})
    try:
        prompt = f"You are the Office AI Assistant for Afaq Alnaseem Trading LLC. Be helpful, concise, and professional to the staff. User says: {user_message}"
        response = ai_model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"response": f"API Error: {str(e)}"})

@manager_app.route('/')
def manager_index():
    emp_data = []
    for e in EMPLOYEES:
        shifts = [{"label": s["label"], "time": s["time"]} for s in get_today_schedule(e["type"])]
        emp_data.append({"name": e["name"], "shifts": shifts, "kpi": get_monthly_kpi(e["name"])})
    return render_template_string(MANAGER_HTML, employees=emp_data, today_logs=get_today_logs(), now_time=datetime.now().strftime("%H:%M:%S"))

@manager_app.route('/ai')
def manager_ai_page():
    return render_template_string(AI_CHAT_HTML, title="Owner AI Assistant")

@manager_app.route('/kpi')
def manager_kpi_page():
    emp_data = []
    for e in EMPLOYEES:
        punctuality = get_punctuality_kpi(e["name"])
        attendance = get_monthly_kpi(e["name"])
        emp_data.append({"name": e["name"], "punctuality": punctuality, "attendance": attendance})
    return render_template_string(KPI_HTML, employees=emp_data)

@manager_app.route('/api/chat', methods=['POST'])
def manager_api_chat():
    data = request.json or {}
    user_message = data.get('message', '')

    # Try Shopify AI Agent (DeepSeek + real store data) first
    shopify_fallback = False
    try:
        shopify_agent = ShopifyAIAgent()
        print(f"[SHOP] ready={shopify_agent.ready()}  deepseek={'yes' if shopify_agent.deepseek_key else 'NO'}  url={'yes' if shopify_agent.store_url else 'NO'}  token={'yes' if shopify_agent.token else 'NO'}")
        if shopify_agent.ready():
            answer = shopify_agent.chat(user_message)
            if isinstance(answer, str) and any(flag in answer.lower() for flag in ["error", "no_data", "missing", "deepseek error"]):
                print(f"[SHOP] fallback trigger: {answer}")
                shopify_fallback = True
            else:
                return jsonify({"response": answer})
        else:
            shopify_fallback = True
    except Exception as e:
        print(f"[SHOP] exception: {e}")
        shopify_fallback = True

    if shopify_fallback:
        print("[MANAGER] Shopify agent failed, falling back to Gemini")

    # Fallback to Gemini
    if not ai_model:
        return jsonify({"response": "Error: No AI backend configured. Add DEEPSEEK_API_KEY or GEMINI_API_KEY to .env."})
    try:
        prompt = f"You are the Owner AI Assistant for Afaq Alnaseem Trading LLC. You are talking to a manager/owner. Be analytical and strategic. User says: {user_message}"
        response = ai_model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"response": f"API Error: {str(e)}"})

# ---------------------------------------------------------
# RUNNER LOGIC
# ---------------------------------------------------------
def run_manager_app():
    print(f" * Running Manager Dashboard on http://127.0.0.1:{MANAGER_PORT}")
    manager_app.run(host='0.0.0.0', port=MANAGER_PORT, debug=False, use_reloader=False)

@manager_app.route('/profit')
def profit_page():
    tpl = os.path.join(BASE_DIR, 'templates', 'profit_report.html')
    if os.path.exists(tpl):
        with open(tpl, 'r', encoding='utf-8') as f:
            return f.read()
    return "<h1>Template not found</h1>"

@manager_app.route('/api/profit-report', methods=['POST'])
def api_profit_report():
    data = request.json or {}
    from_date = data.get('from_date', '')
    to_date = data.get('to_date', '')
    channel = data.get('channel', 'all')
    if not from_date or not to_date:
        return jsonify({"status": "error", "message": "Missing date range"})
    try:
        engine = ProfitEngine()
        if not engine.ready():
            return jsonify({"status": "not_configured"})
        result = engine.build_report(from_date, to_date, channel)
        if result.get("status") != "success":
            return jsonify(result)

        rows = result.get("rows", [])
        online_rows = [r for r in rows if r["channel_group"] == "Online"]
        pos_rows = [r for r in rows if r["channel_group"] != "Online"]

        def agg(items):
            cost = [r for r in items if r.get("cost_price") is not None]
            return {
                "total_orders": len(set(r["order_number"] for r in items)),
                "line_items": len(items),
                "gross_sales": round(sum(r["discount_amount"] + r["sold_price_aed"] for r in items), 2),
                "discounts": round(sum(r["discount_amount"] for r in items), 2),
                "net_sales": round(sum(r["sold_price_aed"] for r in items), 2),
                "shipping_charged": round(sum(r["shipping_charged"] for r in items), 2),
                "shipping_upsell": round(sum(r["shipping_upsell"] for r in items), 2),
                "product_upsell": round(sum(r["product_upsell"] for r in items), 2),
                "upsell": round(sum(r["product_upsell"] for r in items), 2),
                "returns": round(sum(r["returns"] for r in items), 2),
                "final_sales": round(sum(r["sold_price_aed"] + r["product_upsell"] + r["shipping_upsell"] for r in items), 2),
                "cogs_total": round(sum(r["cost_price"] for r in cost), 2) if cost else 0,
                "gross_profit": round(sum(r["profit"] for r in items if r.get("profit") is not None), 2) if any(r.get("profit") is not None for r in items) else 0,
                "cogs_available": bool(cost),
            }

        combined = agg(rows)
        combined["total_line_items"] = len(rows)

        mapped_orders = []
        for r in rows:
            mapped_orders.append({
                "order_number": r["order_number"],
                "order_date": r["order_date"],
                "channel_group": r["channel_group"],
                "channel_source": r["channel_source"],
                "customer_name": r["customer_name"],
                "shipping_city": r["shipping_city"],
                "gross_sales": r["discount_amount"] + r["sold_price_aed"],
                "discounts": r["discount_amount"],
                "net_sales": r["sold_price_aed"],
                "upsell": r["product_upsell"],
                "shipping_charge": r["shipping_charged"],
                "shipping_upsell": r["shipping_upsell"],
                "final_sales": round(r["sold_price_aed"] + r["product_upsell"] + r["shipping_upsell"], 2),
                "cogs": r["cost_price"],
                "gross_profit": r["profit"],
            })

        return jsonify({
            "status": "success",
            "period": {"from": from_date, "to": to_date},
            "summary": combined,
            "online": agg(online_rows),
            "pos": agg(pos_rows),
            "orders": mapped_orders,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    threading.Thread(target=run_manager_app, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
