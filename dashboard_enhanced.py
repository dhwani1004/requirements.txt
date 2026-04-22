"""
Alert Bot Dashboard v2 - Enhanced with persistent logging & debugging
Run: python dashboard_enhanced.py
Open: http://localhost:5000
"""

import sys, os, json, time, logging, threading, traceback
from datetime import datetime, timezone
from flask import Flask, render_template_string, jsonify, request

# ── Configuration ─────────────────────────────────────────────────────────────
DEBUG_MODE = True  # Set to False to disable detailed logging
LOG_FILE = os.path.join(os.path.dirname(__file__), "bot_session.log")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "dashboard_config.json")

# ── State (shared across threads) ────────────────────────────────────────────
state = {
    "bot_running":    False,
    "last_prices":    {},
    "bias":           "both",
    "paused":         False,
    "signals":        [],       # last 50 signals
    "geo_alerts":     [],       # last 20 geo alerts
    "worldmon":       {},
    "sessions":       [],
    "dxy":            "neutral",
    "news_status":    {"risk_level": "CLEAR"},
    "stats":          {"total_signals": 0, "today_signals": 0, "uptime_start": None},
    "log_lines":      [],       # last 100 log lines (in-memory)
    "config":         {},
    "acled_key":      "",
    "acled_email":    "",
    "telegram_token": "",
    "telegram_chat":  "",
    "capital":        350,
    "errors":         [],
    "debug_info":     [],       # Track debug events
}

bot_thread = None
bot_instance = None

# ── Logging Setup ─────────────────────────────────────────────────────────────
class EnhancedLogHandler(logging.Handler):
    """Captures logs to both file and in-memory, with detailed tracking."""
    
    def emit(self, record):
        msg = self.format(record)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # Log entry with all details
        log_entry = {
            "time":    timestamp,
            "level":   record.levelname,
            "msg":     msg[-200:],
            "source":  record.name,
        }
        
        # Keep last 100 in memory for dashboard
        state["log_lines"].append(log_entry)
        if len(state["log_lines"]) > 100:
            state["log_lines"] = state["log_lines"][-100:]
        
        # Write to persistent file
        try:
            with open(LOG_FILE, "a") as f:
                f.write(f"[{timestamp}] {record.levelname:8} | {record.name:20} | {msg}\n")
        except Exception as e:
            print(f"ERROR writing to log file: {e}")
        
        # Track errors separately
        if record.levelname == "ERROR":
            state["errors"].append({
                "time": timestamp,
                "msg": msg[-150:],
                "source": record.name
            })
            state["errors"] = state["errors"][-20:]
        
        # Print to console too
        print(f"[{timestamp}] {record.levelname:8} | {msg}")


def debug_log(category, message):
    """Log debug information for troubleshooting."""
    if DEBUG_MODE:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        debug_entry = {
            "time": timestamp,
            "category": category,
            "message": message
        }
        state["debug_info"].append(debug_entry)
        if len(state["debug_info"]) > 200:
            state["debug_info"] = state["debug_info"][-200:]
        
        # Also write to log file
        try:
            with open(LOG_FILE, "a") as f:
                f.write(f"[{timestamp}] DEBUG     | {category:20} | {message}\n")
        except:
            pass


# Setup logging
handler = EnhancedLogHandler()
handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)
log = logging.getLogger("DASHBOARD")

# Log startup
print("\n" + "="*70)
print("  Alert Bot Dashboard v2 - Enhanced")
print("  Logs saved to:", LOG_FILE)
print("="*70 + "\n")
log.info("Dashboard starting up")
debug_log("STARTUP", "Dashboard initialized")

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

