import atexit
import hashlib
import json
import os
import queue
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

# Backup config
ENABLE_BACKUP = os.getenv("ENABLE_BACKUP", "true").lower() == "true"
ENABLE_TELEGRAM_BACKUP = os.getenv("ENABLE_TELEGRAM_BACKUP", "true").lower() == "true"
ENABLE_GDRIVE_BACKUP = os.getenv("ENABLE_GDRIVE_BACKUP", "true").lower() == "true"
BACKUP_INTERVAL_SEC = int(os.getenv("BACKUP_INTERVAL_SEC", "300"))
TELEGRAM_BACKUP_CHAT_ID = os.getenv("TELEGRAM_BACKUP_CHAT_ID") or os.getenv("CHAT_ID", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def ensure_bootstrap_files() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({"bootstrapped_at": datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d %H:%M:%S"), "status": "bootstrapped"}, ensure_ascii=False, indent=2), encoding="utf-8")
    today = datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}.log"
    if not log_file.exists():
        log_file.write_text("", encoding="utf-8")

ensure_bootstrap_files()

# Ensure engine shares the same state file path
os.environ["STATE_FILE"] = str(STATE_FILE)

app = Flask(__name__)


def iso_time(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.utcfromtimestamp(ts + TZ_OFFSET * 3600).strftime("%Y-%m-%d %H:%M:%S")


def timestamp_text() -> str:
    return datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d %H:%M:%S")


BACKUP_MANAGER_HOOK = None


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class BotSupervisor:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.buffer: Deque[str] = deque(maxlen=MAX_BUFFER_LINES)
        self.last_line_at: Optional[float] = None
        self.last_start_at: Optional[float] = None
        self.last_exit_code: Optional[int] = None
        self.restart_count: int = 0
        self.status: str = "idle"
        self.subscribers: List[queue.Queue] = []

    def _today_file(self) -> Path:
        dt = datetime.utcfromtimestamp(time.time() + TZ_OFFSET * 3600).strftime("%Y-%m-%d")
        return LOG_DIR / f"{dt}.log"

    def _broadcast(self, line: str) -> None:
        dead: List[queue.Queue] = []
        for q in self.subscribers:
            try:
                q.put_nowait(line)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                self.subscribers.remove(q)
            except ValueError:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass

    def _write_line(self, line: str) -> None:
        self.buffer.append(line)
        self.last_line_at = time.time()
        logfile = self._today_file()
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if not STATE_FILE.exists():
            STATE_FILE.write_text(json.dumps({"last_log_line_at": timestamp_text(), "status": "running"}, ensure_ascii=False, indent=2), encoding="utf-8")
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
            self._write_line(f"[{timestamp_text()}] supervisor: started bot pid={self.process.pid}")

            assert self.process.stdout is not None
            for raw in self.process.stdout:
                if self.stop_event.is_set():
                    break
                self._write_line(raw.rstrip("\n"))

            code = self.process.wait()
            self.last_exit_code = code
            if self.stop_event.is_set():
                self.status = "stopped"
                self._write_line(f"[{timestamp_text()}] supervisor: bot stopped gracefully code={code}")
                break

            self.status = "crashed" if code else "stopped"
            self._write_line(f"[{timestamp_text()}] supervisor: bot exited code={code}")
            if not AUTO_RESTART:
                break
            self.restart_count += 1
            self.status = "restarting"
            self._write_line(f"[{timestamp_text()}] supervisor: restarting in {BOT_RESTART_DELAY_SEC}s")
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
        self.lock = threading.Lock()
        self.wake_event = threading.Event()
        self.pending_reasons: Set[str] = set()
        self.state = self._load_state()
        self.status: Dict = {
            "running": False,
            "last_cycle_at": None,
            "last_success_at": None,
            "last_error": None,
            "last_trigger_reason": None,
            "telegram": {"enabled": ENABLE_TELEGRAM_BACKUP, "last_success_at": None, "last_file": None, "last_error": None},
            "gdrive": {"enabled": ENABLE_GDRIVE_BACKUP, "last_success_at": None, "last_file": None, "last_error": None},
        }

    def trigger_now(self, reason: str = "manual") -> None:
        self.pending_reasons.add(reason)
        self.status["last_trigger_reason"] = reason
        self.wake_event.set()

    def _load_state(self) -> Dict:
        if not BACKUP_STATE_FILE.exists():
            return {"telegram": {}, "gdrive": {}}
        try:
            return json.loads(BACKUP_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"telegram": {}, "gdrive": {}}

    def _save_state(self) -> None:
        BACKUP_STATE_FILE.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mark_success(self, channel: str, path: Path) -> None:
        now = time.time()
        digest = md5_file(path)
        info = {
            "path": str(path),
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "md5": digest,
            "sent_at": now,
        }
        self.state.setdefault(channel, {})[str(path)] = info
        self._save_state()
        self.status[channel]["last_success_at"] = iso_time(now)
        self.status[channel]["last_file"] = path.name
        self.status[channel]["last_error"] = None
        self.status["last_success_at"] = iso_time(now)

    def _mark_error(self, channel: str, exc: Exception) -> None:
        msg = str(exc)
        self.status[channel]["last_error"] = msg
        self.status["last_error"] = msg

    def _should_send(self, channel: str, path: Path) -> bool:
        if not path.exists() or path.stat().st_size == 0:
            return False
        current = {
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "md5": md5_file(path),
        }
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

    def _gdrive_client(self):
        if not GDRIVE_FOLDER_ID:
            raise RuntimeError("missing GDRIVE_FOLDER_ID")
        creds_info = None
        if GOOGLE_SERVICE_ACCOUNT_JSON:
            creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        elif GOOGLE_SERVICE_ACCOUNT_FILE:
            creds_info = json.loads(Path(GOOGLE_SERVICE_ACCOUNT_FILE).read_text(encoding="utf-8"))
        else:
            raise RuntimeError("missing GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE")

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/drive.file"]
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _gdrive_upsert(self, service, path: Path) -> None:
        from googleapiclient.http import MediaFileUpload

        query = (
            f"name = '{path.name.replace("'", "\\'")}' and "
            f"'{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        )
        existing = service.files().list(q=query, fields="files(id,name)", pageSize=1).execute().get("files", [])
        media = MediaFileUpload(str(path), resumable=True)
        if existing:
            file_id = existing[0]["id"]
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            meta = {"name": path.name, "parents": [GDRIVE_FOLDER_ID]}
            service.files().create(body=meta, media_body=media, fields="id").execute()

    def _collect_files(self) -> List[Path]:
        files: List[Path] = []
        latest = latest_log_file()
        if latest:
            files.append(latest)
        if STATE_FILE.exists():
            files.append(STATE_FILE)
        return files

    def _cycle(self) -> None:
        ensure_bootstrap_files()
        files = self._collect_files()
        service = None
        for path in files:
            if ENABLE_TELEGRAM_BACKUP and self._should_send("telegram", path):
                caption = f"BTC backup | {path.name} | {timestamp_text()}"
                self._telegram_send_document(path, caption)
                self._mark_success("telegram", path)
            if ENABLE_GDRIVE_BACKUP and self._should_send("gdrive", path):
                if service is None:
                    service = self._gdrive_client()
                self._gdrive_upsert(service, path)
                self._mark_success("gdrive", path)

    def _run_loop(self) -> None:
        self.status["running"] = True
        self.trigger_now(reason="startup")
        while not self.stop_event.is_set():
            self.status["last_cycle_at"] = iso_time(time.time())
            try:
                self._cycle()
                self.status["last_error"] = None
            except Exception as exc:
                self.status["last_error"] = str(exc)
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


def tail_file(path: Optional[Path], max_lines: int = TAIL_LINES) -> List[str]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=max_lines)]


def latest_log_file() -> Optional[Path]:
    files = sorted(LOG_DIR.glob("*.log"))
    return files[-1] if files else None


def read_state() -> Dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.route("/")
def dashboard():
    return render_template_string(TEMPLATE)


@app.route("/health")
def health():
    return jsonify({"ok": True, **supervisor.health(), "backup": backup_manager.health()})


@app.route("/api/status")
def api_status():
    state = read_state()
    latest = latest_log_file()
    return jsonify(
        {
            "bot": supervisor.health(),
            "backup": backup_manager.health(),
            "state": state,
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


@app.route("/stream")
def stream():
    q = supervisor.subscribe()

    def event_stream():
        try:
            bootstrap = list(supervisor.buffer)[-100:]
            for line in bootstrap:
                yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    line = q.get(timeout=15)
                    yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": keep-alive\n\n"
        finally:
            supervisor.unsubscribe(q)

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTC Bot V9.2 Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; background:#0b1020; color:#e7ecf5; margin:0; }
    .wrap { max-width: 1440px; margin: 0 auto; padding: 20px; }
    .grid { display:grid; grid-template-columns: 360px 1fr; gap:16px; }
    .card { background:#131a2e; border:1px solid #24304d; border-radius:16px; padding:16px; box-shadow: 0 10px 25px rgba(0,0,0,.25); }
    h1,h2,h3 { margin: 0 0 12px 0; }
    .muted { color:#93a1bf; font-size: 14px; }
    .badge { display:inline-block; padding:6px 10px; border-radius:999px; background:#1d2742; border:1px solid #324269; font-size:12px; }
    .ok { color:#7CFC9A; }
    .warn { color:#ffd166; }
    .err { color:#ff7b7b; }
    .logbox { background:#090d19; color:#d9e4ff; min-height:72vh; white-space:pre-wrap; overflow:auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; line-height:1.4; padding:16px; border-radius:12px; border:1px solid #1f2942; }
    .row { display:flex; justify-content:space-between; gap:10px; margin:8px 0; }
    .stack > * + * { margin-top: 10px; }
    select { width:100%; background:#0d1324; color:#e7ecf5; border:1px solid #324269; border-radius:10px; padding:10px; }
    a { color:#9ec5ff; text-decoration:none; }
    pre { white-space:pre-wrap; word-break:break-word; margin:0; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>BTC Bot V9.2 Backup Dashboard</h1>
  <p class="muted">Live log + daily log files + bot supervisor + backup status (Telegram + Google Drive)</p>
  <div class="grid">
    <div class="stack">
      <div class="card">
        <h3>Bot Status</h3>
        <div id="status"></div>
      </div>
      <div class="card">
        <h3>Backup Status</h3>
        <div id="backup"></div>
      </div>
      <div class="card">
        <h3>Daily Logs</h3>
        <select id="fileSelect"></select>
        <div style="margin-top:10px"><a id="downloadLink" href="#">Download selected log</a></div>
      </div>
      <div class="card">
        <h3>State Snapshot</h3>
        <div id="state" class="muted"></div>
      </div>
    </div>
    <div class="card">
      <div class="row"><h3>Live Log</h3><span class="badge" id="streamBadge">connecting...</span></div>
      <div id="logbox" class="logbox"></div>
    </div>
  </div>
</div>
<script>
const logbox = document.getElementById('logbox');
const statusEl = document.getElementById('status');
const backupEl = document.getElementById('backup');
const stateEl = document.getElementById('state');
const fileSelect = document.getElementById('fileSelect');
const downloadLink = document.getElementById('downloadLink');
const streamBadge = document.getElementById('streamBadge');
let currentFile = null;

function renderStatus(data) {
  const bot = data.bot || {};
  statusEl.innerHTML = `
    <div class="row"><span class="muted">status</span><strong>${bot.status || '-'}</strong></div>
    <div class="row"><span class="muted">alive</span><strong class="${bot.alive ? 'ok' : 'err'}">${bot.alive}</strong></div>
    <div class="row"><span class="muted">pid</span><strong>${bot.pid ?? '-'}</strong></div>
    <div class="row"><span class="muted">last start</span><strong>${bot.last_start_at || '-'}</strong></div>
    <div class="row"><span class="muted">last line</span><strong>${bot.last_line_at || '-'}</strong></div>
    <div class="row"><span class="muted">restarts</span><strong>${bot.restart_count ?? 0}</strong></div>
    <div class="row"><span class="muted">engine</span><strong>${bot.engine_file || '-'}</strong></div>
  `;

  const backup = data.backup || {};
  const tg = backup.telegram || {};
  const gd = backup.gdrive || {};
  backupEl.innerHTML = `
    <div class="row"><span class="muted">backup loop</span><strong class="${backup.running ? 'ok' : 'warn'}">${backup.running}</strong></div>
    <div class="row"><span class="muted">last cycle</span><strong>${backup.last_cycle_at || '-'}</strong></div>
    <div class="row"><span class="muted">telegram</span><strong class="${tg.last_error ? 'err' : 'ok'}">${tg.enabled ? 'enabled' : 'disabled'}</strong></div>
    <div class="row"><span class="muted">tg last file</span><strong>${tg.last_file || '-'}</strong></div>
    <div class="row"><span class="muted">tg success</span><strong>${tg.last_success_at || '-'}</strong></div>
    <div class="row"><span class="muted">gdrive</span><strong class="${gd.last_error ? 'err' : 'ok'}">${gd.enabled ? 'enabled' : 'disabled'}</strong></div>
    <div class="row"><span class="muted">drive last file</span><strong>${gd.last_file || '-'}</strong></div>
    <div class="row"><span class="muted">drive success</span><strong>${gd.last_success_at || '-'}</strong></div>
    <div class="muted">${tg.last_error ? 'TG error: ' + tg.last_error + '<br>' : ''}${gd.last_error ? 'Drive error: ' + gd.last_error : ''}</div>
  `;

  stateEl.innerHTML = `<pre>${JSON.stringify(data.state || {}, null, 2)}</pre>`;
  const files = data.log_files || [];
  fileSelect.innerHTML = files.map(f => `<option value="${f}">${f}</option>`).join('');
  if (!currentFile && files.length) currentFile = files[0];
  fileSelect.value = currentFile || '';
  refreshDownload();
}

function refreshDownload() {
  if (!fileSelect.value) return;
  currentFile = fileSelect.value;
  downloadLink.href = `/download/${encodeURIComponent(currentFile)}`;
}

fileSelect.addEventListener('change', async () => {
  refreshDownload();
  const res = await fetch(`/api/logs/${encodeURIComponent(fileSelect.value)}`);
  const data = await res.json();
  logbox.textContent = (data.lines || []).join('\n');
  logbox.scrollTop = logbox.scrollHeight;
});

async function bootstrap() {
  const status = await fetch('/api/status').then(r => r.json());
  renderStatus(status);
  const logs = await fetch('/api/logs').then(r => r.json());
  logbox.textContent = (logs.lines || []).join('\n');
  logbox.scrollTop = logbox.scrollHeight;
}

function connectStream() {
  const es = new EventSource('/stream');
  es.onopen = () => { streamBadge.textContent = 'live'; streamBadge.className = 'badge ok'; };
  es.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    logbox.textContent += (logbox.textContent ? '\n' : '') + payload.line;
    logbox.scrollTop = logbox.scrollHeight;
  };
  es.onerror = () => {
    streamBadge.textContent = 'reconnecting';
    streamBadge.className = 'badge warn';
  };
}

setInterval(async () => {
  const status = await fetch('/api/status').then(r => r.json());
  renderStatus(status);
}, 10000);

bootstrap();
connectStream();
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
