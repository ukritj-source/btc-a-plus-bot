from flask import Flask, jsonify
app = Flask(__name__)

@app.get("/")
def health():
    return jsonify({"status": "dashboard_removed", "mode": "telegram_log_engine_v10"})
