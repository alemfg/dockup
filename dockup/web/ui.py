"""Embedded single-file Web UI for dockup."""

WEB_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>dockup</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --black:#040608;--surface:#080c10;--panel:#0d1117;--border:#1a2332;
  --border2:#243347;--accent:#00d4aa;--accent2:#0080ff;--accent3:#ff6b35;
  --green:#00e676;--red:#ff1744;--yellow:#ffd740;--purple:#7c4dff;
  --text:#cdd9e5;--muted:#566879;--dim:#3d4f61;
  --font:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif;
  --r:4px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{font-size:14px}
body{
  background:var(--black);color:var(--text);font-family:var(--font);
  min-height:100vh;display:flex;flex-direction:column;overflow-x:hidden;
}

/* ── Scanline texture ── */
body::after{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:1000;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.03) 2px,rgba(0,0,0,.03) 4px);
}

/* ── Header ── */
header{
  display:flex;align-items:center;justify-content:space-between;
  padding:.75rem 1.5rem;
  background:var(--surface);
  border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:200;
  box-shadow:0 1px 0 var(--border2);
}
.logo{display:flex;align-items:center;gap:.75rem;font-size:1.1rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
.logo-mark{
  width:32px;height:32px;background:var(--accent);
  display:flex;align-items:center;justify-content:center;
  font-size:.9rem;color:#000;font-weight:700;clip-path:polygon(8% 0%,92% 0%,100% 8%,100% 92%,92% 100%,8% 100%,0% 92%,0% 8%);
  animation:logoPulse 4s ease-in-out infinite;
}
@keyframes logoPulse{0%,100%{box-shadow:0 0 0 0 rgba(0,212,170,.4)}50%{box-shadow:0 0 0 8px rgba(0,212,170,0)}}
.logo-text{color:var(--text)}
.logo-text em{color:var(--accent);font-style:normal}
.header-right{display:flex;align-items:center;gap:.75rem}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.chip{
  padding:.2rem .5rem;font-size:.65rem;font-weight:600;letter-spacing:.08em;
  border:1px solid currentColor;border-radius:2px;text-transform:uppercase;
}
.chip-live{color:var(--green);border-color:rgba(0,230,118,.3);background:rgba(0,230,118,.06)}
.chip-ver{color:var(--muted);border-color:var(--border2)}

/* ── Nav ── */
nav{
  display:flex;gap:0;
  border-bottom:1px solid var(--border);
  background:var(--surface);
  overflow-x:auto;
  scrollbar-width:none;
}
nav::-webkit-scrollbar{display:none}
.nav-item{
  padding:.65rem 1.25rem;font-size:.75rem;font-weight:500;letter-spacing:.08em;
  text-transform:uppercase;color:var(--muted);cursor:pointer;border:none;background:none;
  border-bottom:2px solid transparent;transition:all .15s;white-space:nowrap;
  position:relative;
}
.nav-item:hover{color:var(--text)}
.nav-item.active{color:var(--accent);border-bottom-color:var(--accent)}
.nav-item .n-count{
  display:inline-flex;align-items:center;justify-content:center;
  width:16px;height:16px;border-radius:2px;font-size:.6rem;
  background:rgba(0,212,170,.15);color:var(--accent);margin-left:.35rem;
}

/* ── Layout ── */
main{flex:1;padding:1.5rem;display:flex;flex-direction:column;gap:1.25rem}

/* ── KPI Grid ── */
.kpi-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:.75rem}
@media(max-width:900px){.kpi-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
.kpi{
  background:var(--panel);border:1px solid var(--border);
  padding:1rem 1.125rem;position:relative;overflow:hidden;
  cursor:default;transition:border-color .2s;
}
.kpi:hover{border-color:var(--border2)}
.kpi::before{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
  opacity:0;transition:opacity .3s;
}
.kpi:hover::before{opacity:1}
.kpi-label{font-size:.65rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:.6rem}
.kpi-val{font-size:1.75rem;font-weight:700;line-height:1;letter-spacing:-.02em;margin-bottom:.35rem}
.kpi-val.c-green{color:var(--green)}
.kpi-val.c-red{color:var(--red)}
.kpi-val.c-accent{color:var(--accent)}
.kpi-val.c-blue{color:var(--accent2)}
.kpi-val.c-purple{color:var(--purple)}
.kpi-sub{font-size:.65rem;color:var(--dim)}
.kpi-sparkline{margin-top:.5rem}

/* ── Section ── */
.section{display:flex;flex-direction:column;gap:.75rem}
.section-head{display:flex;align-items:center;justify-content:space-between}
.section-title{font-size:.7rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.section-actions{display:flex;gap:.5rem;align-items:center}

/* ── Buttons ── */
.btn{
  padding:.35rem .9rem;font-family:var(--font);font-size:.7rem;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;cursor:pointer;border-radius:var(--r);
  border:1px solid transparent;transition:all .15s;
}
.btn-primary{background:var(--accent);color:#000;border-color:var(--accent)}
.btn-primary:hover{background:#00efbf;border-color:#00efbf}
.btn-ghost{background:transparent;color:var(--muted);border-color:var(--border2)}
.btn-ghost:hover{color:var(--text);border-color:var(--accent)}
.btn-danger{background:rgba(255,23,68,.1);color:var(--red);border-color:rgba(255,23,68,.3)}
.btn-sm{padding:.2rem .6rem;font-size:.62rem}
.btn:disabled{opacity:.4;cursor:not-allowed}

/* ── Panel / Table ── */
.panel{background:var(--panel);border:1px solid var(--border);overflow:hidden}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
thead tr{border-bottom:1px solid var(--border2)}
th{
  padding:.55rem .9rem;font-size:.6rem;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:var(--dim);text-align:left;
  background:rgba(255,255,255,.015);white-space:nowrap;
}
td{
  padding:.6rem .9rem;font-size:.78rem;border-bottom:1px solid rgba(26,35,50,.6);
  vertical-align:middle;
}
tbody tr:last-child td{border-bottom:none}
tbody tr{transition:background .1s}
tbody tr:hover td{background:rgba(0,212,170,.03)}
.mono{font-family:var(--font);font-size:.72rem}

/* ── Status pills ── */
.pill{
  display:inline-flex;align-items:center;gap:.3rem;padding:.15rem .55rem;
  border-radius:2px;font-size:.62rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  font-family:var(--font);
}
.pill::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor;flex-shrink:0}
.p-success{background:rgba(0,230,118,.1);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.p-failed{background:rgba(255,23,68,.1);color:var(--red);border:1px solid rgba(255,23,68,.2)}
.p-running{background:rgba(0,212,170,.1);color:var(--accent);border:1px solid rgba(0,212,170,.2)}
.p-pending{background:rgba(255,215,64,.1);color:var(--yellow);border:1px solid rgba(255,215,64,.2)}
.p-running::before{animation:pulse 1.2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.2}}

/* ── DB type tag ── */
.db-tag{
  display:inline-flex;align-items:center;gap:.35rem;padding:.12rem .45rem;
  border-radius:2px;font-size:.62rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
}
.db-tag-postgres{background:rgba(0,128,255,.12);color:#5b9fff}
.db-tag-mysql{background:rgba(255,107,53,.12);color:#ff9968}
.db-tag-mariadb{background:rgba(255,107,53,.1);color:#ffaa80}
.db-tag-mongodb{background:rgba(0,230,118,.1);color:#4cdb8a}
.db-tag-redis{background:rgba(255,23,68,.1);color:#ff6690}
.db-tag-influxdb{background:rgba(124,77,255,.1);color:#a88fff}
.db-tag-clickhouse{background:rgba(255,215,64,.1);color:#ffd740}
.db-tag-elasticsearch{background:rgba(0,212,170,.1);color:var(--accent)}

/* ── Log pane ── */
.log-pane{
  background:#020408;border:1px solid var(--border);
  padding:.75rem;font-size:.7rem;font-family:var(--font);
  max-height:280px;overflow-y:auto;line-height:1.8;
  scrollbar-width:thin;scrollbar-color:var(--border2) transparent;
}
.log-pane::-webkit-scrollbar{width:4px}
.log-pane::-webkit-scrollbar-track{background:transparent}
.log-pane::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
.log-entry{display:flex;gap:.75rem;padding:.05rem 0}
.log-ts{color:var(--dim);flex-shrink:0;min-width:8ch}
.log-lv-info{color:var(--accent);min-width:5ch;flex-shrink:0}
.log-lv-warn{color:var(--yellow);min-width:5ch;flex-shrink:0}
.log-lv-error{color:var(--red);min-width:5ch;flex-shrink:0}
.log-msg{color:#8899aa}
.log-field{color:var(--muted)}

/* ── Progress bar ── */
.pbar{height:2px;background:var(--border);overflow:hidden}
.pbar-fill{height:100%;transition:width .4s ease;background:linear-gradient(90deg,var(--accent),var(--accent2))}

/* ── Form ── */
.form-group{margin-bottom:.9rem}
.form-label{display:block;font-size:.65rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:.4rem}
.form-input{
  width:100%;padding:.5rem .75rem;background:var(--black);
  border:1px solid var(--border2);color:var(--text);
  font-family:var(--font);font-size:.78rem;outline:none;border-radius:var(--r);
  transition:border-color .15s;
}
.form-input:focus{border-color:var(--accent)}
.form-row{display:flex;gap:.75rem}
.form-row .form-group{flex:1}

/* ── Modal ── */
.overlay{
  display:none;position:fixed;inset:0;
  background:rgba(4,6,8,.85);backdrop-filter:blur(6px);
  z-index:500;align-items:center;justify-content:center;
}
.overlay.open{display:flex}
.modal{
  background:var(--panel);border:1px solid var(--border2);
  width:480px;max-width:calc(100vw - 2rem);
  animation:slideIn .2s ease-out;
}
@keyframes slideIn{from{opacity:0;transform:translateY(-16px)}to{opacity:1;transform:none}}
.modal-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:.9rem 1.25rem;border-bottom:1px solid var(--border);
}
.modal-title{font-size:.8rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.modal-close{
  width:24px;height:24px;border:none;background:none;color:var(--muted);
  cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center;
}
.modal-close:hover{color:var(--text)}
.modal-body{padding:1.25rem}
.modal-footer{
  display:flex;justify-content:flex-end;gap:.5rem;
  padding:.9rem 1.25rem;border-top:1px solid var(--border);
}

/* ── Toast ── */
#toast{
  position:fixed;bottom:1.5rem;right:1.5rem;z-index:999;
  background:var(--panel);border:1px solid var(--border2);
  padding:.6rem 1rem;font-size:.75rem;
  display:flex;align-items:center;gap:.6rem;max-width:340px;
  transform:translateY(80px);opacity:0;transition:all .25s;
}
#toast.show{transform:none;opacity:1}
#toast .t-icon{font-size:.9rem}

/* ── Tabs ── */
.tab{display:none}
.tab.active{display:block;animation:fadeUp .25s ease-out}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ── Stats bar ── */
.stats-bar{
  display:flex;gap:1.5rem;padding:.6rem 1.25rem;
  background:var(--surface);border:1px solid var(--border);
  font-size:.68rem;color:var(--muted);
  overflow-x:auto;scrollbar-width:none;
}
.stats-bar::-webkit-scrollbar{display:none}
.stat-item{display:flex;align-items:center;gap:.4rem;white-space:nowrap}
.stat-val{color:var(--text);font-weight:600}

/* ── Charts (mini sparklines via canvas) ── */
canvas.spark{display:block}

/* ── Empty state ── */
.empty{text-align:center;padding:3rem 1rem;color:var(--dim)}
.empty-icon{font-size:2rem;margin-bottom:.75rem;opacity:.4}
.empty-text{font-size:.75rem}

/* ── Tooltip ── */
[title]{cursor:help}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-mark">⛁</div>
    <span class="logo-text">dock<em>up</em></span>
  </div>
  <div class="header-right">
    <span class="dot"></span>
    <span class="chip chip-live">Live</span>
    <span class="chip chip-ver" id="hdr-version">v1.0.0</span>
    <button class="btn btn-ghost btn-sm" onclick="openLogin()">Login</button>
  </div>
</header>

<nav>
  <button class="nav-item active" onclick="showTab('dashboard',this)">Dashboard</button>
  <button class="nav-item" onclick="showTab('databases',this)">Databases<span class="n-count" id="nav-db-count">0</span></button>
  <button class="nav-item" onclick="showTab('history',this)">History<span class="n-count" id="nav-job-count">0</span></button>
  <button class="nav-item" onclick="showTab('logs',this)">Logs</button>
  <button class="nav-item" onclick="showTab('settings',this)">Settings</button>
  <button class="nav-item" onclick="showTab('api',this)">API Ref</button>
</nav>

<!-- Stats bar -->
<div class="stats-bar" id="stats-bar">
  <div class="stat-item">Workers: <span class="stat-val" id="sb-workers">—</span></div>
  <div class="stat-item">Queue: <span class="stat-val" id="sb-queue">—</span></div>
  <div class="stat-item">Uptime: <span class="stat-val" id="sb-uptime">—</span></div>
  <div class="stat-item">Databases: <span class="stat-val" id="sb-dbs">—</span></div>
  <div class="stat-item">Total Stored: <span class="stat-val" id="sb-size">—</span></div>
</div>

<main>

<!-- ══ DASHBOARD ══ -->
<div id="tab-dashboard" class="tab active">
  <div class="kpi-grid" id="kpi-grid">
    <div class="kpi"><div class="kpi-label">Discovered</div><div class="kpi-val c-accent" id="kpi-disc">—</div><div class="kpi-sub">active targets</div></div>
    <div class="kpi"><div class="kpi-label">Successful</div><div class="kpi-val c-green" id="kpi-succ">—</div><div class="kpi-sub">total backups</div></div>
    <div class="kpi"><div class="kpi-label">Failed</div><div class="kpi-val c-red" id="kpi-fail">—</div><div class="kpi-sub">needs attention</div></div>
    <div class="kpi"><div class="kpi-label">Queue Depth</div><div class="kpi-val c-blue" id="kpi-queue">—</div><div class="kpi-sub">jobs pending</div></div>
    <div class="kpi"><div class="kpi-label">Uptime</div><div class="kpi-val c-purple" id="kpi-uptime">—</div><div class="kpi-sub">since restart</div></div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-title">Recent Jobs</span>
      <div class="section-actions">
        <span class="chip" id="last-refresh" style="color:var(--dim)">—</span>
        <button class="btn btn-ghost btn-sm" onclick="refresh()">↻ Refresh</button>
      </div>
    </div>
    <div class="panel table-wrap">
      <table>
        <thead><tr>
          <th>Target</th><th>Type</th><th>Status</th>
          <th>Duration</th><th>Size</th><th>Started</th><th>Actions</th>
        </tr></thead>
        <tbody id="dash-jobs">
          <tr><td colspan="7" class="empty"><div class="empty-icon">◌</div><div class="empty-text">Loading...</div></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-title">Event Stream</span>
      <span class="chip chip-live">● Live</span>
    </div>
    <div class="log-pane" id="event-log"></div>
  </div>
</div>

<!-- ══ DATABASES ══ -->
<div id="tab-databases" class="tab">
  <div class="section">
    <div class="section-head">
      <span class="section-title">Discovered Databases</span>
      <button class="btn btn-primary btn-sm" onclick="loadDatabases()">↻ Rescan</button>
    </div>
    <div class="panel table-wrap">
      <table>
        <thead><tr>
          <th>Name</th><th>Type</th><th>Host</th><th>Source</th>
          <th>Schedule</th><th>Retention</th><th>Status</th><th>Actions</th>
        </tr></thead>
        <tbody id="db-table"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ══ HISTORY ══ -->
<div id="tab-history" class="tab">
  <div class="section">
    <div class="section-head">
      <span class="section-title">Backup History</span>
      <div class="section-actions">
        <select class="form-input btn-sm" id="hist-filter" onchange="filterHistory()" style="width:auto;padding:.2rem .5rem">
          <option value="">All targets</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="loadHistory()">↻ Refresh</button>
      </div>
    </div>
    <div class="panel table-wrap">
      <table>
        <thead><tr>
          <th>Job ID</th><th>Target</th><th>Type</th><th>Status</th>
          <th>Duration</th><th>Size</th><th>Completed</th><th>Error</th>
        </tr></thead>
        <tbody id="hist-table"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ══ LOGS ══ -->
<div id="tab-logs" class="tab">
  <div class="section">
    <div class="section-head">
      <span class="section-title">Application Logs</span>
      <div class="section-actions">
        <button class="btn btn-ghost btn-sm" onclick="clearLogs()">Clear</button>
        <button class="btn btn-ghost btn-sm" id="autoscroll-btn" onclick="toggleAutoscroll()">Autoscroll ●</button>
      </div>
    </div>
    <div class="log-pane" id="full-log" style="max-height:65vh"></div>
  </div>
</div>

<!-- ══ SETTINGS ══ -->
<div id="tab-settings" class="tab">
  <div class="section">
    <div class="section-head"><span class="section-title">Retention Policy</span></div>
    <div class="panel" style="padding:1.5rem;max-width:480px">
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Max Backups per Target</label>
          <input class="form-input" type="number" id="ret-count" value="7" min="1" max="365">
        </div>
        <div class="form-group">
          <label class="form-label">Max Age (hours)</label>
          <input class="form-input" type="number" id="ret-age" value="168" min="1">
        </div>
      </div>
      <button class="btn btn-primary" onclick="saveRetention()">Save Policy</button>
    </div>
  </div>

  <div class="section">
    <div class="section-head"><span class="section-title">Supported Database Types</span></div>
    <div class="panel" style="padding:1rem 1.25rem">
      <div style="display:flex;flex-wrap:wrap;gap:.5rem">
        <span class="db-tag db-tag-postgres">PostgreSQL</span>
        <span class="db-tag db-tag-mysql">MySQL</span>
        <span class="db-tag db-tag-mariadb">MariaDB</span>
        <span class="db-tag db-tag-mongodb">MongoDB</span>
        <span class="db-tag db-tag-redis">Redis</span>
        <span class="db-tag db-tag-influxdb">InfluxDB</span>
        <span class="db-tag db-tag-clickhouse">ClickHouse</span>
        <span class="db-tag db-tag-elasticsearch">Elasticsearch</span>
      </div>
    </div>
  </div>
</div>

<!-- ══ API REF ══ -->
<div id="tab-api" class="tab">
  <div class="section">
    <div class="section-head">
      <span class="section-title">REST API Reference</span>
      <a href="/docs" target="_blank" class="btn btn-ghost btn-sm">OpenAPI Docs ↗</a>
    </div>
    <div class="panel">
      <div class="log-pane" style="max-height:none">
        ${API_ENDPOINTS}
      </div>
    </div>
  </div>
</div>

</main>

<!-- Login Modal -->
<div class="overlay" id="login-modal">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Authenticate</span>
      <button class="modal-close" onclick="closeLogin()">✕</button>
    </div>
    <div class="modal-body">
      <div class="form-group"><label class="form-label">Username</label><input class="form-input" id="login-user" value="admin"></div>
      <div class="form-group"><label class="form-label">Password</label><input class="form-input" type="password" id="login-pass" value="dockup" onkeydown="if(event.key==='Enter')doLogin()"></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeLogin()">Cancel</button>
      <button class="btn btn-primary" onclick="doLogin()">Login</button>
    </div>
  </div>
</div>

<div id="toast"><span class="t-icon" id="toast-icon">●</span><span id="toast-msg"></span></div>

<script>
const BASE='/api/v1';
let token=localStorage.getItem('dockup_token')||'';
let autoscroll=true;
let allHistory=[];

function h(){return{Authorization:token,'Content-Type':'application/json'}}

async function api(path,opts={}){
  try{
    const r=await fetch(BASE+path,{headers:h(),...opts});
    if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||r.statusText)}
    return await r.json();
  }catch(e){log_entry('error',e.message);return null}
}

/* ── Tab ── */
function showTab(name,btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  if(btn)btn.classList.add('active');
  if(name==='databases')loadDatabases();
  if(name==='history')loadHistory();
}

/* ── Status ── */
async function loadStatus(){
  const d=await api('/status');if(!d)return;
  set('kpi-disc',d.discovered_databases??'0');
  set('kpi-queue',d.queue_depth??'0');
  set('kpi-uptime',fmtUptime(d.uptime_seconds));
  set('sb-workers',d.active_workers??'—');
  set('sb-queue',d.queue_depth??'0');
  set('sb-uptime',fmtUptime(d.uptime_seconds));
  set('sb-dbs',d.discovered_databases??'0');
  set('hdr-version','v'+d.version);
  renderDashJobs(d.recent_jobs||[]);
}

async function loadHistory(){
  const jobs=await api('/history?limit=200');if(!jobs)return;
  allHistory=jobs;
  renderHistTable(jobs);
  set('nav-job-count',jobs.length);
  const succ=jobs.filter(j=>j.status==='success').length;
  const fail=jobs.filter(j=>j.status==='failed').length;
  const total=jobs.reduce((a,j)=>a+(j.size_bytes||0),0);
  set('kpi-succ',succ);
  set('kpi-fail',fail);
  set('sb-size',fmtBytes(total));
}

async function loadDatabases(){
  const dbs=await api('/databases');
  const tbody=document.getElementById('db-table');
  set('nav-db-count',dbs?dbs.length:0);
  if(!dbs||!dbs.length){tbody.innerHTML=emptyRow(8,'No databases discovered — add dockup labels to containers');return}
  tbody.innerHTML=dbs.map(d=>`
  <tr>
    <td><strong>${esc(d.name)}</strong></td>
    <td>${dbTag(d.db_type)}</td>
    <td class="mono">${esc(d.host)}:${d.port}</td>
    <td class="mono" style="color:var(--dim)">${esc(d.source||'docker')}</td>
    <td class="mono">${esc(d.schedule||'@daily')}</td>
    <td class="mono">${d.retention_days||7}d</td>
    <td>${d.enabled?'<span class="pill p-success">enabled</span>':'<span class="pill p-failed">disabled</span>'}</td>
    <td><button class="btn btn-primary btn-sm" onclick="triggerBackup('${d.id}','${esc(d.name)}')">▶ Backup</button></td>
  </tr>`).join('');
  // Populate filter
  const sel=document.getElementById('hist-filter');
  const existing=Array.from(sel.options).map(o=>o.value);
  dbs.forEach(d=>{if(!existing.includes(d.id)){const o=document.createElement('option');o.value=d.id;o.textContent=d.name;sel.appendChild(o)}});
}

function renderDashJobs(jobs){
  const tbody=document.getElementById('dash-jobs');
  if(!jobs.length){tbody.innerHTML=emptyRow(7,'No backup jobs yet');return}
  tbody.innerHTML=jobs.slice(0,12).map(j=>jobRow(j)).join('');
}

function renderHistTable(jobs){
  const tbody=document.getElementById('hist-table');
  if(!jobs.length){tbody.innerHTML=emptyRow(8,'No backup history');return}
  tbody.innerHTML=jobs.map(j=>`
  <tr>
    <td class="mono" style="color:var(--dim)">${j.id.slice(0,8)}…</td>
    <td><strong>${esc(j.target_name)}</strong></td>
    <td>${dbTag(j.db_type)}</td>
    <td>${statusPill(j.status)}</td>
    <td class="mono">${j.duration_seconds?j.duration_seconds.toFixed(1)+'s':'—'}</td>
    <td class="mono">${j.size_bytes?fmtBytes(j.size_bytes):'—'}</td>
    <td class="mono">${fmtTime(j.finished_at||j.started_at)}</td>
    <td class="mono" style="color:var(--red);font-size:.68rem">${j.error?esc(j.error.slice(0,60)):''}</td>
  </tr>`).join('');
}

function filterHistory(){
  const tid=document.getElementById('hist-filter').value;
  renderHistTable(tid?allHistory.filter(j=>j.target_id===tid):allHistory);
}

function jobRow(j){return`
<tr>
  <td><strong>${esc(j.target_name)}</strong></td>
  <td>${dbTag(j.db_type)}</td>
  <td>${statusPill(j.status)}</td>
  <td class="mono">${j.duration_seconds?j.duration_seconds.toFixed(1)+'s':'—'}</td>
  <td class="mono">${j.size_bytes?fmtBytes(j.size_bytes):'—'}</td>
  <td class="mono">${fmtTime(j.started_at)}</td>
  <td><button class="btn btn-ghost btn-sm" onclick="triggerBackup('${j.target_id}','${esc(j.target_name)}')">↻ Retry</button></td>
</tr>`}

async function triggerBackup(id,name){
  toast(`Triggering backup: ${name}…`,'info');
  const r=await api('/backup/'+id,{method:'POST'});
  if(r){
    log_entry('info',`Backup ${r.status}: ${name} (${r.job_id.slice(0,8)})`);
    toast(`Backup ${r.status}: ${name}`,(r.status==='success'?'success':'error'));
    await refresh();
  }
}

async function refresh(){
  await loadStatus();
  await loadHistory();
  set('last-refresh','Updated '+new Date().toLocaleTimeString());
  log_entry('info','Status refreshed');
}

async function saveRetention(){
  const r=await api('/retention',{method:'PUT',body:JSON.stringify({max_count:+document.getElementById('ret-count').value,max_age_hours:+document.getElementById('ret-age').value})});
  if(r)toast('Retention policy saved','success');
}

/* ── Auth ── */
function openLogin(){document.getElementById('login-modal').classList.add('open')}
function closeLogin(){document.getElementById('login-modal').classList.remove('open')}
async function doLogin(){
  const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('login-user').value,password:document.getElementById('login-pass').value})});
  const d=await r.json();
  if(d.access_token){token=d.access_token;localStorage.setItem('dockup_token',token);toast('Logged in as '+document.getElementById('login-user').value+' ('+d.role+')','success');closeLogin();}
  else toast(d.detail||'Login failed','error');
}

/* ── Logs ── */
function log_entry(level,msg,fields={}){
  const pane=document.getElementById('event-log');
  const full=document.getElementById('full-log');
  const ts=new Date().toLocaleTimeString();
  const fd=Object.entries(fields).map(([k,v])=>`<span class="log-field"> ${k}=</span><span style="color:var(--text)">${v}</span>`).join('');
  const html=`<div class="log-entry"><span class="log-ts">${ts}</span><span class="log-lv-${level}">${level.toUpperCase()}</span><span class="log-msg"> ${esc(msg)}${fd}</span></div>`;
  [pane,full].forEach(el=>{if(el){el.insertAdjacentHTML('afterbegin',html);while(el.children.length>200)el.removeChild(el.lastChild)}});
  if(autoscroll&&full)full.scrollTop=0;
}
function clearLogs(){['event-log','full-log'].forEach(id=>{const el=document.getElementById(id);if(el)el.innerHTML=''})}
function toggleAutoscroll(){autoscroll=!autoscroll;document.getElementById('autoscroll-btn').textContent='Autoscroll '+(autoscroll?'●':'○')}

/* ── Toast ── */
let _tt;
function toast(msg,type='info'){
  const t=document.getElementById('toast');
  const icons={success:'✓',error:'✕',info:'◉',warning:'⚠'};
  document.getElementById('toast-msg').textContent=msg;
  document.getElementById('toast-icon').textContent=icons[type]||'◉';
  t.style.borderColor={'success':'rgba(0,230,118,.4)','error':'rgba(255,23,68,.4)','warning':'rgba(255,215,64,.4)'}[type]||'var(--border2)';
  t.style.color={'success':'var(--green)','error':'var(--red)','warning':'var(--yellow)'}[type]||'var(--text)';
  t.classList.add('show');clearTimeout(_tt);
  _tt=setTimeout(()=>t.classList.remove('show'),3500);
}

/* ── Formatting ── */
function fmtBytes(b){if(!b)return'0 B';const u=['B','KB','MB','GB','TB'];let i=0;while(b>=1024&&i<4){b/=1024;i++}return b.toFixed(1)+' '+u[i]}
function fmtUptime(s){if(!s)return'—';if(s<60)return s.toFixed(0)+'s';if(s<3600)return(s/60).toFixed(0)+'m';if(s<86400)return(s/3600).toFixed(1)+'h';return(s/86400).toFixed(1)+'d'}
function fmtTime(t){if(!t)return'—';return new Date(t).toLocaleString()}
function set(id,v){const el=document.getElementById(id);if(el)el.textContent=v}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function emptyRow(cols,msg){return`<tr><td colspan="${cols}"><div class="empty"><div class="empty-icon">◌</div><div class="empty-text">${msg}</div></div></td></tr>`}
function statusPill(s){const m={success:'p-success',failed:'p-failed',running:'p-running',pending:'p-pending'};return`<span class="pill ${m[s]||'p-pending'}">${s}</span>`}
function dbTag(t){return`<span class="db-tag db-tag-${t||'unknown'}">${t||'unknown'}</span>`}

/* ── API Reference HTML ── */
document.getElementById('tab-api').querySelector('.log-pane').innerHTML=`
<div class="log-entry"><span class="log-lv-info">POST</span><span class="log-msg">  /api/v1/auth/login          — obtain JWT token</span></div>
<div class="log-entry"><span class="log-lv-info">GET </span><span class="log-msg">  /api/v1/databases           — list discovered databases</span></div>
<div class="log-entry"><span class="log-lv-info">GET </span><span class="log-msg">  /api/v1/databases/:id       — get specific database</span></div>
<div class="log-entry"><span class="log-lv-info">POST</span><span class="log-msg">  /api/v1/backup/:id          — trigger manual backup</span></div>
<div class="log-entry"><span class="log-lv-info">GET </span><span class="log-msg">  /api/v1/history             — backup history (all)</span></div>
<div class="log-entry"><span class="log-lv-info">GET </span><span class="log-msg">  /api/v1/history/:id         — backup history (target)</span></div>
<div class="log-entry"><span class="log-lv-info">GET </span><span class="log-msg">  /api/v1/retention           — get retention policy</span></div>
<div class="log-entry"><span class="log-lv-info">PUT </span><span class="log-msg">  /api/v1/retention           — update retention policy</span></div>
<div class="log-entry"><span class="log-lv-info">GET </span><span class="log-msg">  /api/v1/status              — system status</span></div>
<div class="log-entry"><span style="color:var(--purple)">GET </span><span class="log-msg">  /metrics                    — Prometheus exposition</span></div>
<div class="log-entry"><span style="color:var(--yellow)">GET </span><span class="log-msg">  /zabbix                     — Zabbix HTTP agent metrics</span></div>
<div class="log-entry"><span style="color:var(--dim)">GET </span><span class="log-msg">  /health                     — liveness check</span></div>
<div class="log-entry"><span style="color:var(--dim)">GET </span><span class="log-msg">  /ready                      — readiness check</span></div>
<div class="log-entry"><span style="color:var(--dim)">GET </span><span class="log-msg">  /docs                       — Swagger UI</span></div>
<div class="log-entry"><span style="color:var(--dim)">GET </span><span class="log-msg">  /redoc                      — ReDoc documentation</span></div>
`;

/* ── Init ── */
(async()=>{
  log_entry('info','dockup UI initialising');
  await refresh();
  log_entry('info','Connected to API');
  setInterval(refresh,30000);
})();
</script>
</body>
</html>
"""