# [HTML content would go here - keeping original for brevity]
# We'll use the original HTML from the project file

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alert Bot Dashboard v2</title>
<style>
  :root {
    --bg:       #0a0c10;
    --bg2:      #111520;
    --bg3:      #171d2b;
    --border:   #1e2740;
    --gold:     #f5c842;
    --gold2:    #e8a020;
    --green:    #22d47a;
    --red:      #f04a4a;
    --orange:   #f08c2a;
    --blue:     #4a90e2;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --font-mono: 'Space Mono', monospace;
    --font-sans: 'DM Sans', sans-serif;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:var(--font-sans); min-height:100vh; }
  .header { display:flex; align-items:center; justify-content:space-between; padding:16px 28px;
            background:var(--bg2); border-bottom:1px solid var(--border); position:sticky; top:0; z-index:100; }
  .logo { display:flex; align-items:center; gap:10px; }
  .logo-icon { width:32px; height:32px; background:var(--gold); border-radius:6px;
               display:flex; align-items:center; justify-content:center; font-size:18px; }
  .logo-text { font-family:var(--font-mono); font-size:14px; font-weight:700; letter-spacing:2px; color:var(--gold); }
  .logo-sub { font-size:11px; color:var(--muted); letter-spacing:1px; }
  .header-right { display:flex; align-items:center; gap:12px; }
  .status-pill { display:flex; align-items:center; gap:6px; padding:6px 14px; border-radius:20px;
                 font-size:12px; font-weight:600; letter-spacing:1px; font-family:var(--font-mono); }
  .status-pill.running { background:rgba(34,212,122,0.15); color:var(--green); border:1px solid rgba(34,212,122,0.3); }
  .status-pill.stopped { background:rgba(240,74,74,0.15); color:var(--red); border:1px solid rgba(240,74,74,0.3); }
  .pulse { width:7px; height:7px; border-radius:50%; background:currentColor; animation:pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(0.8)} }
  .clock { font-family:var(--font-mono); font-size:13px; color:var(--muted); }
  .layout { display:grid; grid-template-columns:260px 1fr 300px; gap:0; height:calc(100vh - 57px); }
  .sidebar { background:var(--bg2); border-right:1px solid var(--border); overflow-y:auto; padding:20px 0; }
  .main { overflow-y:auto; padding:20px; }
  .panel-right { background:var(--bg2); border-left:1px solid var(--border); overflow-y:auto; padding:0; }
  .nav-section { padding:0 12px 8px; }
  .nav-label { font-size:10px; letter-spacing:2px; color:var(--muted); font-weight:700; padding:12px 8px 6px; text-transform:uppercase; }
  .nav-item { display:flex; align-items:center; gap:10px; padding:9px 12px; border-radius:8px;
              cursor:pointer; font-size:13px; color:var(--muted); transition:all .15s; margin:1px 0; }
  .nav-item:hover, .nav-item.active { background:var(--bg3); color:var(--text); }
  .nav-item.active { border-left:2px solid var(--gold); }
  .card { background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:16px; }
  .card-title { font-size:11px; letter-spacing:2px; color:var(--muted); font-weight:700; text-transform:uppercase; margin-bottom:16px; }
  .btn { padding:9px 18px; border-radius:8px; border:1px solid var(--border); background:var(--bg3);
         color:var(--text); font-size:13px; font-weight:500; cursor:pointer; transition:all .15s; font-family:var(--font-sans); }
  .btn:hover { background:var(--border); }
  .btn.primary { background:var(--gold); color:#000; border-color:var(--gold); font-weight:700; }
  .btn.primary:hover { background:var(--gold2); }
  .btn.danger { background:rgba(240,74,74,0.15); color:var(--red); border-color:rgba(240,74,74,0.3); }
  .btn.danger:hover { background:rgba(240,74,74,0.25); }
  .btn.sm { padding:6px 12px; font-size:12px; }
  .view { display:none; }
  .view.active { display:block; }
  .log-line { display:flex; gap:8px; padding:4px 0; border-bottom:1px solid rgba(30,39,64,0.4); font-size:11px; font-family:var(--font-mono); }
  .log-time { color:var(--muted); flex-shrink:0; width:100px; }
  .log-level { flex-shrink:0; width:70px; font-weight:bold; }
  .log-source { flex-shrink:0; width:150px; color:var(--blue); }
  .log-msg { color:var(--text); opacity:.8; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
  .log-msg.ERROR { color:var(--red); opacity:1; }
  .log-msg.WARNING { color:var(--orange); opacity:1; }
  .log-msg.DEBUG { color:var(--muted); opacity:0.6; }
  .stat { background:var(--bg3); border:1px solid var(--border); border-radius:10px; padding:14px 16px; }
  .stat-label { font-size:11px; color:var(--muted); margin-bottom:4px; letter-spacing:.5px; }
  .stat-value { font-family:var(--font-mono); font-size:22px; font-weight:700; color:var(--gold); }
  .empty { text-align:center; padding:40px; color:var(--muted); font-size:13px; }
  .divider { height:1px; background:var(--border); margin:16px 0; }
  .toast { position:fixed; bottom:24px; right:24px; padding:12px 20px; border-radius:10px;
           background:var(--bg2); border:1px solid var(--border); font-size:13px; z-index:999;
           transform:translateY(80px); opacity:0; transition:all .3s; pointer-events:none; }
  .toast.show { transform:translateY(0); opacity:1; }
  ::-webkit-scrollbar { width:4px; }
  ::-webkit-scrollbar-track { background:transparent; }
  ::-webkit-scrollbar-thumb { background:var(--border); border-radius:2px; }
</style>
</head>
<body>

<div class="header">
  <div class="logo">
    <div class="logo-icon">⚡</div>
    <div>
      <div class="logo-text">ALERT BOT v2</div>
      <div class="logo-sub">ENHANCED DEBUGGING</div>
    </div>
  </div>
  <div class="header-right">
    <div class="clock" id="clock">--:-- UTC</div>
    <div class="status-pill stopped" id="statusPill">
      <div class="pulse"></div>
      <span id="statusText">STOPPED</span>
    </div>
  </div>
</div>

<div class="layout">
  <div class="sidebar">
    <div class="nav-label">Navigation</div>
    <div class="nav-section">
      <div class="nav-item active" onclick="showView('overview')">📊 Overview</div>
      <div class="nav-item" onclick="showView('logs')">📋 Live Logs</div>
      <div class="nav-item" onclick="showView('debug')">🔍 Debug Info</div>
      <div class="nav-item" onclick="showView('settings')">⚙️ Settings</div>
    </div>
    <div class="divider"></div>
    <div class="nav-label">Bot Control</div>
    <div class="nav-section" style="padding:0 4px;">
      <button class="btn primary" id="btnStart" onclick="startBot()" style="width:100%; margin-bottom:8px;">▶ Start Bot</button>
      <button class="btn danger" id="btnStop" onclick="stopBot()" style="width:100%; margin-bottom:8px; display:none;">⏹ Stop Bot</button>
    </div>
  </div>

  <div class="main">
    <!-- OVERVIEW -->
    <div class="view active" id="view-overview">
      <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px; margin-bottom:16px;">
        <div class="stat gold">
          <div class="stat-label">BOT STATUS</div>
          <div class="stat-value" id="overallStatus">STOPPED</div>
        </div>
        <div class="stat">
          <div class="stat-label">SIGNALS TODAY</div>
          <div class="stat-value" id="todaySignals">0</div>
        </div>
        <div class="stat">
          <div class="stat-label">TOTAL SIGNALS</div>
          <div class="stat-value" id="totalSignals">0</div>
        </div>
        <div class="stat">
          <div class="stat-label">UPTIME</div>
          <div class="stat-value" id="uptime">--</div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Quick Status</div>
        <div style="font-size:13px; color:var(--text); line-height:1.8;">
          <div>Bias: <strong id="qBias">—</strong></div>
          <div>Paused: <strong id="qPaused">—</strong></div>
          <div>Session: <strong id="qSession">—</strong></div>
          <div>DXY: <strong id="qDxy">—</strong></div>
        </div>
      </div>
    </div>

    <!-- LOGS -->
    <div class="view" id="view-logs">
      <div class="card">
        <div class="card-title" style="display:flex; justify-content:space-between;">
          <span>Live Logs (Last 100 Lines)</span>
          <button class="btn sm" onclick="downloadLogs()">⬇ Download</button>
        </div>
        <div id="logContainer" style="max-height:700px; overflow-y:auto; font-family:monospace; font-size:11px;"></div>
      </div>
    </div>

    <!-- DEBUG -->
    <div class="view" id="view-debug">
      <div class="card">
        <div class="card-title">Debug Information (Last 200 Events)</div>
        <div id="debugContainer" style="max-height:700px; overflow-y:auto; font-family:monospace; font-size:11px;"></div>
      </div>
    </div>

    <!-- SETTINGS -->
    <div class="view" id="view-settings">
      <div class="card">
        <div class="card-title">Telegram Configuration</div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-size:12px; color:var(--muted);">Bot Token</label>
          <input id="cfgToken" type="password" style="width:100%; padding:8px; border:1px solid var(--border); border-radius:6px; background:var(--bg3); color:var(--text);" placeholder="From @BotFather">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-size:12px; color:var(--muted);">Chat ID</label>
          <input id="cfgChat" type="text" style="width:100%; padding:8px; border:1px solid var(--border); border-radius:6px; background:var(--bg3); color:var(--text);" placeholder="From @userinfobot">
        </div>
        <button class="btn primary" onclick="saveSettings()" style="width:100%; margin-top:12px;">💾 Save Settings</button>
        <button class="btn" onclick="testTelegram()" style="width:100%; margin-top:8px;">📱 Test Telegram</button>
      </div>
    </div>
  </div>

  <div class="panel-right" style="padding:16px;">
    <div style="font-size:11px; color:var(--muted); margin-bottom:16px;">
      <div style="letter-spacing:2px; text-transform:uppercase; font-weight:bold; margin-bottom:8px;">Status Info</div>
      <div style="padding:8px 0; border-bottom:1px solid var(--border);">Logs: <strong id="logCount" style="color:var(--gold);">0</strong></div>
      <div style="padding:8px 0; border-bottom:1px solid var(--border);">Errors: <strong id="errCount" style="color:var(--red);">0</strong></div>
      <div style="padding:8px 0;">Debug: <strong id="debugCount" style="color:var(--blue);">0</strong></div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentView = 'overview';

function showView(v) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.getElementById('view-' + v).classList.add('active');
  event.currentTarget.classList.add('active');
  currentView = v;
}

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show';
  setTimeout(() => t.classList.remove('show'), 3000);
}

