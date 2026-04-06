
import atexit
import hashlib
import html
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set

import requests
from flask import Flask, Response, jsonify, render_template_string, send_from_directory, stream_with_context

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
LOG_DIR = Path(os.getenv("LOG_DIR", DATA_DIR / "logs"))
STATE_FILE = Path(os.getenv("STATE_FILE", DATA_DIR / "btc_state.json"))
BACKUP_STATE_FILE = Path(os.getenv("BACKUP_STATE_FILE", DATA_DIR / "backup_state.json"))
ENGINE_FILE = Path(os.getenv("ENGINE_FILE", BASE_DIR / "engine.py"))
RUN_BOT = os.getenv("RUN_BOT", "true").lower() == "true"
AUTO_RESTART = os.getenv("AUTO_RESTART", "true").lower() == "true"
BOT_RESTART_DELAY_SEC = int(os.getenv("BOT_RESTART_DELAY_SEC", "5"))
TAIL_LINES = int(os.getenv("TAIL_LINES", "400"))
MAX_BUFFER_LINES = int(os.getenv("MAX_BUFFER_LINES", "1000"))
TZ_OFFSET = int(os.getenv("TIMEZONE_OFFSET", "7"))

ENABLE_BACKUP = os.getenv("ENABLE_BACKUP", "true").lower() == "true"
ENABLE_TELEGRAM_BACKUP = os.getenv("ENABLE_TELEGRAM_BACKUP", "true").lower() == "true"
ENABLE_TELEGRAM_FILE_BACKUP = os.getenv("ENABLE_TELEGRAM_FILE_BACKUP", "false").lower() == "true"
BACKUP_INTERVAL_SEC = int(os.getenv("BACKUP_INTERVAL_SEC", "300"))
TELEGRAM_BACKUP_CHAT_ID = os.getenv("TELEGRAM_BACKUP_CHAT_ID") or os.getenv("CHAT_ID", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def local_now_text() -> str:
    return datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d %H:%M:%S")


def iso_time(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.utcfromtimestamp(ts + TZ_OFFSET * 3600).strftime("%Y-%m-%d %H:%M:%S")


def ensure_bootstrap_files() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps(
                {"bootstrapped_at": local_now_text(), "status": "bootstrapped", "version": "V9.3"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    today = datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}.log"
    if not log_file.exists():
        log_file.write_text("", encoding="utf-8")


ensure_bootstrap_files()
os.environ["STATE_FILE"] = str(STATE_FILE)
app = Flask(__name__)
BACKUP_MANAGER_HOOK = None


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_log_file() -> Optional[Path]:
    files = sorted(LOG_DIR.glob("*.log"))
    return files[-1] if files else None


def tail_file(path: Optional[Path], max_lines: int = TAIL_LINES) -> List[str]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=max_lines)]


def read_state() -> Dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def summarize_log(lines: List[str]) -> Dict:
    text = "\n".join(lines[-120:])
    def last_match(pattern: str) -> Optional[str]:
        matches = re.findall(pattern, text, flags=re.MULTILINE)
        return matches[-1] if matches else None

    bias = last_match(r"BIAS\s*:\s*(.+)")
    phase = last_match(r"PHASE\s*:\s*(.+)")
    verdict = last_match(r"VERDICT\s*:\s*(.+)")
    quick = last_match(r"QUICK TAKE\s*:\s*(.+)")
    event = last_match(r"EVENT\s*:\s*(.+)")
    grade = last_match(r"GRADE\s*:\s*(.+)")
    trigger = last_match(r"TRIGGER\s*:\s*(.+)")
    return {
        "bias": bias,
        "phase": phase,
        "verdict": verdict,
        "quick_take": quick,
        "event": event,
        "grade": grade,
        "trigger": trigger,
    }


class BotSupervisor:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.buffer: Deque[str] = deque(maxlen=MAX_BUFFER_LINES)
        self.last_line_at: Optional[float] = None
        self.last_start_at: Optional[float] = None
        self.last_exit_code: Optional[int] = None
        self.restart_count = 0
        self.status = "idle"
        self.subscribers: List[queue.Queue] = []

    def _today_file(self) -> Path:
        today = datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d")
        return LOG_DIR / f"{today}.log"

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=300)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass

    def _broadcast(self, line: str) -> None:
        dead = []
        for q in self.subscribers:
            try:
                q.put_nowait(line)
            except Exception:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    def _write_line(self, line: str) -> None:
        self.buffer.append(line)
        self.last_line_at = time.time()
        logfile = self._today_file()
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        try:
            state = read_state()
            state.update({"last_log_line_at": local_now_text(), "status": self.status or "running"})
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        self._broadcast(line)
        hook = globals().get("BACKUP_MANAGER_HOOK")
        if hook is not None:
            try:
                hook.trigger_now(reason=f"log-updated:{logfile.name}")
            except Exception:
                pass

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            self.status = "starting"
            self.last_start_at = time.time()
            cmd = [sys.executable, "-u", str(ENGINE_FILE)]
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            self.process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            self.status = "running"
            self._write_line(f"[{local_now_text()}] supervisor: started bot pid={self.process.pid}")
            assert self.process.stdout is not None
            for raw in self.process.stdout:
                if self.stop_event.is_set():
                    break
                self._write_line(raw.rstrip("\n"))
            code = self.process.wait()
            self.last_exit_code = code
            if self.stop_event.is_set():
                self.status = "stopped"
                self._write_line(f"[{local_now_text()}] supervisor: bot stopped gracefully code={code}")
                break
            self.status = "crashed" if code else "stopped"
            self._write_line(f"[{local_now_text()}] supervisor: bot exited code={code}")
            if not AUTO_RESTART:
                break
            self.restart_count += 1
            self.status = "restarting"
            self._write_line(f"[{local_now_text()}] supervisor: restarting in {BOT_RESTART_DELAY_SEC}s")
            time.sleep(BOT_RESTART_DELAY_SEC)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.status = "stopped"

    def health(self) -> Dict:
        alive = bool(self.process and self.process.poll() is None)
        return {
            "status": self.status,
            "alive": alive,
            "pid": self.process.pid if alive and self.process else None,
            "last_line_at": iso_time(self.last_line_at),
            "last_start_at": iso_time(self.last_start_at),
            "last_exit_code": self.last_exit_code,
            "restart_count": self.restart_count,
            "engine_file": ENGINE_FILE.name,
            "state_file": str(STATE_FILE),
            "log_dir": str(LOG_DIR),
        }


