"""
Alert Bot Dashboard
Run once: python dashboard.py
Open browser: http://localhost:5000
Control everything from the browser — no more terminal, no more file editing.
"""

import sys, os, json, time, logging, threading
from datetime import datetime, timezone
from flask import Flask, render_template_string, jsonify, request

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
    "log_lines":      [],       # last 100 log lines
    "config":         {},
    "acled_key":      "",
    "acled_email":    "",
    "telegram_token": "",
    "telegram_chat":  "",
    "capital":        350,
    "errors":         [],
}

bot_thread = None
bot_instance = None

# ── Logging capture ───────────────────────────────────────────────────────────
class DashboardLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        state["log_lines"].append({
            "time":  datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": record.levelname,
            "msg":   msg[-120:],
        })
        if len(state["log_lines"]) > 100:
            state["log_lines"] = state["log_lines"][-100:]
        if record.levelname == "ERROR":
            state["errors"].append({"time": datetime.now(timezone.utc).strftime("%H:%M:%S"), "msg": msg[-100:]})
            state["errors"] = state["errors"][-10:]

handler = DashboardLogHandler()
handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger("DASHBOARD")

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alert Bot Dashboard</title>

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

  /* Header */
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

  /* Layout */
  .layout { display:grid; grid-template-columns:260px 1fr 300px; gap:0; height:calc(100vh - 57px); }
  .sidebar { background:var(--bg2); border-right:1px solid var(--border); overflow-y:auto; padding:20px 0; }
  .main { overflow-y:auto; padding:20px; }
  .panel-right { background:var(--bg2); border-left:1px solid var(--border); overflow-y:auto; padding:0; }

  /* Sidebar nav */
  .nav-section { padding:0 12px 8px; }
  .nav-label { font-size:10px; letter-spacing:2px; color:var(--muted); font-weight:700; padding:12px 8px 6px; text-transform:uppercase; }
  .nav-item { display:flex; align-items:center; gap:10px; padding:9px 12px; border-radius:8px;
              cursor:pointer; font-size:13px; color:var(--muted); transition:all .15s; margin:1px 0; }
  .nav-item:hover, .nav-item.active { background:var(--bg3); color:var(--text); }
  .nav-item.active { border-left:2px solid var(--gold); }
  .nav-dot { width:6px; height:6px; border-radius:50%; background:var(--muted); flex-shrink:0; }
  .nav-dot.green { background:var(--green); box-shadow:0 0 6px var(--green); }
  .nav-dot.red { background:var(--red); }
  .nav-dot.orange { background:var(--orange); }
  .nav-dot.gold { background:var(--gold); }

  /* Cards */
  .card { background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:16px; }
  .card-title { font-size:11px; letter-spacing:2px; color:var(--muted); font-weight:700; text-transform:uppercase; margin-bottom:16px; }
  .card-grid { display:grid; gap:12px; }
  .card-grid-2 { grid-template-columns:1fr 1fr; }
  .card-grid-3 { grid-template-columns:1fr 1fr 1fr; }
  .card-grid-4 { grid-template-columns:1fr 1fr 1fr 1fr; }

  /* Stat tiles */
  .stat { background:var(--bg3); border:1px solid var(--border); border-radius:10px; padding:14px 16px; }
  .stat-label { font-size:11px; color:var(--muted); margin-bottom:4px; letter-spacing:.5px; }
  .stat-value { font-family:var(--font-mono); font-size:22px; font-weight:700; color:var(--gold); }
  .stat-sub { font-size:11px; color:var(--muted); margin-top:2px; }
  .stat.green .stat-value { color:var(--green); }
  .stat.red .stat-value { color:var(--red); }
  .stat.blue .stat-value { color:var(--blue); }

  /* Sessions */
  .session-row { display:flex; align-items:center; justify-content:space-between;
                 padding:10px 14px; border-radius:8px; margin-bottom:6px; border:1px solid var(--border); }
  .session-row.active { background:rgba(245,200,66,0.08); border-color:rgba(245,200,66,0.3); }
  .session-row.blackout { background:rgba(240,140,42,0.08); border-color:rgba(240,140,42,0.2); }
  .session-name { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:500; }
  .session-time { font-family:var(--font-mono); font-size:11px; color:var(--muted); }
  .badge { padding:3px 8px; border-radius:10px; font-size:10px; font-weight:700; letter-spacing:.5px; }
  .badge-active { background:rgba(34,212,122,0.2); color:var(--green); }
  .badge-blackout { background:rgba(240,140,42,0.2); color:var(--orange); }
  .badge-closed { background:var(--bg3); color:var(--muted); }

  /* Signal cards */
  .signal-card { background:var(--bg3); border:1px solid var(--border); border-radius:10px;
                 padding:14px; margin-bottom:10px; cursor:pointer; transition:border-color .15s; }
  .signal-card:hover { border-color:var(--gold); }
  .signal-card.buy { border-left:3px solid var(--green); }
  .signal-card.sell { border-left:3px solid var(--red); }
  .signal-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .signal-sym { font-family:var(--font-mono); font-size:14px; font-weight:700; }
  .signal-action { font-size:11px; font-weight:700; letter-spacing:1px; padding:3px 8px; border-radius:6px; }
  .signal-action.buy { background:rgba(34,212,122,0.2); color:var(--green); }
  .signal-action.sell { background:rgba(240,74,74,0.2); color:var(--red); }
  .signal-row { display:flex; justify-content:space-between; font-size:12px; color:var(--muted); margin-top:4px; }
  .signal-row span:last-child { color:var(--text); font-family:var(--font-mono); font-size:11px; }
  .signal-score { font-family:var(--font-mono); font-size:11px; color:var(--gold); }
  .signal-inst { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
  .inst-chip { font-size:10px; padding:2px 7px; border-radius:10px; }
  .inst-ok { background:rgba(34,212,122,0.15); color:var(--green); }
  .inst-fail { background:rgba(240,74,74,0.1); color:var(--red); }

  /* Controls */
  .controls { display:flex; gap:8px; flex-wrap:wrap; }
  .btn { padding:9px 18px; border-radius:8px; border:1px solid var(--border); background:var(--bg3);
         color:var(--text); font-size:13px; font-weight:500; cursor:pointer; transition:all .15s;
         font-family:var(--font-sans); }
  .btn:hover { background:var(--border); }
  .btn.primary { background:var(--gold); color:#000; border-color:var(--gold); font-weight:700; }
  .btn.primary:hover { background:var(--gold2); }
  .btn.danger { background:rgba(240,74,74,0.15); color:var(--red); border-color:rgba(240,74,74,0.3); }
  .btn.danger:hover { background:rgba(240,74,74,0.25); }
  .btn.success { background:rgba(34,212,122,0.15); color:var(--green); border-color:rgba(34,212,122,0.3); }
  .btn.success:hover { background:rgba(34,212,122,0.25); }
  .btn.active { background:rgba(245,200,66,0.2); color:var(--gold); border-color:var(--gold); }
  .btn.sm { padding:6px 12px; font-size:12px; }

  /* Form */
  .form-group { margin-bottom:14px; }
  .form-label { font-size:12px; color:var(--muted); margin-bottom:5px; display:block; letter-spacing:.5px; }
  .form-input { width:100%; padding:9px 12px; background:var(--bg3); border:1px solid var(--border);
                border-radius:8px; color:var(--text); font-size:13px; font-family:var(--font-sans); outline:none; }
  .form-input:focus { border-color:var(--gold); }
  .form-row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .form-hint { font-size:11px; color:var(--muted); margin-top:4px; }

  /* Intel panel */
  .intel-section { border-bottom:1px solid var(--border); padding:16px; }
  .intel-title { font-size:10px; letter-spacing:2px; color:var(--muted); font-weight:700; text-transform:uppercase; margin-bottom:10px; }
  .intel-row { display:flex; justify-content:space-between; align-items:center; padding:6px 0; font-size:12px; border-bottom:1px solid rgba(30,39,64,0.5); }
  .intel-row:last-child { border:none; }
  .intel-key { color:var(--muted); }
  .intel-val { font-family:var(--font-mono); font-size:11px; }
  .intel-val.green { color:var(--green); }
  .intel-val.red { color:var(--red); }
  .intel-val.gold { color:var(--gold); }
  .intel-val.orange { color:var(--orange); }

  /* Log */
  .log-line { display:flex; gap:8px; padding:4px 0; border-bottom:1px solid rgba(30,39,64,0.4); font-size:11px; font-family:var(--font-mono); }
  .log-time { color:var(--muted); flex-shrink:0; width:60px; }
  .log-msg { color:var(--text); opacity:.8; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .log-msg.ERROR { color:var(--red); opacity:1; }
  .log-msg.WARNING { color:var(--orange); opacity:1; }

  /* Geo alerts */
  .geo-alert { padding:10px 14px; border-radius:8px; margin-bottom:8px; border-left:3px solid var(--red); background:rgba(240,74,74,0.08); }
  .geo-alert.MEDIUM { border-color:var(--orange); background:rgba(240,140,42,0.08); }
  .geo-alert.LOW { border-color:var(--muted); background:var(--bg3); }
  .geo-time { font-size:10px; color:var(--muted); font-family:var(--font-mono); }
  .geo-text { font-size:12px; margin-top:2px; }

  /* Views */
  .view { display:none; }
  .view.active { display:block; }

  /* Misc */
  .divider { height:1px; background:var(--border); margin:16px 0; }
  .tag { padding:2px 7px; border-radius:4px; font-size:10px; font-weight:700; letter-spacing:.5px; }
  .tag-buy { background:rgba(34,212,122,0.2); color:var(--green); }
  .tag-sell { background:rgba(240,74,74,0.2); color:var(--red); }
  .tag-neutral { background:var(--bg3); color:var(--muted); }
  .empty { text-align:center; padding:40px; color:var(--muted); font-size:13px; }
  .empty-icon { font-size:32px; margin-bottom:8px; }

  /* Toast */
  .toast { position:fixed; bottom:24px; right:24px; padding:12px 20px; border-radius:10px;
           background:var(--bg2); border:1px solid var(--border); font-size:13px; z-index:999;
           transform:translateY(80px); opacity:0; transition:all .3s; pointer-events:none; }
  .toast.show { transform:translateY(0); opacity:1; }
  .toast.success { border-color:var(--green); color:var(--green); }
  .toast.error { border-color:var(--red); color:var(--red); }

  /* Scrollbar */
  ::-webkit-scrollbar { width:4px; }
  ::-webkit-scrollbar-track { background:transparent; }
  ::-webkit-scrollbar-thumb { background:var(--border); border-radius:2px; }
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="logo">
    <div class="logo-icon">⚡</div>
    <div>
      <div class="logo-text">ALERT BOT</div>
      <div class="logo-sub">GOLD · SILVER · XAUUSD</div>
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

<!-- LAYOUT -->
<div class="layout">

  <!-- SIDEBAR -->
  <div class="sidebar">
    <div class="nav-label">Navigation</div>
    <div class="nav-section">
      <div class="nav-item active" onclick="showView('overview')">
        <div class="nav-dot gold" id="dot-overview"></div> Overview
      </div>
      <div class="nav-item" onclick="showView('signals')">
        <div class="nav-dot green" id="dot-signals"></div> Signals
      </div>
      <div class="nav-item" onclick="showView('intel')">
        <div class="nav-dot orange" id="dot-intel"></div> Intelligence
      </div>
      <div class="nav-item" onclick="showView('settings')">
        <div class="nav-dot" id="dot-settings"></div> Settings
      </div>
      <div class="nav-item" onclick="showView('logs')">
        <div class="nav-dot" id="dot-logs"></div> Live Logs
      </div>
    </div>
    <div class="divider"></div>
    <div class="nav-label">Bot Control</div>
    <div class="nav-section">
      <div style="padding:0 4px;">
        <div class="controls" style="flex-direction:column;">
          <button class="btn primary" id="btnStart" onclick="startBot()">▶ Start Bot</button>
          <button class="btn danger" id="btnStop" onclick="stopBot()" style="display:none">⏹ Stop Bot</button>
        </div>
        <div style="margin-top:12px;">
          <div style="font-size:11px;color:var(--muted);margin-bottom:6px;letter-spacing:1px;">BIAS FILTER</div>
          <div class="controls">
            <button class="btn sm active" id="biasBoth" onclick="setBias('both')">↕ Both</button>
            <button class="btn sm" id="biasBuy" onclick="setBias('buy_only')">⬆ Buy</button>
            <button class="btn sm" id="biasSell" onclick="setBias('sell_only')">⬇ Sell</button>
          </div>
        </div>
        <div style="margin-top:12px;">
          <button class="btn sm" id="btnPause" onclick="togglePause()" style="width:100%">⏸ Pause Signals</button>
        </div>
      </div>
    </div>
    <div class="divider"></div>
    <div class="nav-label">Data Sources</div>
    <div class="nav-section">
      <div id="sourcesStatus" style="padding:0 4px;font-size:12px;color:var(--muted);">Loading...</div>
    </div>
  </div>

  <!-- MAIN -->
  <div class="main">

    <!-- OVERVIEW VIEW -->
    <div class="view active" id="view-overview">
      <div class="card-grid card-grid-4" style="margin-bottom:16px;">
        <div class="stat gold">
          <div class="stat-label">TODAY SIGNALS</div>
          <div class="stat-value" id="todaySignals">0</div>
          <div class="stat-sub">since midnight UTC</div>
        </div>
        <div class="stat blue">
          <div class="stat-label">TOTAL SIGNALS</div>
          <div class="stat-value" id="totalSignals">0</div>
          <div class="stat-sub">this session</div>
        </div>
        <div class="stat" id="dxyCard">
          <div class="stat-label">DXY BIAS</div>
          <div class="stat-value" id="dxyVal">—</div>
          <div class="stat-sub">USD direction</div>
        </div>
        <div class="stat" id="newsCard">
          <div class="stat-label">NEWS RISK</div>
          <div class="stat-value" id="newsVal">—</div>
          <div class="stat-sub">market news</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Trading Sessions</div>
        <div id="sessionsList">
          <div class="session-row"><div class="session-name">🇯🇵 Tokyo</div><div class="session-time">00:15 – 06:00 UTC</div><span class="badge badge-closed">CLOSED</span></div>
          <div class="session-row"><div class="session-name">🇨🇳 China</div><div class="session-time">01:45 – 07:00 UTC</div><span class="badge badge-closed">CLOSED</span></div>
          <div class="session-row"><div class="session-name">🇬🇧 London</div><div class="session-time">08:15 – 11:00 UTC</div><span class="badge badge-closed">CLOSED</span></div>
          <div class="session-row"><div class="session-name">🇺🇸 New York</div><div class="session-time">13:45 – 20:00 UTC</div><span class="badge badge-closed">CLOSED</span></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Recent Signals</div>
        <div id="recentSignals"><div class="empty"><div class="empty-icon">📡</div>Waiting for signals...</div></div>
      </div>
    </div>

    <!-- SIGNALS VIEW -->
    <div class="view" id="view-signals">
      <div class="card">
        <div class="card-title">All Signals This Session</div>
        <div id="allSignals"><div class="empty"><div class="empty-icon">📡</div>No signals yet. Bot fires when 2/4+ institutional indicators confirm.</div></div>
      </div>
    </div>

    <!-- INTELLIGENCE VIEW -->
    <div class="view" id="view-intel">
      <div class="card-grid card-grid-2">
        <div class="card">
          <div class="card-title">WorldMonitor Assessment</div>
          <div id="worldmonPanel"><div class="empty">Loading intelligence data...</div></div>
        </div>
        <div class="card">
          <div class="card-title">Geopolitical Alerts</div>
          <div id="geoAlertsList"><div class="empty"><div class="empty-icon">🌍</div>Monitoring for geopolitical events...</div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Data Source Status</div>
        <div class="card-grid card-grid-4" id="sourceCards">
          <div class="stat"><div class="stat-label">ACLED</div><div class="stat-value" style="font-size:14px" id="src-acled">—</div></div>
          <div class="stat"><div class="stat-label">GDELT</div><div class="stat-value" style="font-size:14px" id="src-gdelt">—</div></div>
          <div class="stat"><div class="stat-label">BIS/FRED</div><div class="stat-value" style="font-size:14px" id="src-bis">—</div></div>
          <div class="stat"><div class="stat-label">USGS</div><div class="stat-value" style="font-size:14px" id="src-usgs">—</div></div>
        </div>
      </div>
    </div>

    <!-- SETTINGS VIEW -->
    <div class="view" id="view-settings">
      <div class="card-grid card-grid-2">
        <div class="card">
          <div class="card-title">Telegram</div>
          <div class="form-group">
            <label class="form-label">Bot Token</label>
            <input class="form-input" id="cfgToken" type="password" placeholder="From @BotFather">
          </div>
          <div class="form-group">
            <label class="form-label">Chat ID</label>
            <input class="form-input" id="cfgChat" placeholder="From @userinfobot">
          </div>
        </div>
        <div class="card">
          <div class="card-title">Risk & Capital</div>
          <div class="form-group">
            <label class="form-label">Starting Capital (EUR)</label>
            <input class="form-input" id="cfgCapital" type="number" value="350">
          </div>
          <div class="form-group">
            <label class="form-label">Risk Per Trade (%)</label>
            <input class="form-input" id="cfgRisk" type="number" value="5" step="0.5">
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">ACLED Intelligence (Free — register at acleddata.com)</div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">ACLED API Key</label>
            <input class="form-input" id="cfgAcledKey" type="password" placeholder="Paste key from acleddata.com">
            <div class="form-hint">Register free → acleddata.com/register</div>
          </div>
          <div class="form-group">
            <label class="form-label">Your Email (same as ACLED registration)</label>
            <input class="form-input" id="cfgAcledEmail" placeholder="you@gmail.com">
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Gmail (optional — TradingView alerts)</div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Gmail Address</label>
            <input class="form-input" id="cfgGmail" placeholder="you@gmail.com">
          </div>
          <div class="form-group">
            <label class="form-label">App Password</label>
            <input class="form-input" id="cfgGmailPass" type="password" placeholder="16-char app password">
          </div>
        </div>
      </div>
      <div style="display:flex;gap:10px;">
        <button class="btn primary" onclick="saveSettings()">💾 Save & Restart Bot</button>
        <button class="btn" onclick="loadSettings()">↺ Reload</button>
        <button class="btn success" onclick="testTelegram()">📱 Test Telegram</button>
      </div>
    </div>

    <!-- LOGS VIEW -->
    <div class="view" id="view-logs">
      <div class="card">
        <div class="card-title" style="display:flex;justify-content:space-between;">
          <span>Live Bot Logs</span>
          <button class="btn sm" onclick="clearLogs()">Clear</button>
        </div>
        <div id="logContainer" style="max-height:600px;overflow-y:auto;"></div>
      </div>
    </div>

  </div><!-- /main -->

  <!-- RIGHT PANEL -->
  <div class="panel-right">
    <div class="intel-section">
      <div class="intel-title">Live Prices</div>
      <div class="intel-row"><span class="intel-key">XAUUSD (Gold)</span><span class="intel-val gold" id="priceGold">—</span></div>
      <div class="intel-row"><span class="intel-key">XAGUSD (Silver)</span><span class="intel-val gold" id="priceSilver">—</span></div>
      <div class="intel-row"><span class="intel-key">DXY</span><span class="intel-val" id="priceDXY">—</span></div>
    </div>
    <div class="intel-section">
      <div class="intel-title">Bot State</div>
      <div class="intel-row"><span class="intel-key">Status</span><span class="intel-val" id="stateStatus">Stopped</span></div>
      <div class="intel-row"><span class="intel-key">Bias</span><span class="intel-val gold" id="stateBias">Both</span></div>
      <div class="intel-row"><span class="intel-key">Paused</span><span class="intel-val" id="statePaused">No</span></div>
      <div class="intel-row"><span class="intel-key">Uptime</span><span class="intel-val" id="stateUptime">—</span></div>
    </div>
    <div class="intel-section">
      <div class="intel-title">Intelligence</div>
      <div class="intel-row"><span class="intel-key">WorldMon Level</span><span class="intel-val" id="wmLevel">—</span></div>
      <div class="intel-row"><span class="intel-key">Gold Direction</span><span class="intel-val" id="wmGold">—</span></div>
      <div class="intel-row"><span class="intel-key">GDELT Tone</span><span class="intel-val" id="wmTone">—</span></div>
      <div class="intel-row"><span class="intel-key">Fed Rate</span><span class="intel-val" id="wmFed">—</span></div>
    </div>
    <div class="intel-section">
      <div class="intel-title">Errors</div>
      <div id="errorList" style="font-size:11px;color:var(--red);font-family:var(--font-mono);">None</div>
    </div>
    <div class="intel-section">
      <div class="intel-title">Quick Commands</div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <button class="btn sm" onclick="setBias('buy_only')">⬆ BUY Only Mode</button>
        <button class="btn sm" onclick="setBias('sell_only')">⬇ SELL Only Mode</button>
        <button class="btn sm" onclick="setBias('both')">↕ Both Directions</button>
        <button class="btn sm danger" onclick="togglePause()">⏸ Pause / Resume</button>
      </div>
      <div style="margin-top:12px;font-size:11px;color:var(--muted);letter-spacing:1px;margin-bottom:6px;">ACCOUNT</div>
      <div class="intel-row"><span class="intel-key">Capital</span><span class="intel-val gold">€350</span></div>
      <div class="intel-row"><span class="intel-key">Risk/trade</span><span class="intel-val orange">5% = €17.50</span></div>
      <div class="intel-row"><span class="intel-key">Trades left</span><span class="intel-val" id="tradesLeft">~20</span></div>
      <div style="margin-top:8px;font-size:11px;color:var(--muted);padding:8px;background:rgba(240,74,74,0.08);border-radius:6px;border:1px solid rgba(240,74,74,0.2);">
        <b style="color:var(--orange)">⭐⭐⭐ STRONG</b> — always take<br>
        <b style="color:var(--gold)">⭐⭐ STANDARD</b> — take if trend agrees<br>
        <b style="color:var(--muted)">⭐ RELAXED</b> — be selective
      </div>
    </div>
  </div>

</div><!-- /layout -->

<div class="toast" id="toast"></div>

<script>
let currentView = 'overview';
let botRunning  = false;
let biasState   = 'both';
let pauseState  = false;
let prices      = {};

function showView(v) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.getElementById('view-' + v).classList.add('active');
  event.currentTarget.classList.add('active');
  currentView = v;
}

function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3000);
}