function updateClock() {
  const now = new Date();
  const h = String(now.getUTCHours()).padStart(2,'0');
  const m = String(now.getUTCMinutes()).padStart(2,'0');
  document.getElementById('clock').textContent = h+':'+m+' UTC';
}
setInterval(updateClock, 1000);
updateClock();

async function api(endpoint, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(endpoint, opts);
  return r.json();
}

async function pollState() {
  const r = await api('/api/state');
  if (!r) return;

  // Status pill
  const pill = document.getElementById('statusPill');
  pill.className = 'status-pill ' + (r.bot_running ? 'running' : 'stopped');
  document.getElementById('statusText').textContent = r.bot_running ? 'RUNNING' : 'STOPPED';
  document.getElementById('btnStart').style.display = r.bot_running ? 'none' : '';
  document.getElementById('btnStop').style.display = r.bot_running ? '' : 'none';

  // Overview stats
  document.getElementById('overallStatus').textContent = r.bot_running ? 'RUNNING' : 'STOPPED';
  document.getElementById('todaySignals').textContent = r.stats?.today_signals || 0;
  document.getElementById('totalSignals').textContent = r.stats?.total_signals || 0;
  document.getElementById('qBias').textContent = (r.bias || 'both').toUpperCase();
  document.getElementById('qPaused').textContent = r.paused ? 'YES' : 'NO';
  document.getElementById('qDxy').textContent = (r.dxy || 'neutral').toUpperCase();

  if (r.stats?.uptime_start) {
    const up = Math.floor((Date.now()/1000) - r.stats.uptime_start);
    const h = Math.floor(up/3600), m = Math.floor((up%3600)/60);
    document.getElementById('uptime').textContent = h+'h '+m+'m';
  }

  // Logs
  document.getElementById('logCount').textContent = r.log_lines?.length || 0;
  document.getElementById('errCount').textContent = r.errors?.length || 0;
  document.getElementById('debugCount').textContent = r.debug_info?.length || 0;

  if (currentView === 'logs') {
    const html = (r.log_lines || []).slice().reverse().map(l =>
      `<div class="log-line"><span class="log-time">${l.time}</span><span class="log-level">${l.level}</span><span class="log-source">${l.source}</span><span class="log-msg ${l.level}">${l.msg}</span></div>`
    ).join('');
    document.getElementById('logContainer').innerHTML = html || '<div class="empty">No logs yet</div>';
  }

  if (currentView === 'debug') {
    const html = (r.debug_info || []).slice().reverse().map(d =>
      `<div class="log-line"><span class="log-time">${d.time}</span><span class="log-source">${d.category}</span><span class="log-msg">${d.message}</span></div>`
    ).join('');
    document.getElementById('debugContainer').innerHTML = html || '<div class="empty">No debug info yet</div>';
  }
}