class BackupManager:
    def __init__(self) -> None:
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.state = self._load_state()
        self.status: Dict = {
            "running": False,
            "last_cycle_at": None,
            "last_success_at": None,
            "last_error": None,
            "last_trigger_reason": None,
            "telegram": {
                "enabled": (ENABLE_TELEGRAM_BACKUP and ENABLE_TELEGRAM_FILE_BACKUP),
                "last_success_at": None,
                "last_file": None,
                "last_error": None,
            },
        }

    def trigger_now(self, reason: str = "manual") -> None:
        self.status["last_trigger_reason"] = reason
        self.wake_event.set()

    def _load_state(self) -> Dict:
        if not BACKUP_STATE_FILE.exists():
            return {"telegram": {}}
        try:
            return json.loads(BACKUP_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"telegram": {}}

    def _save_state(self) -> None:
        BACKUP_STATE_FILE.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mark_success(self, channel: str, path: Path) -> None:
        now = time.time()
        info = {
            "path": str(path),
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "md5": md5_file(path),
            "sent_at": now,
        }
        self.state.setdefault(channel, {})[str(path)] = info
        self._save_state()
        self.status[channel]["last_success_at"] = iso_time(now)
        self.status[channel]["last_file"] = path.name
        self.status[channel]["last_error"] = None
        self.status["last_success_at"] = iso_time(now)

    def _should_send(self, channel: str, path: Path) -> bool:
        if not path.exists() or path.stat().st_size == 0:
            return False
        current = {"size": path.stat().st_size, "mtime": path.stat().st_mtime, "md5": md5_file(path)}
        prev = self.state.get(channel, {}).get(str(path), {})
        return any(prev.get(k) != current[k] for k in current)

    def _telegram_send_document(self, path: Path, caption: str) -> None:
        if not TELEGRAM_TOKEN or not TELEGRAM_BACKUP_CHAT_ID:
            raise RuntimeError("missing TELEGRAM_TOKEN or TELEGRAM_BACKUP_CHAT_ID")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with path.open("rb") as f:
            r = requests.post(
                url,
                data={"chat_id": TELEGRAM_BACKUP_CHAT_ID, "caption": caption[:1024]},
                files={"document": (path.name, f)},
                timeout=60,
            )
        r.raise_for_status()

    def _collect_files(self) -> List[Path]:
        files = []
        latest = latest_log_file()
        if latest:
            files.append(latest)
        if STATE_FILE.exists():
            files.append(STATE_FILE)
        return files

    def _cycle(self) -> None:
        ensure_bootstrap_files()
        if not (ENABLE_TELEGRAM_BACKUP and ENABLE_TELEGRAM_FILE_BACKUP):
            self.status["telegram"]["last_error"] = None
            return
        for path in self._collect_files():
            if self._should_send("telegram", path):
                self._telegram_send_document(path, f"BTC backup | {path.name} | {local_now_text()}")
                self._mark_success("telegram", path)

    def _run_loop(self) -> None:
        self.status["running"] = True
        self.trigger_now("startup")
        while not self.stop_event.is_set():
            self.status["last_cycle_at"] = iso_time(time.time())
            try:
                self._cycle()
                self.status["last_error"] = None
            except Exception as exc:
                self.status["last_error"] = str(exc)
                self.status["telegram"]["last_error"] = str(exc)
            self.wake_event.clear()
            self.wake_event.wait(BACKUP_INTERVAL_SEC)
        self.status["running"] = False

    def start(self) -> None:
        if not ENABLE_BACKUP:
            return
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def health(self) -> Dict:
        return self.status