// Clock
function updateClock() {
  const now = new Date();
  const h = String(now.getUTCHours()).padStart(2,'0');
  const m = String(now.getUTCMinutes()).padStart(2,'0');
  const s = String(now.getUTCSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent = h+':'+m+':'+s+' UTC';
}
setInterval(updateClock, 1000); updateClock();

// Sessions
const SESSION_DEF = [
  {name:'🇯🇵 Tokyo',    open:[0,0],  close:[9,0],  blackout:[0,15]},
  {name:'🇨🇳 China',    open:[1,30], close:[8,0],  blackout:[1,45]},
  {name:'🇬🇧 London',   open:[8,0],  close:[17,0], blackout:[8,15]},
  {name:'🇺🇸 New York', open:[13,15],close:[22,0], blackout:[13,30]},
];
function updateSessions() {
  const now = new Date();
  const h = now.getUTCHours(), m = now.getUTCMinutes();
  const cur = h * 60 + m;
  const html = SESSION_DEF.map(s => {
    const open  = s.open[0]*60+s.open[1];
    const close = s.close[0]*60+s.close[1];
    const black = s.blackout[0]*60+s.blackout[1];
    const times = `${String(s.open[0]).padStart(2,'0')}:${String(s.open[1]).padStart(2,'0')} – ${String(s.close[0]).padStart(2,'0')}:${String(s.close[1]).padStart(2,'0')} UTC`;
    if (cur >= open && cur < black) return `<div class="session-row blackout"><div class="session-name">${s.name}</div><div class="session-time">${times}</div><span class="badge badge-blackout">BLACKOUT</span></div>`;
    if (cur >= black && cur < close) return `<div class="session-row active"><div class="session-name">${s.name}</div><div class="session-time">${times}</div><span class="badge badge-active">ACTIVE</span></div>`;
    return `<div class="session-row"><div class="session-name">${s.name}</div><div class="session-time">${times}</div><span class="badge badge-closed">CLOSED</span></div>`;
  }).join('');
  document.getElementById('sessionsList').innerHTML = html;
}
setInterval(updateSessions, 10000); updateSessions();

// API calls
async function api(endpoint, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(endpoint, opts);
  return r.json();
}

async function startBot() {
  document.getElementById('statusText').textContent = 'STARTING...';
  document.getElementById('btnStart').style.display = 'none';
  document.getElementById('btnStop').style.display = '';
  const r = await api('/api/start', 'POST');
  if (r.ok) { toast('Bot started!'); } else { toast(r.error || 'Failed', 'error'); }
  setTimeout(pollState, 600);
}
async function stopBot() {
  document.getElementById('statusText').textContent = 'STOPPING...';
  document.getElementById('btnStop').style.display = 'none';
  document.getElementById('btnStart').style.display = '';
  const r = await api('/api/stop', 'POST');
  if (r.ok) toast('Bot stopped');
  setTimeout(pollState, 600);
}
async function setBias(b) {
  const r = await api('/api/bias', 'POST', {bias: b});
  if (r.ok) toast('Bias: ' + b.replace('_',' ').toUpperCase());
}
async function togglePause() {
  const r = await api('/api/pause', 'POST');
  if (r.ok) toast(r.paused ? 'Bot paused' : 'Bot resumed');
}
async function testTelegram() {
  const r = await api('/api/test_telegram', 'POST');
  toast(r.ok ? 'Telegram test sent!' : 'Failed: '+r.error, r.ok ? 'success' : 'error');
}
async function saveSettings() {
  const body = {
    telegram_token: document.getElementById('cfgToken').value,
    telegram_chat:  document.getElementById('cfgChat').value,
    capital:        parseFloat(document.getElementById('cfgCapital').value),
    risk_pct:       parseFloat(document.getElementById('cfgRisk').value) / 100,
    acled_key:      document.getElementById('cfgAcledKey').value,
    acled_email:    document.getElementById('cfgAcledEmail').value,
    gmail:          document.getElementById('cfgGmail').value,
    gmail_pass:     document.getElementById('cfgGmailPass').value,
  };
  const r = await api('/api/settings', 'POST', body);
  toast(r.ok ? 'Settings saved! Bot restarting...' : 'Error: '+r.error, r.ok?'success':'error');
}
async function loadSettings() {
  const r = await api('/api/settings');
  if (r.telegram_token) document.getElementById('cfgToken').value = r.telegram_token;
  if (r.telegram_chat)  document.getElementById('cfgChat').value  = r.telegram_chat;
  if (r.capital)        document.getElementById('cfgCapital').value = r.capital;
  if (r.acled_key)      document.getElementById('cfgAcledKey').value = r.acled_key;
  if (r.acled_email)    document.getElementById('cfgAcledEmail').value = r.acled_email;
  toast('Settings loaded');
}
function clearLogs() { document.getElementById('logContainer').innerHTML = ''; }

// State polling
async function pollState() {
  try {
    const r = await api('/api/state');

    // Status pill
    botRunning = r.bot_running;
    const pill = document.getElementById('statusPill');
    pill.className = 'status-pill ' + (r.bot_running ? 'running' : 'stopped');
    document.getElementById('statusText').textContent = r.paused ? 'PAUSED' : r.bot_running ? 'RUNNING' : 'STOPPED';
    document.getElementById('btnStart').style.display = r.bot_running ? 'none' : '';
    document.getElementById('btnStop').style.display  = r.bot_running ? '' : 'none';

    // Stats
    document.getElementById('todaySignals').textContent  = r.stats?.today_signals  || 0;
    document.getElementById('totalSignals').textContent  = r.stats?.total_signals  || 0;

    // DXY
    const dxy = r.dxy || 'neutral';
    const dxyEl = document.getElementById('dxyVal');
    dxyEl.textContent = dxy.toUpperCase();
    dxyEl.style.color = dxy==='bullish'?'var(--red)':dxy==='bearish'?'var(--green)':'var(--muted)';

    // News
    const nv = r.news_status?.risk_level || 'CLEAR';
    const nvEl = document.getElementById('newsVal');
    nvEl.textContent = nv;
    nvEl.style.color = nv==='HIGH'?'var(--red)':nv==='MEDIUM'?'var(--orange)':'var(--green)';

    // Right panel
    document.getElementById('stateStatus').textContent = r.bot_running ? (r.paused?'PAUSED':'RUNNING') : 'STOPPED';
    document.getElementById('stateBias').textContent   = r.bias?.toUpperCase().replace('_',' ') || 'BOTH';
    document.getElementById('statePaused').textContent = r.paused ? 'YES' : 'No';
    if (r.stats?.uptime_start) {
      const up = Math.floor((Date.now()/1000) - r.stats.uptime_start);
      const h = Math.floor(up/3600), m = Math.floor((up%3600)/60);
      document.getElementById('stateUptime').textContent = h+'h '+m+'m';
    }

    // Bias buttons
    biasState = r.bias || 'both';
    ['Both','Buy','Sell'].forEach(b => document.getElementById('bias'+b).classList.remove('active'));
    if (biasState==='buy_only') document.getElementById('biasBuy').classList.add('active');
    else if (biasState==='sell_only') document.getElementById('biasSell').classList.add('active');
    else document.getElementById('biasBoth').classList.add('active');

    // Pause button
    document.getElementById('btnPause').textContent = r.paused ? '▶ Resume Signals' : '⏸ Pause Signals';

    // Signals
    if (r.signals?.length) {
      const html = r.signals.slice().reverse().slice(0,5).map(renderSignal).join('');
      document.getElementById('recentSignals').innerHTML = html;
      document.getElementById('allSignals').innerHTML = r.signals.slice().reverse().map(renderSignal).join('');
    }

    // WorldMon
    const wm = r.worldmon || {};
    document.getElementById('wmLevel').textContent = wm.overall_level || '—';
    document.getElementById('wmGold').textContent  = wm.gold_direction || '—';
    const gdelt = wm.sources?.gdelt || {};
    const bis   = wm.sources?.bis   || {};
    document.getElementById('wmTone').textContent = gdelt.avg_tone !== undefined ? gdelt.avg_tone.toFixed(1) : '—';
    document.getElementById('wmFed').textContent  = bis.fed_rate  ? bis.fed_rate + '%' : '—';

    // Source cards
    const ss = r.sources_status || {};
    ['acled','gdelt','bis','usgs'].forEach(s => {
      const el = document.getElementById('src-'+s);
      if (el) { el.textContent = ss[s] || '—'; el.style.color = ss[s]==='OK'?'var(--green)':ss[s]==='FAIL'?'var(--red)':'var(--muted)'; }
    });

    // Sidebar sources
    const srcHtml = ['ACLED','GDELT','BIS','USGS'].map(s => {
      const ok = (ss[s.toLowerCase()] === 'OK');
      return `<div style="display:flex;align-items:center;gap:6px;padding:4px 8px;font-size:12px;">
        <div class="nav-dot ${ok?'green':'red'}"></div>${s}
      </div>`;
    }).join('');
    document.getElementById('sourcesStatus').innerHTML = srcHtml;

    // Errors
    const errs = r.errors || [];
    document.getElementById('errorList').innerHTML = errs.length
      ? errs.map(e => `<div style="margin-bottom:4px;">${e.time} ${e.msg}</div>`).join('')
      : '<span style="color:var(--green)">None</span>';

    // Geo alerts
    const geo = r.geo_alerts || [];
    document.getElementById('geoAlertsList').innerHTML = geo.length
      ? geo.slice().reverse().map(a => `<div class="geo-alert ${a.level||''}"><div class="geo-time">${a.time||''}</div><div class="geo-text">${a.text||''}</div></div>`).join('')
      : '<div class="empty"><div class="empty-icon">🌍</div>Monitoring...</div>';

    // WorldMon panel
    document.getElementById('worldmonPanel').innerHTML = wm.overall_level
      ? `<div class="intel-row"><span class="intel-key">Level</span><span class="intel-val ${wm.overall_level==='CLEAR'?'green':wm.overall_level==='HIGH'?'orange':'red'}">${wm.overall_level}</span></div>
         <div class="intel-row"><span class="intel-key">Gold Direction</span><span class="intel-val gold">${wm.gold_direction||'—'}</span></div>
         <div class="intel-row"><span class="intel-key">Buy Signals</span><span class="intel-val">${wm.buy_signals||0}/4 sources</span></div>
         <div class="intel-row"><span class="intel-key">GDELT Tone</span><span class="intel-val">${gdelt.avg_tone?.toFixed(1)||'—'}</span></div>
         <div class="intel-row"><span class="intel-key">GDELT Reason</span><span class="intel-val" style="font-size:10px;max-width:160px;text-align:right;">${gdelt.reason||'—'}</span></div>
         <div class="intel-row"><span class="intel-key">Fed Rate</span><span class="intel-val">${bis.fed_rate||'—'}%</span></div>
         <div class="intel-row"><span class="intel-key">ECB Rate</span><span class="intel-val">${bis.ecb_rate||'—'}%</span></div>
         <div class="intel-row"><span class="intel-key">Updated</span><span class="intel-val" style="font-size:10px;">${wm.timestamp?wm.timestamp.slice(11,16)+' UTC':'—'}</span></div>`
      : '<div class="empty">Start bot to load intelligence</div>';

    // Logs
    if (r.log_lines?.length && currentView==='logs') {
      const logHtml = r.log_lines.slice(-50).reverse().map(l =>
        `<div class="log-line"><span class="log-time">${l.time}</span><span class="log-msg ${l.level}">${l.msg}</span></div>`
      ).join('');
      document.getElementById('logContainer').innerHTML = logHtml;
    }

  } catch(e) { console.error('Poll error:', e); }
}

function renderSignal(s) {
  const isBuy = s.direction === 'bullish';
  const inst  = s.inst_result || {};
  const chips = [
    {label:'Sweep',  ok: inst.sweep?.detected},
    {label:'Flow',   ok: inst.order_flow?.confirmed},
    {label:'VP',     ok: inst.volume_profile?.confirmed},
    {label:'VWAP',   ok: inst.vwap?.confirmed},
  ].map(c => `<span class="inst-chip ${c.ok?'inst-ok':'inst-fail'}">${c.label}</span>`).join('');
  return `<div class="signal-card ${isBuy?'buy':'sell'}">
    <div class="signal-top">
      <div class="signal-sym">${s.symbol?.replace('XAU','Gold ').replace('XAG','Silver ')}</div>
      <div style="display:flex;gap:6px;align-items:center;">
        <span class="signal-score">${s.signal_score||0}/100</span>
        <span class="signal-action ${isBuy?'buy':'sell'}">${isBuy?'BUY':'SELL'}</span>
      </div>
    </div>
    <div class="signal-row"><span>Entry</span><span>${s.entry_price||'—'}</span></div>
    <div class="signal-row"><span>SL / TP</span><span>${s.order?.stop_loss||'—'} / ${s.order?.take_profit||'—'}</span></div>
    <div class="signal-row"><span>Session</span><span>${s.active_sessions?.map(ss=>ss.name).join('+')||'—'}</span></div>
    <div class="signal-row"><span>Time</span><span>${s.timestamp||'—'}</span></div>
    <div class="signal-inst">${chips}</div>
  </div>`;
}

// Poll every 4 seconds
setInterval(pollState, 1500);
pollState();
loadSettings();
</script>
</body>
</html>"""

MOBILE_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">\n<meta name="apple-mobile-web-app-capable" content="yes">\n<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n<meta name="apple-mobile-web-app-title" content="Alert Bot">\n<title>Alert Bot</title>\n<style>\n:root{--bg:#0a0a0f;--card:#12121a;--border:#1e1e2e;--gold:#f5c842;--silver:#b0bec5;--green:#00e676;--red:#ff1744;--orange:#ff9100;--blue:#448aff;--text:#e8e8f0;--muted:#5a5a7a;--r:16px;}\n*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;}\nbody{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,\'SF Pro Display\',sans-serif;min-height:100vh;padding-bottom:90px;overflow-x:hidden;}\n.mono{font-family:\'Courier New\',monospace;}\n.header{background:#0d0d1a;border-bottom:1px solid var(--border);padding:52px 20px 16px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;}\n.header-icon{width:40px;height:40px;background:linear-gradient(135deg,var(--gold),#e6a800);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 15px rgba(245,200,66,0.3);}\n.header-left{display:flex;align-items:center;gap:12px;}\n.header-title{font-family:\'Courier New\',monospace;font-size:15px;font-weight:700;letter-spacing:1px;}\n.header-sub{font-size:11px;color:var(--muted);margin-top:2px;}\n.status-pill{padding:6px 14px;border-radius:20px;font-family:\'Courier New\',monospace;font-size:11px;font-weight:700;letter-spacing:1px;display:flex;align-items:center;gap:6px;}\n.status-pill::before{content:\'\';width:7px;height:7px;border-radius:50%;}\n.status-pill.running{background:rgba(0,230,118,0.12);color:var(--green);border:1px solid rgba(0,230,118,0.3);}\n.status-pill.running::before{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 1.5s infinite;}\n.status-pill.stopped{background:rgba(255,23,68,0.12);color:var(--red);border:1px solid rgba(255,23,68,0.3);}\n.status-pill.stopped::before{background:var(--red);}\n.status-pill.paused{background:rgba(255,145,0,0.12);color:var(--orange);border:1px solid rgba(255,145,0,0.3);}\n.status-pill.paused::before{background:var(--orange);}\n@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}\n.scroll{padding:16px;display:flex;flex-direction:column;gap:12px;}\n.prices-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;}\n.price-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px;position:relative;overflow:hidden;}\n.price-card::before{content:\'\';position:absolute;top:0;left:0;right:0;height:2px;}\n.price-card.gold::before{background:linear-gradient(90deg,var(--gold),transparent);}\n.price-card.silver::before{background:linear-gradient(90deg,var(--silver),transparent);}\n.price-card.dxy::before{background:linear-gradient(90deg,var(--blue),transparent);}\n.price-label{font-size:10px;color:var(--muted);font-family:\'Courier New\',monospace;letter-spacing:1px;margin-bottom:8px;}\n.price-value{font-family:\'Courier New\',monospace;font-size:20px;font-weight:700;}\n.price-value.gold{color:var(--gold);}\n.price-value.silver{color:var(--silver);}\n.price-value.dxy{color:var(--blue);font-size:17px;}\n.price-updated{font-size:9px;color:var(--muted);margin-top:4px;}\n.section-header{font-family:\'Courier New\',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;padding:0 2px;display:flex;align-items:center;justify-content:space-between;}\n.section-count{background:var(--border);color:var(--text);border-radius:10px;padding:2px 8px;font-size:10px;}\n.signal-card{background:var(--card);border-radius:var(--r);overflow:hidden;border:1px solid var(--border);animation:slideIn 0.3s ease;}\n@keyframes slideIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}\n.signal-header{padding:14px 16px;display:flex;align-items:center;justify-content:space-between;}\n.signal-card.buy .signal-header{background:rgba(0,230,118,0.07);border-bottom:1px solid rgba(0,230,118,0.15);}\n.signal-card.sell .signal-header{background:rgba(255,23,68,0.07);border-bottom:1px solid rgba(255,23,68,0.15);}\n.signal-sym{font-family:\'Courier New\',monospace;font-size:14px;font-weight:700;}\n.signal-badge{padding:4px 12px;border-radius:20px;font-family:\'Courier New\',monospace;font-size:11px;font-weight:700;letter-spacing:1px;}\n.signal-card.buy .signal-badge{background:rgba(0,230,118,0.15);color:var(--green);border:1px solid rgba(0,230,118,0.3);}\n.signal-card.sell .signal-badge{background:rgba(255,23,68,0.15);color:var(--red);border:1px solid rgba(255,23,68,0.3);}\n.signal-body{padding:12px 16px;display:flex;flex-direction:column;gap:8px;}\n.signal-row{display:flex;justify-content:space-between;align-items:center;}\n.signal-key{font-size:12px;color:var(--muted);}\n.signal-val{font-family:\'Courier New\',monospace;font-size:12px;font-weight:700;}\n.signal-score{display:flex;align-items:center;gap:8px;padding-top:8px;border-top:1px solid var(--border);}\n.score-bar{flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden;}\n.score-fill{height:100%;border-radius:2px;transition:width 0.5s;}\n.score-fill.high{background:var(--green);}\n.score-fill.mid{background:var(--orange);}\n.score-fill.low{background:var(--red);}\n.score-num{font-family:\'Courier New\',monospace;font-size:11px;color:var(--muted);}\n.signal-time{font-size:10px;color:var(--muted);padding-top:2px;}\n.no-signals{text-align:center;padding:40px 20px;color:var(--muted);font-size:13px;background:var(--card);border-radius:var(--r);border:1px dashed var(--border);}\n.no-signals-icon{font-size:32px;margin-bottom:10px;}\n.control-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px;}\n.control-title{font-family:\'Courier New\',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);margin-bottom:14px;}\n.btn-row{display:flex;gap:8px;}\n.btn{flex:1;padding:14px 8px;border-radius:12px;border:none;font-family:\'Courier New\',monospace;font-size:12px;font-weight:700;letter-spacing:0.5px;cursor:pointer;transition:all 0.15s;}\n.btn:active{transform:scale(0.96);}\n.btn-start{background:linear-gradient(135deg,#f5c842,#e6a800);color:#000;}\n.btn-stop{background:rgba(255,23,68,0.15);color:var(--red);border:1px solid rgba(255,23,68,0.3);}\n.btn-pause{background:rgba(255,145,0,0.12);color:var(--orange);border:1px solid rgba(255,145,0,0.3);}\n.bias-row{display:flex;gap:8px;margin-top:10px;}\n.bias-btn{flex:1;padding:10px 8px;border-radius:10px;border:1px solid var(--border);background:transparent;color:var(--muted);font-family:\'Courier New\',monospace;font-size:10px;font-weight:700;letter-spacing:1px;cursor:pointer;transition:all 0.2s;}\n.bias-btn:active{transform:scale(0.96);}\n.bias-btn.active-both{background:rgba(68,138,255,0.15);color:var(--blue);border-color:rgba(68,138,255,0.4);}\n.bias-btn.active-buy{background:rgba(0,230,118,0.15);color:var(--green);border-color:rgba(0,230,118,0.4);}\n.bias-btn.active-sell{background:rgba(255,23,68,0.15);color:var(--red);border-color:rgba(255,23,68,0.4);}\n.stat-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);}\n.stat-row:last-child{border-bottom:none;}\n.stat-key{font-size:12px;color:var(--muted);}\n.stat-val{font-family:\'Courier New\',monospace;font-size:12px;font-weight:700;}\n.trade-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px;}\n.trade-inputs{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px;}\n.trade-input-group{display:flex;flex-direction:column;gap:4px;}\n.trade-label{font-size:10px;color:var(--muted);letter-spacing:1px;}\n.trade-input{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 12px;color:var(--text);font-family:\'Courier New\',monospace;font-size:13px;width:100%;outline:none;}\n.trade-input:focus{border-color:var(--gold);}\n.trade-select{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 12px;color:var(--text);font-family:\'Courier New\',monospace;font-size:13px;width:100%;outline:none;}\n.add-trade-btn{width:100%;margin-top:10px;padding:13px;border-radius:10px;border:1px solid rgba(245,200,66,0.3);background:rgba(245,200,66,0.08);color:var(--gold);font-family:\'Courier New\',monospace;font-size:12px;font-weight:700;letter-spacing:1px;cursor:pointer;transition:all 0.15s;}\n.add-trade-btn:active{transform:scale(0.98);}\n.open-trade{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:12px 14px;margin-top:10px;display:flex;align-items:center;justify-content:space-between;}\n.open-trade-left{display:flex;flex-direction:column;gap:3px;}\n.open-trade-sym{font-family:\'Courier New\',monospace;font-size:13px;font-weight:700;}\n.open-trade-detail{font-size:11px;color:var(--muted);}\n.open-trade-right{display:flex;flex-direction:column;align-items:flex-end;gap:4px;}\n.open-trade-pl{font-family:\'Courier New\',monospace;font-size:15px;font-weight:700;}\n.open-trade-pl.pos{color:var(--green);}\n.open-trade-pl.neg{color:var(--red);}\n.close-trade-btn{background:rgba(255,23,68,0.12);border:1px solid rgba(255,23,68,0.25);color:var(--red);border-radius:6px;padding:3px 8px;font-size:10px;font-family:\'Courier New\',monospace;cursor:pointer;}\n.total-pl{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;background:var(--bg);border-radius:12px;margin-top:8px;border:1px solid var(--border);}\n.total-pl-label{font-size:11px;color:var(--muted);font-family:\'Courier New\',monospace;letter-spacing:1px;}\n.total-pl-val{font-family:\'Courier New\',monospace;font-size:18px;font-weight:700;}\n.total-pl-val.pos{color:var(--green);}\n.total-pl-val.neg{color:var(--red);}\n.toast{position:fixed;bottom:100px;left:50%;transform:translateX(-50%) translateY(20px);background:#1e1e2e;border:1px solid var(--border);color:var(--text);padding:10px 20px;border-radius:20px;font-size:12px;opacity:0;transition:all 0.3s;z-index:200;white-space:nowrap;}\n.toast.show{opacity:1;transform:translateX(-50%) translateY(0);}\n.bottom-nav{position:fixed;bottom:0;left:0;right:0;background:rgba(10,10,15,0.97);border-top:1px solid var(--border);display:flex;padding:8px 0 24px;z-index:100;}\n.nav-item{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px;cursor:pointer;border:none;background:none;color:var(--muted);transition:color 0.2s;}\n.nav-item.active{color:var(--gold);}\n.nav-icon{font-size:22px;}\n.nav-label{font-size:9px;font-family:\'Courier New\',monospace;letter-spacing:0.5px;}\n.page{display:none;}\n.page.active{display:block;}\n.refresh-row{display:flex;justify-content:space-between;align-items:center;font-size:10px;color:var(--muted);padding:0 2px;font-family:\'Courier New\',monospace;}\n.refresh-dot{width:6px;height:6px;border-radius:50%;background:var(--green);display:inline-block;margin-right:5px;animation:pulse 2s infinite;}\n</style>\n</head>\n<body>\n<div class="header">\n  <div class="header-left">\n    <div class="header-icon">⚡</div>\n    <div>\n      <div class="header-title">ALERT BOT</div>\n      <div class="header-sub">Gold · Silver · <span id="hdrTime">--:--</span> Berlin</div>\n    </div>\n  </div>\n  <div class="status-pill stopped" id="statusPill"><span id="statusText">STOPPED</span></div>\n</div>\n<div class="toast" id="toast"></div>\n\n<div class="page active scroll" id="page-dash">\n  <div class="refresh-row">\n    <span><span class="refresh-dot"></span>LIVE PRICES</span>\n    <span id="priceTime">--:-- UTC</span>\n  </div>\n  <div class="prices-row">\n    <div class="price-card gold">\n      <div class="price-label">GOLD</div>\n      <div class="price-value gold" id="goldPrice">—</div>\n      <div class="price-updated">XAUUSD</div>\n    </div>\n    <div class="price-card silver">\n      <div class="price-label">SILVER</div>\n      <div class="price-value silver" id="silverPrice">—</div>\n      <div class="price-updated">XAGUSD</div>\n    </div>\n  </div>\n  <div class="prices-row">\n    <div class="price-card dxy" style="grid-column:1/-1">\n      <div class="price-label">US DOLLAR INDEX</div>\n      <div class="price-value dxy" id="dxyPrice">—</div>\n      <div class="price-updated">DXY · <span id="dxyBias">—</span></div>\n    </div>\n  </div>\n  <div class="section-header">\n    <span>SIGNALS TODAY</span>\n    <span class="section-count" id="sigCount">0</span>\n  </div>\n  <div id="signalsList">\n    <div class="no-signals"><div class="no-signals-icon">📡</div>No signals yet</div>\n  </div>\n</div>\n\n<div class="page scroll" id="page-ctrl">\n  <div class="control-card">\n    <div class="control-title">BOT CONTROL</div>\n    <div class="btn-row">\n      <button class="btn btn-start" id="btnStart" onclick="startBot()">▶ START</button>\n      <button class="btn btn-stop" id="btnStop" onclick="stopBot()" style="display:none">⏹ STOP</button>\n      <button class="btn btn-pause" id="btnPause" onclick="pauseBot()">⏸ PAUSE</button>\n    </div>\n    <div class="control-title" style="margin-top:16px">SIGNAL BIAS</div>\n    <div class="bias-row">\n      <button class="bias-btn active-both" id="bBoth" onclick="setBias(\'both\')">BOTH</button>\n      <button class="bias-btn" id="bBuy" onclick="setBias(\'buy_only\')">BUY</button>\n      <button class="bias-btn" id="bSell" onclick="setBias(\'sell_only\')">SELL</button>\n    </div>\n  </div>\n  <div class="control-card">\n    <div class="control-title">STATUS</div>\n    <div class="stat-row"><span class="stat-key">Bot</span><span class="stat-val" id="ctrlStatus">—</span></div>\n    <div class="stat-row"><span class="stat-key">Bias</span><span class="stat-val" id="ctrlBias">—</span></div>\n    <div class="stat-row"><span class="stat-key">Signals today</span><span class="stat-val" id="ctrlSigs">—</span></div>\n    <div class="stat-row"><span class="stat-key">Capital</span><span class="stat-val">EUR 350</span></div>\n    <div class="stat-row"><span class="stat-key">Risk/trade</span><span class="stat-val">EUR 17.50</span></div>\n    <div class="stat-row"><span class="stat-key">Session</span><span class="stat-val" id="ctrlSession">—</span></div>\n    <div class="stat-row"><span class="stat-key">DXY</span><span class="stat-val" id="ctrlDxy">—</span></div>\n  </div>\n</div>\n\n<div class="page scroll" id="page-trades">\n  <div class="trade-card">\n    <div class="control-title">ADD TRADE</div>\n    <div class="trade-inputs">\n      <div class="trade-input-group">\n        <div class="trade-label">SYMBOL</div>\n        <select class="trade-select" id="tSym">\n          <option value="XAUUSD">Gold</option>\n          <option value="XAGUSD">Silver</option>\n        </select>\n      </div>\n      <div class="trade-input-group">\n        <div class="trade-label">DIRECTION</div>\n        <select class="trade-select" id="tDir">\n          <option value="BUY">BUY</option>\n          <option value="SELL">SELL</option>\n        </select>\n      </div>\n      <div class="trade-input-group">\n        <div class="trade-label">ENTRY</div>\n        <input class="trade-input" id="tEntry" type="number" step="0.01" placeholder="0.00">\n      </div>\n      <div class="trade-input-group">\n        <div class="trade-label">UNITS</div>\n        <input class="trade-input" id="tUnits" type="number" step="0.1" placeholder="0.7">\n      </div>\n      <div class="trade-input-group">\n        <div class="trade-label">STOP LOSS</div>\n        <input class="trade-input" id="tSl" type="number" step="0.01" placeholder="0.00">\n      </div>\n      <div class="trade-input-group">\n        <div class="trade-label">TAKE PROFIT</div>\n        <input class="trade-input" id="tTp" type="number" step="0.01" placeholder="0.00">\n      </div>\n    </div>\n    <button class="add-trade-btn" onclick="addTrade()">+ ADD TRADE</button>\n  </div>\n  <div class="section-header" style="margin-top:4px">\n    <span>OPEN TRADES</span>\n    <span class="section-count" id="tradeCount">0</span>\n  </div>\n  <div id="openTrades">\n    <div class="no-signals" style="margin-top:8px"><div class="no-signals-icon">📊</div>No trades yet</div>\n  </div>\n  <div class="total-pl" id="totalPlRow" style="display:none">\n    <span class="total-pl-label">TOTAL P/L</span>\n    <span class="total-pl-val" id="totalPl">$0.00</span>\n  </div>\n</div>\n\n<div class="bottom-nav">\n  <button class="nav-item active" id="nav-dash" onclick="showPage(\'dash\')">\n    <span class="nav-icon">📊</span><span class="nav-label">SIGNALS</span>\n  </button>\n  <button class="nav-item" id="nav-ctrl" onclick="showPage(\'ctrl\')">\n    <span class="nav-icon">⚙️</span><span class="nav-label">CONTROL</span>\n  </button>\n  <button class="nav-item" id="nav-trades" onclick="showPage(\'trades\')">\n    <span class="nav-icon">💰</span><span class="nav-label">TRADES</span>\n  </button>\n</div>\n\n<script>\nvar trades = JSON.parse(localStorage.getItem(\'alertbot_trades\') || \'[]\');\nvar currentPrices = {};\n\nfunction showPage(id) {\n  document.querySelectorAll(\'.page\').forEach(function(p){p.classList.remove(\'active\');});\n  document.querySelectorAll(\'.nav-item\').forEach(function(n){n.classList.remove(\'active\');});\n  document.getElementById(\'page-\'+id).classList.add(\'active\');\n  document.getElementById(\'nav-\'+id).classList.add(\'active\');\n}\n\nfunction toast(msg) {\n  var t = document.getElementById(\'toast\');\n  t.textContent = msg;\n  t.classList.add(\'show\');\n  setTimeout(function(){t.classList.remove(\'show\');}, 2500);\n}\n\nfunction updateClock() {\n  var now = new Date();\n  var mo = now.getUTCMonth()+1, d = now.getUTCDate();\n  var isSummer = (mo>3&&mo<10)||(mo===3&&d>=29)||(mo===10&&d<25);\n  var bH = (now.getUTCHours()+(isSummer?2:1))%24;\n  var bM = now.getUTCMinutes();\n  document.getElementById(\'hdrTime\').textContent = String(bH).padStart(2,\'0\')+\':\'+String(bM).padStart(2,\'0\');\n}\nsetInterval(updateClock, 1000);\nupdateClock();\n\nasync function api(url, method, body) {\n  try {\n    var opts = {method: method||\'GET\', headers: {\'Content-Type\':\'application/json\'}};\n    if (body) opts.body = JSON.stringify(body);\n    var r = await fetch(url, opts);\n    return await r.json();\n  } catch(e) { return {ok:false, error:e.message}; }\n}\n\nasync function fetchPrices() {\n  var r = await api(\'/api/prices\');\n  if (r && r.prices) {\n    currentPrices = r.prices;\n    if (r.prices.XAUUSD) document.getElementById(\'goldPrice\').textContent = r.prices.XAUUSD.toLocaleString(\'en-US\',{minimumFractionDigits:2,maximumFractionDigits:2});\n    if (r.prices.XAGUSD) document.getElementById(\'silverPrice\').textContent = r.prices.XAGUSD.toFixed(2);\n    if (r.prices.DXY) document.getElementById(\'dxyPrice\').textContent = r.prices.DXY.toFixed(2);\n    var now = new Date();\n    document.getElementById(\'priceTime\').textContent = String(now.getUTCHours()).padStart(2,\'0\')+\':\'+String(now.getUTCMinutes()).padStart(2,\'0\')+\' UTC\';\n    renderTrades();\n  }\n}\nsetInterval(fetchPrices, 15000);\nfetchPrices();\n\nasync function pollState() {\n  var r = await api(\'/api/state\');\n  if (!r || r.error) return;\n  var pill = document.getElementById(\'statusPill\');\n  var txt = document.getElementById(\'statusText\');\n  if (r.paused) { pill.className=\'status-pill paused\'; txt.textContent=\'PAUSED\'; }\n  else if (r.bot_running) { pill.className=\'status-pill running\'; txt.textContent=\'RUNNING\'; }\n  else { pill.className=\'status-pill stopped\'; txt.textContent=\'STOPPED\'; }\n  document.getElementById(\'btnStart\').style.display = r.bot_running?\'none\':\'\';\n  document.getElementById(\'btnStop\').style.display = r.bot_running?\'\':\'none\';\n  var bias = r.bias||\'both\';\n  [\'Both\',\'Buy\',\'Sell\'].forEach(function(b){\n    var el = document.getElementById(\'b\'+b);\n    el.className=\'bias-btn\';\n    if((b===\'Both\'&&bias===\'both\')||(b===\'Buy\'&&bias===\'buy_only\')||(b===\'Sell\'&&bias===\'sell_only\'))\n      el.className=\'bias-btn active-\'+b.toLowerCase();\n  });\n  var sigs = (r.signals||[]).slice().reverse();\n  document.getElementById(\'sigCount\').textContent = sigs.length;\n  var sl = document.getElementById(\'signalsList\');\n  if (sigs.length===0) {\n    sl.innerHTML = \'<div class="no-signals"><div class="no-signals-icon">📡</div>No signals yet</div>\';\n  } else {\n    sl.innerHTML = sigs.slice(0,10).map(function(s){\n      var isBuy = s.direction===\'BULLISH\';\n      var score = s.signal_score||0;\n      var sc = score>=72?\'high\':score>=50?\'mid\':\'low\';\n      var sym = (s.symbol||\'\').replace(\'XAU\',\'Gold \').replace(\'XAG\',\'Silver \');\n      var sl = (s.order&&s.order.stop_loss)||\'—\';\n      var tp = (s.order&&s.order.take_profit)||\'—\';\n      var rr = (s.order&&s.order.rr_ratio)||\'—\';\n      return \'<div class="signal-card \'+(isBuy?\'buy\':\'sell\')+\'">\'\n        +\'<div class="signal-header"><div class="signal-sym">\'+sym+\'</div>\'\n        +\'<span class="signal-badge">\'+(isBuy?\'BUY\':\'SELL\')+\'</span></div>\'\n        +\'<div class="signal-body">\'\n        +\'<div class="signal-row"><span class="signal-key">Entry</span><span class="signal-val">\'+(s.entry_price||\'—\')+\'</span></div>\'\n        +\'<div class="signal-row"><span class="signal-key">Stop Loss</span><span class="signal-val">\'+sl+\'</span></div>\'\n        +\'<div class="signal-row"><span class="signal-key">Take Profit</span><span class="signal-val">\'+tp+\'</span></div>\'\n        +\'<div class="signal-row"><span class="signal-key">R/R</span><span class="signal-val">1:\'+rr+\'</span></div>\'\n        +\'<div class="signal-score"><span>\'+(s.signal_tier||\'⭐\')+\'</span>\'\n        +\'<div class="score-bar"><div class="score-fill \'+sc+\'" style="width:\'+score+\'%"></div></div>\'\n        +\'<span class="score-num">\'+score+\'/100</span></div>\'\n        +\'<div class="signal-time">\'+(s.timestamp||\'\')+\'</div>\'\n        +\'</div></div>\';\n    }).join(\'\');\n  }\n  document.getElementById(\'ctrlStatus\').textContent = r.bot_running?(r.paused?\'PAUSED\':\'RUNNING\'):\'STOPPED\';\n  document.getElementById(\'ctrlBias\').textContent = (r.bias||\'both\').replace(\'_\',\' \').toUpperCase();\n  document.getElementById(\'ctrlSigs\').textContent = sigs.length;\n  document.getElementById(\'ctrlDxy\').textContent = (r.dxy||\'neutral\').toUpperCase();\n  document.getElementById(\'dxyBias\').textContent = (r.dxy||\'neutral\').toUpperCase();\n  var now = new Date();\n  var utcH = now.getUTCHours()+now.getUTCMinutes()/60;\n  var session = \'No active session\';\n  if (utcH>=0&&utcH<9) session=\'Tokyo\';\n  if (utcH>=1.5&&utcH<8) session=\'China\';\n  if (utcH>=8&&utcH<17) session=\'London\';\n  if (utcH>=13&&utcH<22) session=\'New York\';\n  if (utcH>=13&&utcH<17) session=\'London + New York\';\n  document.getElementById(\'ctrlSession\').textContent = session;\n}\nsetInterval(pollState, 3000);\npollState();\n\nasync function startBot() {\n  document.getElementById(\'btnStart\').style.display=\'none\';\n  document.getElementById(\'btnStop\').style.display=\'\';\n  document.getElementById(\'statusText\').textContent=\'STARTING...\';\n  var r = await api(\'/api/start\',\'POST\');\n  toast(r.ok?\'Bot started!\':\'Error: \'+(r.error||\'failed\'));\n  pollState();\n}\nasync function stopBot() {\n  document.getElementById(\'btnStop\').style.display=\'none\';\n  document.getElementById(\'btnStart\').style.display=\'\';\n  document.getElementById(\'statusText\').textContent=\'STOPPING...\';\n  await api(\'/api/stop\',\'POST\');\n  toast(\'Bot stopped\');\n  pollState();\n}\nasync function pauseBot() {\n  var r = await api(\'/api/pause\',\'POST\');\n  toast(r.paused?\'Signals paused\':\'Signals resumed\');\n  pollState();\n}\nasync function setBias(b) {\n  await api(\'/api/bias\',\'POST\',{bias:b});\n  toast(\'Bias: \'+b.replace(\'_\',\' \').toUpperCase());\n  pollState();\n}\n\nfunction saveTrades() { localStorage.setItem(\'alertbot_trades\', JSON.stringify(trades)); }\n\nfunction addTrade() {\n  var sym = document.getElementById(\'tSym\').value;\n  var dir = document.getElementById(\'tDir\').value;\n  var entry = parseFloat(document.getElementById(\'tEntry\').value);\n  var units = parseFloat(document.getElementById(\'tUnits\').value);\n  var sl = parseFloat(document.getElementById(\'tSl\').value)||0;\n  var tp = parseFloat(document.getElementById(\'tTp\').value)||0;\n  if (!entry||!units) { toast(\'Enter entry and units\'); return; }\n  trades.push({id:Date.now(),sym:sym,dir:dir,entry:entry,units:units,sl:sl,tp:tp});\n  saveTrades();\n  renderTrades();\n  document.getElementById(\'tEntry\').value=\'\';\n  document.getElementById(\'tUnits\').value=\'\';\n  document.getElementById(\'tSl\').value=\'\';\n  document.getElementById(\'tTp\').value=\'\';\n  toast(\'Trade added\');\n}\n\nfunction removeTrade(id) {\n  trades = trades.filter(function(t){return t.id!==id;});\n  saveTrades();\n  renderTrades();\n  toast(\'Trade removed\');\n}\n\nfunction renderTrades() {\n  var container = document.getElementById(\'openTrades\');\n  document.getElementById(\'tradeCount\').textContent = trades.length;\n  if (trades.length===0) {\n    container.innerHTML=\'<div class="no-signals" style="margin-top:8px"><div class="no-signals-icon">📊</div>No trades yet</div>\';\n    document.getElementById(\'totalPlRow\').style.display=\'none\';\n    return;\n  }\n  var totalPl = 0;\n  container.innerHTML = trades.map(function(t){\n    var price = currentPrices[t.sym]||t.entry;\n    var pl = t.dir===\'BUY\'?(price-t.entry)*t.units:(t.entry-price)*t.units;\n    totalPl += pl;\n    var plClass = pl>=0?\'pos\':\'neg\';\n    var plStr = (pl>=0?\'+\':\'\')+pl.toFixed(2);\n    var sym = t.sym.replace(\'XAU\',\'Gold\').replace(\'XAG\',\'Silver\');\n    return \'<div class="open-trade">\'\n      +\'<div class="open-trade-left">\'\n      +\'<div class="open-trade-sym">\'+sym+\' <span style="color:\'+(t.dir===\'BUY\'?\'var(--green)\':\'var(--red)\')+\';font-size:10px">\'+t.dir+\'</span></div>\'\n      +\'<div class="open-trade-detail">Entry: \'+t.entry+\' &middot; \'+t.units+\' units</div>\'\n      +\'<div class="open-trade-detail">SL: \'+(t.sl||\'—\')+\' &middot; TP: \'+(t.tp||\'—\')+\'</div>\'\n      +\'</div>\'\n      +\'<div class="open-trade-right">\'\n      +\'<div class="open-trade-pl \'+plClass+\'">$\'+plStr+\'</div>\'\n      +\'<div style="font-size:10px;color:var(--muted)">@ \'+price+\'</div>\'\n      +\'<button class="close-trade-btn" onclick="removeTrade(\'+t.id+\')">CLOSE</button>\'\n      +\'</div></div>\';\n  }).join(\'\');\n  document.getElementById(\'totalPlRow\').style.display=\'flex\';\n  var tpEl = document.getElementById(\'totalPl\');\n  tpEl.className = \'total-pl-val \'+(totalPl>=0?\'pos\':\'neg\');\n  tpEl.textContent = (totalPl>=0?\'+\':\'\')+\'$\'+totalPl.toFixed(2);\n}\n\nrenderTrades();\n</script>\n</body>\n</html>'

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
        'geo_alerts':    state['geo_alerts'][-20:],
        'worldmon':      state['worldmon'],
        'dxy':           state['dxy'],
        'news_status':   state['news_status'],
        'stats':         state['stats'],
        'log_lines':     state['log_lines'][-100:],
        'errors':        state['errors'],
        'sources_status': _get_sources_status(),
        'prices':         state.get('last_prices', {}),
    })

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify({
            'telegram_token': state['config'].get('telegram_token',''),
            'telegram_chat':  state['config'].get('telegram_chat',''),
            'capital':        state['config'].get('capital', 350),
            'acled_key':      state['config'].get('acled_key',''),
            'acled_email':    state['config'].get('acled_email',''),
        })
    data = request.json
    state['config'].update(data)
    _save_config(data)
    if state['bot_running']:
        _stop_bot()
        time.sleep(1)
        _start_bot()
    return jsonify({'ok': True})

@app.route('/api/start', methods=['POST'])
def api_start():
    if state['bot_running']:
        return jsonify({'ok': False, 'error': 'Already running'})
    ok = _start_bot()
    return jsonify({'ok': ok})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    _stop_bot()
    return jsonify({'ok': True})

@app.route('/api/bias', methods=['POST'])
def api_bias():
    bias = request.json.get('bias', 'both')
    state['bias'] = bias
    if bot_instance:
        bot_instance.bias.bias = bias
    return jsonify({'ok': True, 'bias': bias})

@app.route('/api/pause', methods=['POST'])
def api_pause():
    state['paused'] = not state['paused']
    if bot_instance:
        bot_instance.bias.paused = state['paused']
    return jsonify({'ok': True, 'paused': state['paused']})

@app.route('/api/test_telegram', methods=['POST'])
def api_test_telegram():
    try:
        cfg = _load_config()
        from telegram_alerter import TelegramAlerter
        t = TelegramAlerter(cfg['telegram']['bot_token'], cfg['telegram']['chat_id'])
        ok = t.test()
        return jsonify({'ok': ok})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── Bot management ─────────────────────────────────────────────────────────────

def _apply_config_to_file():
    """Write dashboard settings into alert_config.py so AlertBot picks them up."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alert_config.py')
    try:
        content = open(path).read()
        dc = state['config']
        import re
        if dc.get('telegram_token') and dc['telegram_token'] != 'YOUR_BOT_TOKEN_HERE':
            content = re.sub(r"'bot_token':\s*'[^']*'", f"'bot_token': '{dc['telegram_token']}'", content)
        if dc.get('telegram_chat') and dc['telegram_chat'] != 'YOUR_CHAT_ID_HERE':
            content = re.sub(r"'chat_id':\s*'[^']*'", f"'chat_id': '{dc['telegram_chat']}'", content)
        if dc.get('capital'):
            content = re.sub(r"'starting_capital':\s*[\d.]+", f"'starting_capital': {dc['capital']}", content)
        if dc.get('acled_key') and dc['acled_key'] != 'YOUR_ACLED_KEY_HERE':
            content = re.sub(r"'acled_key':\s*'[^']*'", f"'acled_key': '{dc['acled_key']}'", content)
        if dc.get('acled_email'):
            content = re.sub(r"'acled_email':\s*'[^']*'", f"'acled_email': '{dc['acled_email']}'", content)
        open(path, 'w').write(content)
    except Exception as e:
        log.warning(f"Could not update alert_config.py: {e}")


def _start_bot():
    global bot_thread, bot_instance
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        # Reload config into environment so alert_config.py picks it up
        _apply_config_to_file()

        from main import AlertBot
        bot_instance = AlertBot()

        # Patch _process_signal to capture signals for dashboard
        original_process = bot_instance._process_signal
        def patched_process(sig):
            sig['timestamp'] = datetime.now(timezone.utc).strftime('%H:%M UTC')
            state['signals'].append(sig)
            state['signals'] = state['signals'][-50:]
            state['stats']['total_signals'] += 1
            state['stats']['today_signals'] += 1
            original_process(sig)
        bot_instance._process_signal = patched_process

        state['bot_running'] = True
        state['stats']['uptime_start'] = time.time()
        state['bias']   = 'both'
        state['paused'] = False

        bot_thread = threading.Thread(target=_bot_loop, daemon=True)
        bot_thread.start()
        log.info("Bot started from dashboard")
        return True
    except Exception as e:
        import traceback
        log.error(f"Bot start failed: {e}")
        log.error(traceback.format_exc())
        state['errors'].append({'time': datetime.now(timezone.utc).strftime('%H:%M'), 'msg': str(e)[:120]})
        return False


def _bot_loop():
    global bot_instance
    try:
        # Send startup in background thread so it doesn't block
        import threading as _t
        _t.Thread(target=bot_instance.telegram.send_startup, args=(bot_instance.capital,), daemon=True).start()
        log.info("Bot startup message sending in background")
        while state['bot_running']:
            try:
                bot_instance._tick()
                # Cache latest prices from bot
                try:
                    from data_fetcher import fetch_bars
                    prices = {}
                    for sym in ['XAUUSD', 'XAGUSD']:
                        bars = fetch_bars(sym, '1m', 3)
                        if bars:
                            prices[sym] = round(bars[-1]['close'], 2)
                    if prices:
                        state['last_prices'] = prices
                except Exception:
                    pass
                # Sync worldmon state to dashboard
                if hasattr(bot_instance, 'worldmon'):
                    wm = bot_instance.worldmon.get_gold_bias()
                    if wm:
                        state['worldmon'] = wm
            except Exception as e:
                import traceback
                log.error(f"Tick error: {e}")
                log.error(traceback.format_exc())
            # Wait 3 minutes between scans
            for _ in range(36):
                if not state['bot_running']:
                    break
                time.sleep(5)
    except Exception as e:
        import traceback
        log.error(f"Bot loop crashed: {e}")
        log.error(traceback.format_exc())
    state['bot_running'] = False
    log.info("Bot loop ended")


def _stop_bot():
    global bot_instance
    state['bot_running'] = False
    if bot_instance:
        try:
            if hasattr(bot_instance, 'geo'):      bot_instance.geo.stop()
            if hasattr(bot_instance, 'bias'):     bot_instance.bias.stop()
            if hasattr(bot_instance, 'worldmon'): bot_instance.worldmon.stop()
        except Exception:
            pass
        bot_instance = None
    log.info("Bot stopped from dashboard")


def _get_sources_status():
    wm = state.get('worldmon', {})
    sources = wm.get('sources', {})
    return {
        'acled': 'OK' if sources.get('acled', {}).get('level') else 'N/A',
        'gdelt': 'OK' if sources.get('gdelt', {}).get('level') else 'N/A',
        'bis':   'OK' if sources.get('bis', {}).get('fed_rate') else 'N/A',
        'usgs':  'OK' if sources.get('usgs', {}).get('level') else 'N/A',
    }


def _load_config():
    # Load from alert_config.py
    import importlib.util, sys as _sys
    path = os.path.join(os.path.dirname(__file__), 'alert_config.py')
    spec = importlib.util.spec_from_file_location('alert_config', path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = dict(mod.ALERT_CONFIG)
    # Override with dashboard settings
    dc = state['config']
    if dc.get('telegram_token'): cfg['telegram']['bot_token'] = dc['telegram_token']
    if dc.get('telegram_chat'):  cfg['telegram']['chat_id']   = dc['telegram_chat']
    if dc.get('capital'):        cfg['risk']['starting_capital'] = dc['capital']
    if dc.get('acled_key'):
        cfg.setdefault('worldmonitor', {})['acled_key']   = dc['acled_key']
        cfg.setdefault('worldmonitor', {})['acled_email'] = dc.get('acled_email','')
    return cfg


def _save_config(data):
    """Persist non-sensitive settings to a JSON sidecar."""
    path = os.path.join(os.path.dirname(__file__), 'dashboard_config.json')
    existing = {}
    if os.path.exists(path):
        try: existing = json.load(open(path))
        except Exception: pass
    existing.update({k: v for k, v in data.items() if v})
    json.dump(existing, open(path, 'w'), indent=2)



@app.route('/api/prices')
def api_prices():
    """Return cached prices — updated by bot tick every 3min."""
    return jsonify({'ok': True, 'prices': state.get('last_prices', {})})

@app.route('/mobile')
def mobile():
    return render_template_string(MOBILE_HTML)


# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Load saved config on startup
    path = os.path.join(os.path.dirname(__file__), 'dashboard_config.json')
    if os.path.exists(path):
        try: state['config'] = json.load(open(path))
        except Exception: pass
    print("\n" + "="*50)
    print("  Alert Bot Dashboard")
    print("  Open: http://localhost:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
