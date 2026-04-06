from flask import Flask, jsonify
import os
import threading

app = Flask(__name__)

_engine_thread = None
_engine_started = False
_engine_error = None


def _engine_target():
    global _engine_error
    try:
        from engine import run_engine_forever
        run_engine_forever()
    except BaseException as e:
        _engine_error = repr(e)
        raise


def ensure_engine_started():
    global _engine_thread, _engine_started
    if _engine_started:
        return
    _engine_started = True
    _engine_thread = threading.Thread(target=_engine_target, name="telegram-log-engine", daemon=True)
    _engine_thread.start()


@app.before_request
def _boot_engine_once():
    if os.getenv("RAILWAY_RUN_ENGINE", "true").lower() == "true":
        ensure_engine_started()


@app.get("/")
def root():
    alive = bool(_engine_thread and _engine_thread.is_alive())
    return jsonify({
        "status": "ok",
        "service": "telegram_log_engine_v10_0_1",
        "engine_thread_alive": alive,
        "engine_started": _engine_started,
        "engine_error": _engine_error,
        "mode": "railway_safe_web_health",
    })


@app.get("/health")
def health():
    alive = bool(_engine_thread and _engine_thread.is_alive()) if _engine_started else False
    healthy = alive or (_engine_started is False and os.getenv("RAILWAY_RUN_ENGINE", "true").lower() != "true")
    status_code = 200 if healthy else 503
    payload = {
        "status": "healthy" if healthy else "starting",
        "engine_thread_alive": alive,
        "engine_started": _engine_started,
        "engine_error": _engine_error,
    }
    return jsonify(payload), status_code


if os.getenv("RAILWAY_RUN_ENGINE", "true").lower() == "true":
    ensure_engine_started()

if __name__ == "__main__":
    ensure_engine_started()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