supervisor = BotSupervisor()
backup_manager = BackupManager()
BACKUP_MANAGER_HOOK = backup_manager




def safe_text(v) -> str:
    if v is None:
        return "-"
    return str(v)


def render_summary_cards(summary: Dict) -> str:
    items = [
        ("Bias", safe_text(summary.get("bias"))),
        ("Phase", safe_text(summary.get("phase"))),
        ("Grade", safe_text(summary.get("grade"))),
        ("Event", safe_text(summary.get("event"))),
        ("Verdict", safe_text(summary.get("verdict"))),
        ("Trigger", safe_text(summary.get("trigger"))),
    ]
    return "".join(
        f'<div class="mini"><div class="label">{html.escape(k)}</div><div class="value">{html.escape(v)}</div></div>'
        for k, v in items
    )


def render_bot_status_html(bot: Dict) -> str:
    rows = [
        ("status", safe_text(bot.get("status"))),
        ("alive", safe_text(bot.get("alive"))),
        ("pid", safe_text(bot.get("pid"))),
        ("last start", safe_text(bot.get("last_start_at"))),
        ("last line", safe_text(bot.get("last_line_at"))),
        ("restarts", safe_text(bot.get("restart_count", 0))),
        ("engine", safe_text(bot.get("engine_file"))),
    ]
    out = []
    for k, v in rows:
        cls = ""
        if k == "alive":
            cls = "ok" if str(v).lower() == "true" else "err"
        out.append(f'<div class="row"><span class="muted">{html.escape(k)}</span><strong class="{cls}">{html.escape(v)}</strong></div>')
    return "".join(out)


def render_backup_status_html(backup: Dict) -> str:
    tg = backup.get("telegram") or {}
    rows = [
        ("backup loop", safe_text(backup.get("running"))),
        ("last cycle", safe_text(backup.get("last_cycle_at"))),
        ("trigger", safe_text(backup.get("last_trigger_reason"))),
        ("telegram", "enabled" if tg.get("enabled") else "disabled"),
        ("last file", safe_text(tg.get("last_file"))),
        ("last success", safe_text(tg.get("last_success_at"))),
    ]
    out = []
    for k, v in rows:
        cls = ""
        if k == "backup loop":
            cls = "ok" if str(v).lower() == "true" else "warn"
        if k == "telegram":
            cls = "err" if tg.get("last_error") else "ok"
        out.append(f'<div class="row"><span class="muted">{html.escape(k)}</span><strong class="{cls}">{html.escape(v)}</strong></div>')
    note = f'TG error: {tg.get("last_error")}' if tg.get("last_error") else "Telegram file backup disabled"
    out.append(f'<div class="muted">{html.escape(note)}</div>')
    return "".join(out)