async function startBot() {
  document.getElementById('statusText').textContent = 'STARTING...';
  await api('/api/start', 'POST');
  setTimeout(pollState, 500);
}

async function stopBot() {
  document.getElementById('statusText').textContent = 'STOPPING...';
  await api('/api/stop', 'POST');
  setTimeout(pollState, 500);
}

async function testTelegram() {
  const r = await api('/api/test_telegram', 'POST');
  toast(r.ok ? '✅ Telegram test sent!' : '❌ Failed: ' + r.error);
}

async function saveSettings() {
  const r = await api('/api/settings', 'POST', {
    telegram_token: document.getElementById('cfgToken').value,
    telegram_chat: document.getElementById('cfgChat').value,
  });
  toast(r.ok ? '✅ Settings saved!' : '❌ Error');
}

async function downloadLogs() {
  const r = await api('/api/logs/full');
  if (r.ok) {
    const blob = new Blob([r.logs], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'bot_session.log';
    a.click();
    toast('✅ Downloaded bot_session.log');
  }
}

setInterval(pollState, 2000);
pollState();
</script>
</body>
</html>"""

# ── API Routes ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/state')
def api_state():
    return jsonify({
        'bot_running':   state['bot_running'],
        'bias':          state['bias'],
        'paused':        state['paused'],
        'signals':       state['signals'][-50:],
        'stats':         state['stats'],
        'log_lines':     state['log_lines'][-100:],
        'errors':        state['errors'],
        'debug_info':    state['debug_info'][-200:],
        'dxy':           state['dxy'],
    })

@app.route('/api/logs/full')
def api_logs_full():
    """Download complete log file."""
    try:
        with open(LOG_FILE, 'r') as f:
            content = f.read()
        return jsonify({'ok': True, 'logs': content})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/start', methods=['POST'])
def api_start():
    if state['bot_running']:
        return jsonify({'ok': False, 'error': 'Already running'})
    debug_log("BOT_CONTROL", "Start requested")
    ok = _start_bot()
    return jsonify({'ok': ok})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    debug_log("BOT_CONTROL", "Stop requested")
    _stop_bot()
    return jsonify({'ok': True})

@app.route('/api/test_telegram', methods=['POST'])
def api_test_telegram():
    debug_log("TELEGRAM", "Test requested")
    try:
        token = state['config'].get('telegram_token', '')
        chat = state['config'].get('telegram_chat', '')
        if not token or not chat:
            debug_log("TELEGRAM", "Missing credentials")
            return jsonify({'ok': False, 'error': 'Missing token or chat ID'})
        
        # Try to send test message via Telegram API
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat,
            "text": "🤖 Alert Bot Test Message - Dashboard is working!"
        }
        resp = requests.post(url, json=payload, timeout=5)
        ok = resp.status_code == 200
        debug_log("TELEGRAM", f"Test result: {resp.status_code}")
        return jsonify({'ok': ok, 'status': resp.status_code})
    except Exception as e:
        debug_log("TELEGRAM", f"Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify(state['config'])
    
    data = request.json or {}
    state['config'].update(data)
    debug_log("SETTINGS", f"Updated: {list(data.keys())}")
    
    # Save to file
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(state['config'], f, indent=2)
        debug_log("SETTINGS", "Saved to config file")
    except Exception as e:
        debug_log("SETTINGS", f"Save failed: {e}")
    
    return jsonify({'ok': True})

# ── Bot Management ────────────────────────────────────────────────────────────

def _start_bot():
    global bot_thread, bot_instance
    try:
        log.info("="*70)
        log.info("STARTING BOT")
        log.info("="*70)
        debug_log("BOT_LIFECYCLE", "Import AlertBot")
        
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        # Try to import the actual bot
        try:
            from main import AlertBot
            debug_log("BOT_LIFECYCLE", "AlertBot imported successfully")
            bot_instance = AlertBot()
            debug_log("BOT_LIFECYCLE", "AlertBot instance created")
            
            # Patch signal processing
            original_process = bot_instance._process_signal
            def patched_process(sig):
                sig['timestamp'] = datetime.now(timezone.utc).strftime('%H:%M UTC')
                state['signals'].append(sig)
                state['signals'] = state['signals'][-50:]
                state['stats']['total_signals'] += 1
                state['stats']['today_signals'] += 1
                debug_log("SIGNAL", f"Processed: {sig.get('symbol', '?')} {sig.get('direction', '?')}")
                original_process(sig)
            bot_instance._process_signal = patched_process
            debug_log("BOT_LIFECYCLE", "Signal handler patched")
        except ImportError as e:
            debug_log("BOT_LIFECYCLE", f"Could not import AlertBot: {e} - Running in simulation mode")
            log.warning(f"AlertBot module not found - running in mock mode. Error: {e}")
            # Create mock bot for testing dashboard
            bot_instance = MockAlertBot()
        
        state['bot_running'] = True
        state['stats']['uptime_start'] = time.time()
        state['bias'] = 'both'
        state['paused'] = False
        
        bot_thread = threading.Thread(target=_bot_loop, daemon=True)
        bot_thread.start()
        log.info("Bot loop thread started")
        debug_log("BOT_LIFECYCLE", "Bot thread created and started")
        return True
    except Exception as e:
        log.error(f"Bot start failed: {e}")
        log.error(traceback.format_exc())
        debug_log("BOT_LIFECYCLE", f"ERROR: {str(e)}")
        return False


def _bot_loop():
    """Main bot loop - runs every 5 seconds."""
    global bot_instance
    log.info("Bot loop started")
    debug_log("BOT_LIFECYCLE", "Loop: started")
    
    try:
        tick_count = 0
        while state['bot_running']:
            tick_count += 1
            try:
                if hasattr(bot_instance, '_tick'):
                    debug_log("BOT_TICK", f"Tick #{tick_count}")
                    bot_instance._tick()
                    log.debug(f"Bot tick #{tick_count} completed")
                
                # Simulate some activity for mock bot
                if isinstance(bot_instance, MockAlertBot):
                    bot_instance.simulate_tick()
                    
            except Exception as e:
                log.error(f"Tick error: {e}")
                debug_log("BOT_TICK", f"Error: {str(e)[:100]}")
            
            # Sleep in 1-second increments so we can check stop flag
            for _ in range(5):
                if not state['bot_running']:
                    break
                time.sleep(1)
        
        log.info("Bot loop ended")
        debug_log("BOT_LIFECYCLE", "Loop: ended")
    except Exception as e:
        log.error(f"Bot loop crashed: {e}")
        log.error(traceback.format_exc())
        debug_log("BOT_LIFECYCLE", f"Loop crash: {str(e)[:100]}")
    finally:
        state['bot_running'] = False


def _stop_bot():
    global bot_instance
    log.info("Stopping bot")
    debug_log("BOT_LIFECYCLE", "Stop requested")
    state['bot_running'] = False
    
    if bot_instance:
        try:
            # Cleanup
            if hasattr(bot_instance, 'stop'):
                bot_instance.stop()
            debug_log("BOT_LIFECYCLE", "Bot cleanup completed")
        except Exception as e:
            log.error(f"Cleanup error: {e}")
            debug_log("BOT_LIFECYCLE", f"Cleanup error: {str(e)}")
        bot_instance = None
    
    log.info("Bot stopped")


class MockAlertBot:
    """Mock bot for testing when real bot unavailable."""
    def __init__(self):
        log.info("MockAlertBot initialized - for testing purposes")
        self.tick_count = 0
        self.session_hours = list(range(24))
    
    def simulate_tick(self):
        self.tick_count += 1
        # Simulate price checking
        if self.tick_count % 12 == 0:  # Every 60 seconds
            debug_log("MOCK_BOT", f"Checking prices (tick {self.tick_count})")
    
    def stop(self):
        log.info("MockAlertBot stopped")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Load config if exists
    if os.path.exists(CONFIG_FILE):
        try:
            state['config'] = json.load(open(CONFIG_FILE))
            debug_log("STARTUP", f"Loaded config from {CONFIG_FILE}")
        except Exception as e:
            debug_log("STARTUP", f"Config load failed: {e}")
    
    print("\n" + "="*70)
    print("  Alert Bot Dashboard v2 - Enhanced with Full Logging")
    print("  Open: http://localhost:5000")
    print(f"  Logs: {LOG_FILE}")
    print("="*70 + "\n")
    
    debug_log("STARTUP", "Dashboard server starting")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