@app.route("/")
def dashboard():
    latest = latest_log_file()
    initial_status = {
        "bot": supervisor.health(),
        "backup": backup_manager.health(),
        "state": read_state(),
        "summary": summarize_log(tail_file(latest)) if latest else {},
        "latest_log_file": latest.name if latest else None,
        "log_files": [p.name for p in sorted(LOG_DIR.glob("*.log"), reverse=True)[:14]],
    }
    initial_logs = {
        "file": latest.name if latest else None,
        "lines": tail_file(latest) if latest else list(supervisor.buffer),
    }
    return render_template_string(
        TEMPLATE,
        initial_status_json=json.dumps(initial_status, ensure_ascii=False),
        initial_logs_json=json.dumps(initial_logs, ensure_ascii=False),
        initial_bot_html=render_bot_status_html(initial_status["bot"]),
        initial_backup_html=render_backup_status_html(initial_status["backup"]),
        initial_summary_html=render_summary_cards(initial_status["summary"]),
        initial_state_pre=json.dumps(initial_status["state"], ensure_ascii=False, indent=2),
        initial_file_options=initial_status["log_files"],
        initial_current_file=initial_logs["file"],
        initial_log_text="\n".join(initial_logs["lines"]),
    )


@app.route("/health")
def health():
    latest = latest_log_file()
    return jsonify({"ok": True, **supervisor.health(), "backup": backup_manager.health(), "latest_log_file": latest.name if latest else None, "summary": summarize_log(tail_file(latest)) if latest else {}})


@app.route("/api/status")
def api_status():
    state = read_state()
    latest = latest_log_file()
    return jsonify(
        {
            "bot": supervisor.health(),
            "backup": backup_manager.health(),
            "state": state,
            "summary": summarize_log(tail_file(latest)) if latest else {},
            "latest_log_file": latest.name if latest else None,
            "log_files": [p.name for p in sorted(LOG_DIR.glob("*.log"), reverse=True)[:14]],
        }
    )


@app.route("/api/logs")
def api_logs():
    latest = latest_log_file()
    lines = tail_file(latest) if latest else list(supervisor.buffer)
    return jsonify({"file": latest.name if latest else None, "lines": lines[-TAIL_LINES:]})


@app.route("/api/logs/<path:filename>")
def api_logs_by_name(filename: str):
    path = LOG_DIR / filename
    lines = tail_file(path)
    return jsonify({"file": filename, "lines": lines[-TAIL_LINES:]})


@app.route("/download/<path:filename>")
def download_log(filename: str):
    return send_from_directory(LOG_DIR, filename, as_attachment=True)


TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTC Bot V9.3.2 Frontend Hydration + Null-safe Render Fix</title>
  <style>
    body { font-family: Arial, sans-serif; background:#0b1020; color:#e7ecf5; margin:0; }
    .wrap { max-width: 1440px; margin: 0 auto; padding: 16px; }
    .grid { display:grid; grid-template-columns: 380px 1fr; gap:16px; }
    .stack > * + * { margin-top: 12px; }
    .card { background:#131a2e; border:1px solid #24304d; border-radius:16px; padding:16px; box-shadow:0 10px 25px rgba(0,0,0,.25); }
    h1,h2,h3 { margin:0 0 12px 0; }
    .muted { color:#93a1bf; font-size:14px; }
    .badge { display:inline-block; padding:6px 10px; border-radius:999px; background:#1d2742; border:1px solid #324269; font-size:12px; }
    .ok { color:#7CFC9A; }
    .warn { color:#ffd166; }
    .err { color:#ff7b7b; }
    .logbox { background:#090d19; color:#d9e4ff; min-height:72vh; white-space:pre-wrap; overflow:auto; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; line-height:1.4; padding:16px; border-radius:12px; border:1px solid #1f2942; }
    .row { display:flex; justify-content:space-between; gap:10px; margin:8px 0; }
    .mini { border:1px solid #24304d; border-radius:12px; padding:10px; margin:8px 0; background:#10182b; }
    .label { color:#93a1bf; font-size:12px; margin-bottom:4px; }
    .value { color:#e7ecf5; font-size:14px; word-break:break-word; }
    select { width:100%; background:#0d1324; color:#e7ecf5; border:1px solid #324269; border-radius:10px; padding:10px; }
    a { color:#9ec5ff; text-decoration:none; }
    pre { white-space:pre-wrap; word-break:break-word; margin:0; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>BTC Bot V9.3.2 Frontend Hydration + Null-safe Render Fix</h1>
  <p class="muted">Server-rendered hydration + null-safe polling refresh + Telegram backup only</p>
  <div class="grid">
    <div class="stack">
      <div class="card">
        <h3>Bot Status</h3>
        <div id="status">{{ initial_bot_html | safe }}</div>
      </div>
      <div class="card">
        <h3>Backup Status</h3>
        <div id="backup">{{ initial_backup_html | safe }}</div>
      </div>
      <div class="card">
        <h3>Quick Summary</h3>
        <div id="summary">{{ initial_summary_html | safe }}</div>
      </div>
      <div class="card">
        <h3>Daily Logs</h3>
        <select id="fileSelect">
          {% if initial_file_options %}
            {% for f in initial_file_options %}
              <option value="{{ f }}" {% if f == initial_current_file %}selected{% endif %}>{{ f }}</option>
            {% endfor %}
          {% else %}
            <option value="">No log files</option>
          {% endif %}
        </select>
        <div style="margin-top:10px"><a id="downloadLink" {% if initial_current_file %}href="/download/{{ initial_current_file }}"{% endif %}>Download selected log</a></div>
      </div>
      <div class="card">
        <h3>State Snapshot</h3>
        <div id="state"><pre>{{ initial_state_pre }}</pre></div>
      </div>
    </div>
    <div class="card">
      <div class="row"><h3>Live Log</h3><span class="badge warn" id="streamBadge">hydrated</span></div>
      <div id="logbox" class="logbox">{{ initial_log_text }}</div>
    </div>
  </div>
</div>

<script id="initial-status-data" type="application/json">{{ initial_status_json | safe }}</script>
<script id="initial-logs-data" type="application/json">{{ initial_logs_json | safe }}</script>
<script>
function parseInitialJson(id, fallback) {
  try {
    const el = document.getElementById(id);
    if (!el) return fallback;
    return JSON.parse(el.textContent || 'null') || fallback;
  } catch (e) {
    return fallback;
  }
}
const INITIAL_STATUS = parseInitialJson('initial-status-data', {});
const INITIAL_LOGS = parseInitialJson('initial-logs-data', {lines: []});

const logbox = document.getElementById('logbox');
const statusEl = document.getElementById('status');
const backupEl = document.getElementById('backup');
const stateEl = document.getElementById('state');
const summaryEl = document.getElementById('summary');
const fileSelect = document.getElementById('fileSelect');
const downloadLink = document.getElementById('downloadLink');
const streamBadge = document.getElementById('streamBadge');
let currentFile = (INITIAL_LOGS && INITIAL_LOGS.file) || (INITIAL_STATUS && INITIAL_STATUS.latest_log_file) || '';
let lastRenderedBlob = (INITIAL_LOGS && Array.isArray(INITIAL_LOGS.lines)) ? INITIAL_LOGS.lines.join('\n') : '';

function escHtml(s) {
  return String(s ?? '-')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}
async function jfetch(url) {
  const r = await fetch(url, {cache: 'no-store'});
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return await r.json();
}
function setBadge(text, cls='') {
  streamBadge.textContent = text;
  streamBadge.className = 'badge ' + cls;
}
function renderSummary(s) {
  const items = [
    ['Bias', s && s.bias],
    ['Phase', s && s.phase],
    ['Grade', s && s.grade],
    ['Event', s && s.event],
    ['Verdict', s && s.verdict],
    ['Trigger', s && s.trigger],
  ];
  summaryEl.innerHTML = items.map(([k,v]) => `<div class="mini"><div class="label">${escHtml(k)}</div><div class="value">${escHtml(v || '-')}</div></div>`).join('');
}
function refreshDownload() {
  const val = fileSelect ? fileSelect.value : '';
  if (!val) {
    downloadLink.removeAttribute('href');
    return;
  }
  currentFile = val;
  downloadLink.href = `/download/${encodeURIComponent(currentFile)}`;
}
function renderStatus(data) {
  const bot = (data && data.bot) || {};
  statusEl.innerHTML = `
    <div class="row"><span class="muted">status</span><strong>${escHtml(bot.status || '-')}</strong></div>
    <div class="row"><span class="muted">alive</span><strong class="${bot.alive ? 'ok' : 'err'}">${escHtml(bot.alive)}</strong></div>
    <div class="row"><span class="muted">pid</span><strong>${escHtml(bot.pid ?? '-')}</strong></div>
    <div class="row"><span class="muted">last start</span><strong>${escHtml(bot.last_start_at || '-')}</strong></div>
    <div class="row"><span class="muted">last line</span><strong>${escHtml(bot.last_line_at || '-')}</strong></div>
    <div class="row"><span class="muted">restarts</span><strong>${escHtml(bot.restart_count ?? 0)}</strong></div>
    <div class="row"><span class="muted">engine</span><strong>${escHtml(bot.engine_file || '-')}</strong></div>
  `;
  const backup = (data && data.backup) || {};
  const tg = backup.telegram || {};
  backupEl.innerHTML = `
    <div class="row"><span class="muted">backup loop</span><strong class="${backup.running ? 'ok' : 'warn'}">${escHtml(backup.running)}</strong></div>
    <div class="row"><span class="muted">last cycle</span><strong>${escHtml(backup.last_cycle_at || '-')}</strong></div>
    <div class="row"><span class="muted">trigger</span><strong>${escHtml(backup.last_trigger_reason || '-')}</strong></div>
    <div class="row"><span class="muted">telegram</span><strong class="${tg.last_error ? 'err' : 'ok'}">${escHtml(tg.enabled ? 'enabled' : 'disabled')}</strong></div>
    <div class="row"><span class="muted">last file</span><strong>${escHtml(tg.last_file || '-')}</strong></div>
    <div class="row"><span class="muted">last success</span><strong>${escHtml(tg.last_success_at || '-')}</strong></div>
    <div class="muted">${escHtml(tg.last_error ? ('TG error: ' + tg.last_error) : 'Telegram file backup disabled')}</div>
  `;
  stateEl.innerHTML = `<pre>${escHtml(JSON.stringify((data && data.state) || {}, null, 2))}</pre>`;
  const files = Array.isArray(data && data.log_files) ? data.log_files : [];
  fileSelect.innerHTML = files.length ? files.map(f => `<option value="${escHtml(f)}">${escHtml(f)}</option>`).join('') : '<option value="">No log files</option>';
  if (!currentFile && files.length) currentFile = files[0];
  if (currentFile && files.includes(currentFile)) {
    fileSelect.value = currentFile;
  } else if (files.length) {
    currentFile = files[0];
    fileSelect.value = currentFile;
  }
  refreshDownload();
  renderSummary((data && data.summary) || {});
}
function renderLogs(lines) {
  const safeLines = Array.isArray(lines) ? lines : [];
  const blob = safeLines.join('\n');
  logbox.textContent = blob;
  lastRenderedBlob = blob;
  logbox.scrollTop = logbox.scrollHeight;
}
async function loadSelectedFile() {
  try {
    if (!fileSelect.value) return;
    const data = await jfetch(`/api/logs/${encodeURIComponent(fileSelect.value)}`);
    renderLogs(data.lines || []);
    setBadge('polling', 'warn');
  } catch (e) {
    setBadge('polling error', 'err');
  }
}
if (fileSelect) {
  fileSelect.addEventListener('change', async () => {
    refreshDownload();
    await loadSelectedFile();
  });
}
async function refreshAll(force=false) {
  try {
    const status = await jfetch('/api/status');
    renderStatus(status);
    const latestFromStatus = (status && status.latest_log_file) || '';
    const targetFile = (fileSelect && fileSelect.value) || currentFile || latestFromStatus || '';
    const target = targetFile ? `/api/logs/${encodeURIComponent(targetFile)}` : '/api/logs';
    const logs = await jfetch(target);
    const blob = Array.isArray(logs.lines) ? logs.lines.join('\n') : '';
    if (force || blob !== lastRenderedBlob) {
      renderLogs(logs.lines || []);
    }
    setBadge('auto refresh', 'ok');
  } catch (e) {
    setBadge('offline', 'err');
  }
}
(function bootstrap() {
  try {
    renderStatus(INITIAL_STATUS || {});
    renderLogs((INITIAL_LOGS && INITIAL_LOGS.lines) || []);
    setBadge('auto refresh', 'ok');
  } catch (e) {
    setBadge('render error', 'err');
  }
  setTimeout(() => { refreshAll(true); }, 600);
})();
setInterval(() => { refreshAll(false); }, 2000);
</script>
</body>
</html>
"""

if RUN_BOT:
    supervisor.start()
if ENABLE_BACKUP:
    backup_manager.start()

atexit.register(supervisor.stop)
atexit.register(backup_manager.stop)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
