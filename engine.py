# -*- coding: utf-8 -*-
"""
BTC A+ V9.1 EARLY EXPANSION / SHORT SQUEEZE SYNC ENGINE — STRICT / BALANCED + Fake Pump/Dump
ต่อยอดจาก V7.0 โดยปรับ:
1) Commit จริง = ไม่ใช่แค่เด้ง แต่ต้องมี "แรงตาม"
2) ใช้ 3 ด่านก่อนเข้า:
   - OI COMMIT
   - PREMIUM COMMIT
   - HOLD / PULLBACK HOLD
3) แยกสถานะ:
   - มีสัญญาณ
   - ยังไม่ commit
   - commit แล้ว เข้าได้
4) ใช้คำอ่านง่ายแบบภาคสนาม
5) ยังเป็นระบบวิเคราะห์ + แจ้งเตือน ไม่ส่งออเดอร์จริง
6) จัดลำดับ debug ใหม่ = Context → Signal → Confirmation → Execution
7) เพิ่ม FINAL VERDICT + QUICK TAKE สำหรับอ่านเร็ว
8) เพิ่ม grading framework = A+ / A / WATCHLIST / NO TRADE
9) เพิ่ม Fake Pump / Fake Dump Detector เพื่อกันการ short/long เร็วเกินไป
10) เพิ่ม STRICT / BALANCED MODE เพื่อผ่อนความเข้มโดยไม่ทำลายแกนระบบ
11) เพิ่ม Early Expansion Detector = เห็นแรงเร่งต้นทางก่อน breakout/short squeeze เต็มตัว
12) เพิ่ม Short Squeeze Sync Engine = จับจังหวะที่แรงเด้ง + orderbook + premium + reclaim sync กัน
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import UTC, datetime

import requests

# ================= FILE LOG TEE =================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
LOG_DIR = Path(os.getenv("LOG_DIR", DATA_DIR / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _daily_log_path() -> Path:
    return LOG_DIR / f"{datetime.utcnow().strftime('%Y-%m-%d')}.log"


class _LineBufferedTee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass
        return len(data)

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


def setup_file_logging():
    try:
        logfile = _daily_log_path().open("a", encoding="utf-8", buffering=1)
        sys.stdout = _LineBufferedTee(sys.__stdout__, logfile)
        sys.stderr = _LineBufferedTee(sys.__stderr__, logfile)
        print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] file logging ready: {logfile.name}")
    except Exception as e:
        print(f"file logging setup error: {e}")


# ================= CONFIG =================
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
HTF_INTERVAL = "1h"

KLINE_LIMIT = 260
SLEEP = 20

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

EMA_FAST, EMA_MID, EMA_SLOW = 20, 50, 200
ATR_PERIOD = 14

SHORT_OB_MAX = 0.48
LONG_OB_MIN = 0.52

OI_SPIKE = 0.10
PREMIUM_SHORT = -0.001
PREMIUM_LONG = 0.001

TIMEZONE_OFFSET = 7
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
TELEGRAM_COOLDOWN_SEC = 60 * 10

ENABLE_LIVE_OPEN_CANDLE_LOG = True
LIVE_STATE_CONFIRM_TICKS = 3
LIVE_STATE_CHANGE_COOLDOWN_SEC = 20
LIVE_SIGNAL_MIN_SCORE = 4
LIVE_ALERT_IF_ABNORMAL = True
LIVE_ABNORMAL_OB_SHORT = 0.60
LIVE_ABNORMAL_OB_LONG = 0.40

PHASE_HOLD_SECONDS = 90
PHASE_FLIP_MIN_CONFIDENCE = 65
INTENT_HOLD_SECONDS = 180
INTENT_CONFIRM_TICKS = 2
INTENT_SHIFT_MIN_DELTA = 10
EARLY_BREAK_ATR_PCT = 0.12
EARLY_BREAK_OB_SHORT = 0.40
EARLY_BREAK_OB_LONG = 0.60
EARLY_BREAK_PREMIUM_SHORT = -0.00015
EARLY_BREAK_PREMIUM_LONG = 0.00015

SMASH_RANGE_ATR_MULT = 1.60
SMASH_BODY_PCT = 0.60
SMASH_OI_SHORT = -0.08
SMASH_OI_LONG = 0.08
SMASH_PREMIUM_SHORT = -0.00035
SMASH_PREMIUM_LONG = 0.00035

PROBABLE_SMASH_MOMENTUM = 60
PROBABLE_SMASH_OB_SHORT = 0.38
PROBABLE_SMASH_OB_LONG = 0.62
PROBABLE_SMASH_PREMIUM_SHORT = -0.00020
PROBABLE_SMASH_PREMIUM_LONG = 0.00020
PROBE_ENTRY_MIN_PROB = 46

DISTRIBUTION_NEAR_EMA_ATR = 0.35
DISTRIBUTION_WICK_PCT = 0.28
DISTRIBUTION_PROBE_MIN_PROB = 34
DISTRIBUTION_MAX_OI = 0.06
DISTRIBUTION_PREMIUM_SHORT_MAX = 0.00015
DISTRIBUTION_PREMIUM_LONG_MIN = -0.00015

A_PLUS_ONLY_MODE = True
TRUE_COMMIT_REQUIRE_BREAK = True
TRUE_COMMIT_REQUIRE_TRIGGER_TOUCH = True
TRUE_COMMIT_REQUIRE_ORDERBOOK = True
TRUE_COMMIT_REQUIRE_OI = True
TRUE_COMMIT_REQUIRE_PREMIUM = True


STATE_FILE = os.getenv("STATE_FILE", "btc_a_plus_v9_1_early_expansion_short_squeeze_sync_engine_state.json")
STATE_SAVE_DEBOUNCE_SEC = 2

ENABLE_TRAP_ALERT = True
ENABLE_REVERSAL_ALERT = True
ENABLE_AUTO_ENTRY_ALERT = True
ENABLE_A_PLUS_ALERT = True

ENABLE_TELEGRAM_LIVE_LOG = os.getenv("ENABLE_TELEGRAM_LIVE_LOG", "true").lower() == "true"
ENABLE_TELEGRAM_FAKE_MOVE_ALERT = os.getenv("ENABLE_TELEGRAM_FAKE_MOVE_ALERT", "true").lower() == "true"
ENABLE_TELEGRAM_SMASH_ALERT = os.getenv("ENABLE_TELEGRAM_SMASH_ALERT", "true").lower() == "true"
ENABLE_TELEGRAM_PROBE_ALERT = os.getenv("ENABLE_TELEGRAM_PROBE_ALERT", "false").lower() == "true"
LIVE_SUMMARY_MIN_SECONDS = int(os.getenv("LIVE_SUMMARY_MIN_SECONDS", "180"))

BIAS_FLIP_RESET_ON_CLOSED = True
BIAS_FLIP_CONFIRM_BARS = 2
TRAP_MEMORY_TTL_EXTRA = 4

ENTRY_SL_ATR = 0.8
ENTRY_TP1_ATR = 1.0
ENTRY_TP2_ATR = 1.8
MIN_RR_FOR_ENTRY = 1.2

# HARD LOCK
ENTRY_FILTER_MIN_PROB = 68
ENTRY_FILTER_REQUIRE_TRIGGER_TOUCH = True
ENTRY_FILTER_REQUIRE_ORDERBOOK = True
ENTRY_FILTER_REQUIRE_OI = True
ENTRY_FILTER_REQUIRE_PREMIUM = True

# SETUP GRADING
GRADE_A_PLUS_MIN = 68
GRADE_A_MIN = 56
GRADE_WATCH_MIN = 40

# EARLY ENTRY / TRAP EXPLOIT
EARLY_ENTRY_MIN_PROB = 52
TRAP_EXPLOIT_MIN_PROB = 48
EARLY_ENTRY_MAX_RISK_TAG = "SMALL SIZE"

# Fake move detector
FAKE_PUMP_BODY_PCT = 0.45
FAKE_PUMP_OB_MIN = 0.60
FAKE_PUMP_OI_MAX = 0.05
FAKE_PUMP_PREMIUM_MAX = 0.00020
FAKE_PUMP_EXT_ATR = 0.18

FAKE_DUMP_BODY_PCT = 0.45
FAKE_DUMP_OB_MAX = 0.40
FAKE_DUMP_OI_MAX = 0.05
FAKE_DUMP_PREMIUM_MIN = -0.00020
FAKE_DUMP_EXT_ATR = 0.18

# V9 Fake Dump -> Auto Flip Bias -> Long Setup
FAKE_DUMP_FLIP_MIN_OB = 0.56
FAKE_DUMP_FLIP_MIN_LONG_MOM = 36
FAKE_DUMP_FLIP_MAX_SHORT_MOM = 28
FAKE_DUMP_FLIP_MAX_NEG_OI = -0.03
FAKE_DUMP_FLIP_PREMIUM_RECOVER = -0.00065
FAKE_DUMP_FLIP_RECLAIM_ATR = 0.10
FAKE_DUMP_FLIP_ENTRY_PROB = 52

# V9.1 Early Expansion / Short Squeeze Sync
EARLY_EXPANSION_BODY_PCT = 0.38
EARLY_EXPANSION_RANGE_ATR = 0.85
EARLY_EXPANSION_CLOSE_POS_LONG = 0.62
EARLY_EXPANSION_OB_LONG = 0.54
EARLY_EXPANSION_PREMIUM_LONG = -0.00005
EARLY_EXPANSION_MIN_LONG_MOM = 34
EARLY_EXPANSION_RECLAIM_BUFFER_ATR = 0.04

SHORT_SQUEEZE_OB_LONG = 0.58
SHORT_SQUEEZE_PREMIUM_LONG = -0.00005
SHORT_SQUEEZE_MAX_OI = 0.02
SHORT_SQUEEZE_MIN_LONG_MOM = 42
SHORT_SQUEEZE_MIN_SCORE = 4
SHORT_SQUEEZE_ENTRY_PROB = 56

# MODE PROFILES
MODE_PROFILE = "STRICT"  # STRICT | BALANCED

MODE_PROFILES = {
    "STRICT": {
        "OI_SPIKE": 0.10,
        "PREMIUM_SHORT": -0.0010,
        "PREMIUM_LONG": 0.0010,
        "ENTRY_FILTER_MIN_PROB": 68,
        "ENTRY_FILTER_REQUIRE_ORDERBOOK": True,
        "ENTRY_FILTER_REQUIRE_OI": True,
        "ENTRY_FILTER_REQUIRE_PREMIUM": True,
        "COMMIT_OI_LONG": 0.02,
        "COMMIT_OI_SHORT": -0.02,
        "COMMIT_PREMIUM_LONG": -0.00005,
        "COMMIT_PREMIUM_SHORT": 0.00005,
        "GRADE_A_PLUS_MIN": 68,
        "GRADE_A_MIN": 56,
        "GRADE_WATCH_MIN": 40,
    },
    "BALANCED": {
        "OI_SPIKE": 0.05,
        "PREMIUM_SHORT": -0.0006,
        "PREMIUM_LONG": 0.0006,
        "ENTRY_FILTER_MIN_PROB": 60,
        "ENTRY_FILTER_REQUIRE_ORDERBOOK": False,
        "ENTRY_FILTER_REQUIRE_OI": True,
        "ENTRY_FILTER_REQUIRE_PREMIUM": True,
        "COMMIT_OI_LONG": 0.01,
        "COMMIT_OI_SHORT": -0.01,
        "COMMIT_PREMIUM_LONG": -0.00002,
        "COMMIT_PREMIUM_SHORT": 0.00002,
        "GRADE_A_PLUS_MIN": 60,
        "GRADE_A_MIN": 50,
        "GRADE_WATCH_MIN": 34,
    },
}


def apply_mode_profile(mode_name: str):
    global MODE_PROFILE
    global OI_SPIKE, PREMIUM_SHORT, PREMIUM_LONG
    global ENTRY_FILTER_MIN_PROB, ENTRY_FILTER_REQUIRE_ORDERBOOK, ENTRY_FILTER_REQUIRE_OI, ENTRY_FILTER_REQUIRE_PREMIUM
    global COMMIT_OI_LONG, COMMIT_OI_SHORT, COMMIT_PREMIUM_LONG, COMMIT_PREMIUM_SHORT
    global GRADE_A_PLUS_MIN, GRADE_A_MIN, GRADE_WATCH_MIN

    mode = (mode_name or "STRICT").upper()
    if mode not in MODE_PROFILES:
        print(f"[{now()}] Unknown MODE_PROFILE={mode_name} -> fallback STRICT")
        mode = "STRICT"

    cfg = MODE_PROFILES[mode]
    MODE_PROFILE = mode
    OI_SPIKE = cfg["OI_SPIKE"]
    PREMIUM_SHORT = cfg["PREMIUM_SHORT"]
    PREMIUM_LONG = cfg["PREMIUM_LONG"]
    ENTRY_FILTER_MIN_PROB = cfg["ENTRY_FILTER_MIN_PROB"]
    ENTRY_FILTER_REQUIRE_ORDERBOOK = cfg["ENTRY_FILTER_REQUIRE_ORDERBOOK"]
    ENTRY_FILTER_REQUIRE_OI = cfg["ENTRY_FILTER_REQUIRE_OI"]
    ENTRY_FILTER_REQUIRE_PREMIUM = cfg["ENTRY_FILTER_REQUIRE_PREMIUM"]
    COMMIT_OI_LONG = cfg["COMMIT_OI_LONG"]
    COMMIT_OI_SHORT = cfg["COMMIT_OI_SHORT"]
    COMMIT_PREMIUM_LONG = cfg["COMMIT_PREMIUM_LONG"]
    COMMIT_PREMIUM_SHORT = cfg["COMMIT_PREMIUM_SHORT"]
    GRADE_A_PLUS_MIN = cfg["GRADE_A_PLUS_MIN"]
    GRADE_A_MIN = cfg["GRADE_A_MIN"]
    GRADE_WATCH_MIN = cfg["GRADE_WATCH_MIN"]


def mode_summary_text():
    return (
        f"mode={MODE_PROFILE} | oi_spike={OI_SPIKE:.2f} | premium=({PREMIUM_SHORT:.4f},{PREMIUM_LONG:.4f}) | "
        f"entry_prob>={ENTRY_FILTER_MIN_PROB} | require_ob={ENTRY_FILTER_REQUIRE_ORDERBOOK}"
    )

# Smart Money Entry Timing
PULLBACK_ATR_PCT = 0.25
OI_SHIFT_POSITIVE = 0.02
PREMIUM_RECOVER_LONG = -0.00015
PREMIUM_RECOVER_SHORT = 0.00015

# Commit จริง
COMMIT_OI_LONG = 0.02
COMMIT_OI_SHORT = -0.02
COMMIT_PREMIUM_LONG = -0.00005
COMMIT_PREMIUM_SHORT = 0.00005
COMMIT_PULLBACK_HOLD_ATR = 0.18

# Trap thresholds
TRAP_OI_STRONG = 0.25
TRAP_OI_VERY_STRONG = 0.80
TRAP_PREMIUM_WEAK_SHORT = -0.0007
TRAP_PREMIUM_WEAK_LONG = 0.0007
TRAP_REJECTION_BODY_PCT = 0.35
TRAP_WICK_PCT = 0.40
TRAP_DISTANCE_ATR = 0.20
TRAP_BOOK_OPPOSITE_SHORT = 0.58
TRAP_BOOK_OPPOSITE_LONG = 0.42

# Reversal thresholds
REVERSAL_BOOK_LONG = 0.56
REVERSAL_BOOK_SHORT = 0.44
REVERSAL_PREMIUM_LONG = -0.0002
REVERSAL_PREMIUM_SHORT = 0.0002

# Auto entry thresholds
POST_TRAP_BOOK_LONG = 0.54
POST_TRAP_BOOK_SHORT = 0.46
POST_TRAP_PREMIUM_LONG = -0.0001
POST_TRAP_PREMIUM_SHORT = 0.0001
POST_TRAP_MIN_BODY_PCT = 0.45
POST_TRAP_CLOSE_BUFFER_ATR = 0.05
POST_TRAP_MAX_WAIT_CANDLES = 4

session = requests.Session()
BASE = "https://fapi.binance.com"

_last_alert_key = None
_last_alert_ts = 0
_last_closed_candle_logged = None
_last_live_log_ts = 0
_last_live_state_signature = None
_last_live_state_print_ts = 0
_live_candidate_state_signature = None
_live_candidate_state_count = 0
_startup_telegram_test_done = False
_last_live_summary_ts = 0.0
_last_state_save_ts = 0

_last_short_trap = None
_last_long_trap = None
_last_short_reversal = None
_last_long_reversal = None
_last_bias_side = None
_last_bias_change_time = None

_last_stable_live_phase = None
_last_stable_live_phase_ts = 0
_live_candidate_phase = None
_live_candidate_phase_count = 0
_last_intent = None
_last_intent_ts = 0
_intent_candidate = None
_intent_candidate_count = 0


# ================= TIME =================
def ts_to_str(ts: int) -> str:
    return datetime.fromtimestamp(ts + TIMEZONE_OFFSET * 3600, UTC).strftime("%Y-%m-%d %H:%M:%S")


def now() -> str:
    return ts_to_str(int(time.time()))


# ================= PERSISTENCE =================
def _safe_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _clean_memory_dict(d):
    if not isinstance(d, dict):
        return None
    cleaned = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            cleaned[k] = v
        elif isinstance(v, list):
            cleaned[k] = [x for x in v if isinstance(x, (str, int, float, bool)) or x is None]
        elif isinstance(v, dict):
            nested = {}
            for nk, nv in v.items():
                if isinstance(nv, (str, int, float, bool)) or nv is None:
                    nested[nk] = nv
            cleaned[k] = nested
    return cleaned


def save_state(force=False):
    global _last_state_save_ts
    now_ts = time.time()
    if not force and (now_ts - _last_state_save_ts) < STATE_SAVE_DEBOUNCE_SEC:
        return
    state = {
        "saved_at": int(now_ts),
        "last_alert_key": _last_alert_key,
        "last_alert_ts": _safe_int(_last_alert_ts, 0),
        "last_closed_candle_logged": _safe_int(_last_closed_candle_logged),
        "last_live_log_ts": _safe_int(_last_live_log_ts, 0),
        "last_live_state_signature": _last_live_state_signature,
        "last_live_state_print_ts": _safe_int(_last_live_state_print_ts, 0),
        "live_candidate_state_signature": _live_candidate_state_signature,
        "live_candidate_state_count": _safe_int(_live_candidate_state_count, 0),
        "last_short_trap": _clean_memory_dict(_last_short_trap),
        "last_long_trap": _clean_memory_dict(_last_long_trap),
        "last_short_reversal": _clean_memory_dict(_last_short_reversal),
        "last_long_reversal": _clean_memory_dict(_last_long_reversal),
        "last_bias_side": _last_bias_side,
        "last_bias_change_time": _safe_int(_last_bias_change_time),
        "last_stable_live_phase": _last_stable_live_phase,
        "last_stable_live_phase_ts": _safe_int(_last_stable_live_phase_ts, 0),
        "live_candidate_phase": _live_candidate_phase,
        "live_candidate_phase_count": _safe_int(_live_candidate_phase_count, 0),
        "last_intent": _last_intent,
        "last_intent_ts": _safe_int(_last_intent_ts, 0),
        "intent_candidate": _intent_candidate,
        "intent_candidate_count": _safe_int(_intent_candidate_count, 0),
    }
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)
    _last_state_save_ts = now_ts


def load_state():
    global _last_alert_key, _last_alert_ts, _last_closed_candle_logged, _last_live_log_ts
    global _last_live_state_signature, _last_live_state_print_ts, _live_candidate_state_signature, _live_candidate_state_count
    global _last_short_trap, _last_long_trap, _last_short_reversal, _last_long_reversal
    global _last_bias_side, _last_bias_change_time
    global _last_stable_live_phase, _last_stable_live_phase_ts, _live_candidate_phase, _live_candidate_phase_count
    global _last_intent, _last_intent_ts, _intent_candidate, _intent_candidate_count

    if not os.path.exists(STATE_FILE):
        print(f"[{now()}] State file not found → start fresh")
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        _last_alert_key = state.get("last_alert_key")
        _last_alert_ts = _safe_int(state.get("last_alert_ts"), 0) or 0
        _last_closed_candle_logged = _safe_int(state.get("last_closed_candle_logged"))
        _last_live_log_ts = _safe_int(state.get("last_live_log_ts"), 0) or 0
        _last_live_state_signature = state.get("last_live_state_signature")
        _last_live_state_print_ts = _safe_int(state.get("last_live_state_print_ts"), 0) or 0
        _live_candidate_state_signature = state.get("live_candidate_state_signature")
        _live_candidate_state_count = _safe_int(state.get("live_candidate_state_count"), 0) or 0
        _last_short_trap = _clean_memory_dict(state.get("last_short_trap"))
        _last_long_trap = _clean_memory_dict(state.get("last_long_trap"))
        _last_short_reversal = _clean_memory_dict(state.get("last_short_reversal"))
        _last_long_reversal = _clean_memory_dict(state.get("last_long_reversal"))
        _last_bias_side = state.get("last_bias_side")
        _last_bias_change_time = _safe_int(state.get("last_bias_change_time"))
        _last_stable_live_phase = state.get("last_stable_live_phase")
        _last_stable_live_phase_ts = _safe_int(state.get("last_stable_live_phase_ts"), 0) or 0
        _live_candidate_phase = state.get("live_candidate_phase")
        _live_candidate_phase_count = _safe_int(state.get("live_candidate_phase_count"), 0) or 0
        _last_intent = state.get("last_intent")
        _last_intent_ts = _safe_int(state.get("last_intent_ts"), 0) or 0
        _intent_candidate = state.get("intent_candidate")
        _intent_candidate_count = _safe_int(state.get("intent_candidate_count"), 0) or 0
        saved_at = state.get("saved_at")
        saved_at_txt = ts_to_str(saved_at) if isinstance(saved_at, int) else "unknown"
        print(f"[{now()}] State restored from {STATE_FILE} | saved_at={saved_at_txt}")
    except Exception as e:
        print(f"[{now()}] State restore failed: {e} | start fresh")


# ================= FETCH =================
def safe_get_json(url: str, params: dict):
    r = session.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def klines_closed(interval):
    data = safe_get_json(BASE + "/fapi/v1/klines", {"symbol": SYMBOL, "interval": interval, "limit": KLINE_LIMIT})
    return [{
        "open_time": int(x[0]) // 1000,
        "close_time": int(x[6]) // 1000,
        "o": float(x[1]),
        "h": float(x[2]),
        "l": float(x[3]),
        "c": float(x[4]),
        "v": float(x[5]),
        "is_closed": True
    } for x in data[:-1]]


def latest_open_candle(interval):
    data = safe_get_json(BASE + "/fapi/v1/klines", {"symbol": SYMBOL, "interval": interval, "limit": 2})
    if not data:
        return None
    x = data[-1]
    return {
        "open_time": int(x[0]) // 1000,
        "close_time": int(x[6]) // 1000,
        "o": float(x[1]),
        "h": float(x[2]),
        "l": float(x[3]),
        "c": float(x[4]),
        "v": float(x[5]),
        "is_closed": False
    }


def orderbook():
    d = safe_get_json(BASE + "/fapi/v1/depth", {"symbol": SYMBOL, "limit": 50})
    bids = sum(float(x[1]) for x in d["bids"])
    asks = sum(float(x[1]) for x in d["asks"])
    return bids / (bids + asks) if bids + asks else 0.5


def oi():
    d = safe_get_json(BASE + "/futures/data/openInterestHist", {"symbol": SYMBOL, "period": "5m", "limit": 3})
    if len(d) < 2:
        return None
    a = float(d[-2]["sumOpenInterest"])
    b = float(d[-1]["sumOpenInterest"])
    return (b - a) / a * 100 if a else None


def premium():
    d = safe_get_json(BASE + "/fapi/v1/premiumIndexKlines", {"symbol": SYMBOL, "interval": "15m", "limit": 2})
    return float(d[-1][4]) if d else None


# ================= INDICATORS =================
def ema(values, n):
    k = 2 / (n + 1)
    e = values[0]
    out = []
    for x in values:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def atr(candles):
    if len(candles) < ATR_PERIOD + 1:
        return None
    tr = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr[-ATR_PERIOD:]) / ATR_PERIOD if len(tr) >= ATR_PERIOD else None


# ================= TELEGRAM =================
def can_send_alert(alert_key: str) -> bool:
    global _last_alert_key, _last_alert_ts
    now_ts = time.time()
    if _last_alert_key == alert_key and (now_ts - _last_alert_ts) < TELEGRAM_COOLDOWN_SEC:
        return False
    _last_alert_key = alert_key
    _last_alert_ts = now_ts
    save_state()
    return True


def send_telegram(msg: str):
    if not ENABLE_TELEGRAM:
        return False
    try:
        r = session.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=15
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{now()}] Telegram send error: {e}")
        return False


def startup_telegram_test():
    global _startup_telegram_test_done
    if _startup_telegram_test_done:
        return
    _startup_telegram_test_done = True
    ok = send_telegram(
        f"✅ BTC bot startup test\nsymbol: {SYMBOL}\ninterval: {INTERVAL}\ntime: {now()}\nstatus: telegram connection test"
    )
    print(f"[{now()}] Telegram startup test: {'OK' if ok else 'FAILED'}")


# ================= FORMAT =================
def fmt_price(x):
    return "n/a" if x is None else f"{x:,.2f}"


def fmt_pct(x, digits=3):
    return "n/a" if x is None else f"{x:.{digits}f}%"


def fmt_num(x, digits=6):
    return "n/a" if x is None else f"{x:.{digits}f}"


def fmt_rr(x):
    return "n/a" if x is None else f"{x:.2f}"


def passfail(v):
    return "PASS" if v else "FAIL"


def compact_reason(checks):
    order = ["trend", "htf", "break", "orderbook", "oi", "premium"]
    good = [k for k in order if checks.get(k)]
    bad = [k for k in order if not checks.get(k)]
    return f"ผ่าน: {', '.join(good) if good else '-'} | ไม่ผ่าน: {', '.join(bad) if bad else '-'}"


# ================= CANDLE HELPERS =================
def candle_range(c):
    return c["h"] - c["l"]


def candle_body(c):
    return abs(c["c"] - c["o"])


def body_pct(c):
    r = candle_range(c)
    return (candle_body(c) / r) if r > 0 else 0.0


def upper_wick_pct(c):
    r = candle_range(c)
    top = max(c["o"], c["c"])
    return ((c["h"] - top) / r) if r > 0 else 0.0


def lower_wick_pct(c):
    r = candle_range(c)
    bot = min(c["o"], c["c"])
    return ((bot - c["l"]) / r) if r > 0 else 0.0


def close_position_pct(c):
    r = candle_range(c)
    return ((c["c"] - c["l"]) / r) if r > 0 else 0.5


def dist_to_level(price, level):
    return abs(price - level)


# ================= MARKET LABELS =================
def signal_quality(checks):
    score = sum(1 for v in checks.values() if bool(v))
    if score == 6:
        return "A+"
    if score >= 5:
        return "VERY CLOSE"
    if score >= 4:
        return "CLOSE"
    if score >= 3:
        return "WATCH"
    return "NO TRADE"


def setup_grade(side, checks, traps, reversal=None, auto_entry=None, entry_filter=None, commit_info=None,
                ob=None, oi_v=None, prem=None, fake_move=None, early_entry=None, trap_exploit=None,
                expansion_long=None, squeeze_sync=None):
    prob = probability_score(side, checks, traps, reversal, auto_entry, ob, oi_v, prem)
    hard_ready = bool(auto_entry and entry_filter and entry_filter.get("passed") and commit_info and commit_info.get("commit"))

    if hard_ready:
        return "A+", prob
    if fake_move and fake_move.get("active"):
        return "NO TRADE", prob
    if auto_entry and entry_filter and entry_filter.get("passed"):
        return "A", prob
    if squeeze_sync and squeeze_sync.get("active") and prob >= SHORT_SQUEEZE_ENTRY_PROB:
        return "A", prob
    if expansion_long and expansion_long.get("active") and prob >= EARLY_ENTRY_MIN_PROB:
        return "WATCHLIST", prob
    if early_entry and early_entry.get("active"):
        return "A", prob
    if trap_exploit and trap_exploit.get("active"):
        return "WATCHLIST", prob
    if reversal and prob >= GRADE_A_MIN:
        return "A", prob
    if not traps and prob >= GRADE_A_MIN and sum(1 for v in checks.values() if v) >= 4:
        return "A", prob
    if prob >= GRADE_WATCH_MIN or signal_quality(checks) in {"WATCH", "CLOSE", "VERY CLOSE"} or traps:
        return "WATCHLIST", prob
    return "NO TRADE", prob



def detect_early_entry(side, checks, reversal=None, auto_entry=None, traps=None, prob=None):
    traps = traps or []
    if auto_entry:
        return None
    structure_ok = bool(checks.get("trend") and checks.get("htf"))
    pressure_count = sum(1 for k in ["orderbook", "oi", "premium"] if checks.get(k))
    if structure_ok and pressure_count >= 2 and prob is not None and prob >= EARLY_ENTRY_MIN_PROB:
        return {
            "active": True,
            "side": side,
            "label": f"EARLY ENTRY {side}",
            "reason": "structure มาแล้ว + pressure เริ่มหนุน แต่ยังไม่ถึง auto-entry",
            "risk_tag": EARLY_ENTRY_MAX_RISK_TAG,
        }
    if reversal and prob is not None and prob >= EARLY_ENTRY_MIN_PROB:
        return {
            "active": True,
            "side": reversal["side"],
            "label": f"EARLY ENTRY {reversal['side']}",
            "reason": "reversal เริ่มชัด แต่ยังไม่ถึง commit เต็มตัว",
            "risk_tag": EARLY_ENTRY_MAX_RISK_TAG,
        }
    return None


def detect_trap_exploit(side, traps, reversal=None, prob=None):
    traps = traps or []
    if reversal and prob is not None and prob >= TRAP_EXPLOIT_MIN_PROB:
        return {
            "active": True,
            "side": reversal["side"],
            "label": f"TRAP EXPLOIT {reversal['side']}",
            "reason": "มี trap + reversal เริ่มเฉลยทาง",
            "risk_tag": "CONFIRM THEN SMALL SIZE",
        }
    if traps and len(traps) >= 2 and prob is not None and prob >= TRAP_EXPLOIT_MIN_PROB:
        exploit_side = "LONG" if side == "SHORT" else "SHORT"
        return {
            "active": True,
            "side": exploit_side,
            "label": f"TRAP EXPLOIT {exploit_side}",
            "reason": "trap เริ่มชัด กำลังมองหา reclaim/reject เพื่อสวนฝั่งที่โดนหลอก",
            "risk_tag": "WAIT CONFIRM",
        }
    return None


def detect_fake_pump(cur, prev, atr_v, ob, oi_v, prem, trend_l, htf_s):
    if not htf_s:
        return None

    reasons = []
    up_break = cur["h"] > prev["h"] or cur["c"] > prev["h"]
    green_body = cur["c"] > cur["o"] and body_pct(cur) >= FAKE_PUMP_BODY_PCT
    buyer_push = ob is not None and ob >= FAKE_PUMP_OB_MIN
    oi_weak = oi_v is None or oi_v <= FAKE_PUMP_OI_MAX
    premium_not_real = prem is None or prem <= FAKE_PUMP_PREMIUM_MAX
    ext_ok = atr_v is not None and (cur["h"] - prev["h"]) >= atr_v * FAKE_PUMP_EXT_ATR
    trend_not_long = not trend_l

    if up_break:
        reasons.append("price pushed above prior high")
    if green_body:
        reasons.append("strong green candle")
    if buyer_push:
        reasons.append("buyer pressure visible")
    if oi_weak:
        reasons.append("OI not confirming breakout")
    if premium_not_real:
        reasons.append("premium not confirming long")
    if ext_ok:
        reasons.append("price stretched up fast")
    if trend_not_long:
        reasons.append("LTF trend still not long")

    weak_commit_count = sum([oi_weak, premium_not_real, trend_not_long])
    if up_break and buyer_push and weak_commit_count >= 2 and (green_body or ext_ok):
        return {
            "type": "FAKE PUMP RISK",
            "label": "ขึ้นแรง แต่ยังไม่ใช่ long commitment",
            "reasons": reasons,
            "warning": "อย่าเพิ่ง short สวนทันที รอ rejection / break ลงก่อน",
        }
    return None


def detect_fake_dump(cur, prev, atr_v, ob, oi_v, prem, trend_s, htf_l):
    if not htf_l:
        return None

    reasons = []
    down_break = cur["l"] < prev["l"] or cur["c"] < prev["l"]
    red_body = cur["c"] < cur["o"] and body_pct(cur) >= FAKE_DUMP_BODY_PCT
    seller_push = ob is not None and ob <= FAKE_DUMP_OB_MAX
    oi_weak = oi_v is None or oi_v <= FAKE_DUMP_OI_MAX
    premium_not_real = prem is None or prem >= FAKE_DUMP_PREMIUM_MIN
    ext_ok = atr_v is not None and (prev["l"] - cur["l"]) >= atr_v * FAKE_DUMP_EXT_ATR
    trend_not_short = not trend_s

    if down_break:
        reasons.append("price pushed below prior low")
    if red_body:
        reasons.append("strong red candle")
    if seller_push:
        reasons.append("seller pressure visible")
    if oi_weak:
        reasons.append("OI not confirming breakdown")
    if premium_not_real:
        reasons.append("premium not confirming short")
    if ext_ok:
        reasons.append("price stretched down fast")
    if trend_not_short:
        reasons.append("LTF trend still not short")

    weak_commit_count = sum([oi_weak, premium_not_real, trend_not_short])
    if down_break and seller_push and weak_commit_count >= 2 and (red_body or ext_ok):
        return {
            "type": "FAKE DUMP RISK",
            "label": "ลงแรง แต่ยังไม่ใช่ short commitment",
            "reasons": reasons,
            "warning": "อย่าเพิ่ง long สวนทันที รอ reclaim / break ขึ้นก่อน",
        }
    return None


def detect_fake_dump_flip_long_setup(cur, prev, ob, oi_v, prem, atr_v, fake_move=None, checks_long=None):
    checks_long = checks_long or {}
    if not fake_move or not fake_move.get("active") or fake_move.get("type") != "FAKE DUMP":
        return None

    long_mom, short_mom = compute_intent_momentum(cur, prev, checks_long, ob, oi_v, prem, atr_v, fake_move)
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    reclaim_level = max(prev["h"], cur["l"] + atr_ref * FAKE_DUMP_FLIP_RECLAIM_ATR)

    reasons = []
    if ob is not None and ob >= FAKE_DUMP_FLIP_MIN_OB:
        reasons.append("buyer reclaimed orderbook")
    if oi_v is not None and oi_v >= FAKE_DUMP_FLIP_MAX_NEG_OI:
        reasons.append("OI not supporting downside")
    if prem is not None and prem >= FAKE_DUMP_FLIP_PREMIUM_RECOVER:
        reasons.append("premium recovered from dump")
    if long_mom >= FAKE_DUMP_FLIP_MIN_LONG_MOM:
        reasons.append("long momentum expanding")
    if short_mom <= FAKE_DUMP_FLIP_MAX_SHORT_MOM:
        reasons.append("short momentum fading")
    if cur["c"] >= reclaim_level:
        reasons.append("price reclaimed from sweep zone")

    if len(reasons) >= 4:
        return {
            "active": True,
            "side": "LONG",
            "label": "FAKE DUMP -> AUTO FLIP LONG",
            "reasons": reasons,
            "entry_hint": f"watch LONG, reclaim above {fmt_price(reclaim_level)}",
            "reclaim_level": reclaim_level,
        }
    return None


def detect_early_expansion_long(cur, prev, ob, oi_v, prem, atr_v, checks_long=None, fake_move=None, reversal=None):
    checks_long = checks_long or {}
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    rng = cur["h"] - cur["l"]
    body_ok = body_pct(cur) >= EARLY_EXPANSION_BODY_PCT
    range_ok = rng >= atr_ref * EARLY_EXPANSION_RANGE_ATR
    close_ok = close_position_pct(cur) >= EARLY_EXPANSION_CLOSE_POS_LONG
    ob_ok = ob is not None and ob >= EARLY_EXPANSION_OB_LONG
    prem_ok = prem is not None and prem >= EARLY_EXPANSION_PREMIUM_LONG
    reclaim_level = prev["l"] + atr_ref * EARLY_EXPANSION_RECLAIM_BUFFER_ATR
    reclaim_ok = cur["c"] >= reclaim_level

    long_mom, short_mom = compute_intent_momentum(cur, prev, checks_long, ob, oi_v, prem, atr_v, fake_move)
    trigger_ctx = bool(
        (fake_move and fake_move.get("active") and fake_move.get("type") == "FAKE DUMP")
        or (reversal and reversal.get("side") == "LONG")
        or checks_long.get("htf")
    )

    reasons = []
    if trigger_ctx:
        reasons.append("context supports long expansion")
    if range_ok:
        reasons.append("range started expanding")
    if body_ok:
        reasons.append("body expansion visible")
    if close_ok:
        reasons.append("close holds near high")
    if ob_ok:
        reasons.append("buyer pressure improving")
    if prem_ok:
        reasons.append("premium no longer weak")
    if reclaim_ok:
        reasons.append("price reclaimed off the sweep")
    if long_mom >= EARLY_EXPANSION_MIN_LONG_MOM:
        reasons.append("long momentum building")
    if short_mom <= FAKE_DUMP_FLIP_MAX_SHORT_MOM:
        reasons.append("short momentum fading")

    core = sum([range_ok, body_ok, close_ok, ob_ok, prem_ok, reclaim_ok, long_mom >= EARLY_EXPANSION_MIN_LONG_MOM])
    if trigger_ctx and core >= 5:
        return {
            "active": True,
            "side": "LONG",
            "label": "EARLY EXPANSION LONG",
            "reasons": reasons,
            "entry_hint": f"watch LONG, hold above {fmt_price(reclaim_level)}",
            "reclaim_level": reclaim_level,
            "long_mom": long_mom,
            "short_mom": short_mom,
        }
    return None


def detect_short_squeeze_sync(cur, prev, ob, oi_v, prem, atr_v, fake_move=None, checks_long=None, reversal=None, expansion_long=None):
    checks_long = checks_long or {}
    long_mom, short_mom = compute_intent_momentum(cur, prev, checks_long, ob, oi_v, prem, atr_v, fake_move)
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    reclaim_level = max(prev["h"], prev["c"] + atr_ref * EARLY_EXPANSION_RECLAIM_BUFFER_ATR)

    score = 0
    reasons = []

    if fake_move and fake_move.get("active") and fake_move.get("type") == "FAKE DUMP":
        score += 1
        reasons.append("came from fake dump")
    if reversal and reversal.get("side") == "LONG":
        score += 1
        reasons.append("reversal already active")
    if expansion_long and expansion_long.get("active"):
        score += 1
        reasons.append("early expansion already on")
    if ob is not None and ob >= SHORT_SQUEEZE_OB_LONG:
        score += 1
        reasons.append("buyer control on book")
    if prem is not None and prem >= SHORT_SQUEEZE_PREMIUM_LONG:
        score += 1
        reasons.append("premium recovered enough")
    if oi_v is not None and oi_v <= SHORT_SQUEEZE_MAX_OI:
        score += 1
        reasons.append("looks like short cover, not crowded fresh longs")
    if cur["c"] >= reclaim_level:
        score += 1
        reasons.append("price reclaimed squeeze trigger")
    if long_mom >= SHORT_SQUEEZE_MIN_LONG_MOM:
        score += 1
        reasons.append("long momentum expanded")
    if short_mom <= FAKE_DUMP_FLIP_MAX_SHORT_MOM:
        score += 1
        reasons.append("short momentum faded")

    if score >= SHORT_SQUEEZE_MIN_SCORE and long_mom >= SHORT_SQUEEZE_MIN_LONG_MOM:
        return {
            "active": True,
            "side": "LONG",
            "label": "SHORT SQUEEZE SYNC LONG",
            "reasons": reasons,
            "entry_hint": f"watch LONG, reclaim/hold above {fmt_price(reclaim_level)}",
            "reclaim_level": reclaim_level,
            "score": score,
            "long_mom": long_mom,
            "short_mom": short_mom,
        }
    return None


def market_bias_text(trend_s, trend_l, htf_s, htf_l):
    if trend_s and htf_s:
        return "SHORT BIAS"
    if trend_l and htf_l:
        return "LONG BIAS"
    if htf_s and not trend_s:
        return "HTF SHORT / LTF NOT READY"
    if htf_l and not trend_l:
        return "HTF LONG / LTF NOT READY"
    return "NEUTRAL / MIXED"


def easy_trap_warning(traps):
    if not traps:
        return "ไม่มีสัญญาณหลอกชัด"
    out = []
    for t in traps:
        if "BUYER ABSORPTION" in t:
            out.append("มีแรงซื้อสวน ทำให้ short เสี่ยงโดนเด้ง")
        elif "SELLER ABSORPTION" in t:
            out.append("มีแรงขายสวน ทำให้ long เสี่ยงโดนย่อ")
        elif "FAILED BREAKDOWN" in t:
            out.append("ราคาพยายามลงแต่ลงไม่ผ่าน")
        elif "FAILED BREAKOUT" in t:
            out.append("ราคาพยายามขึ้นแต่ขึ้นไม่ผ่าน")
        elif "LIQUIDITY BUILD" in t:
            out.append("ตลาดเหมือนกำลังสะสมคนผิดทาง")
        elif "CROWDED POSITIONING" in t:
            out.append("คนเริ่มไปทางเดียวกันมากเกินไป")
        else:
            out.append(t)
    return " | ".join(out)


def probability_meaning(prob):
    if prob >= 80:
        return "สูงมาก"
    if prob >= 65:
        return "ค่อนข้างสูง"
    if prob >= 50:
        return "กลาง ๆ"
    if prob >= 35:
        return "ยังไม่ชัด"
    return "ต่ำ"


# ================= SMART MONEY TIMING =================
def oi_shift_text(side, oi_v):
    if oi_v is None:
        return "ยังไม่มีข้อมูล OI shift"
    if side == "LONG":
        if oi_v >= OI_SHIFT_POSITIVE:
            return "OI เริ่มกลับมาหนุนฝั่งขึ้น"
        if oi_v > 0:
            return "OI บวกอ่อน ๆ ยังไม่เด่น"
        return "OI ยังไม่หนุนฝั่งขึ้น"
    if oi_v <= -OI_SHIFT_POSITIVE:
        return "OI เริ่มกลับมาหนุนฝั่งลง"
    if oi_v < 0:
        return "OI ลบอ่อน ๆ ยังไม่เด่น"
    return "OI ยังไม่หนุนฝั่งลง"


def premium_shift_text(side, prem):
    if prem is None:
        return "ยังไม่มีข้อมูล premium"
    if side == "LONG":
        if prem >= 0:
            return "premium กลับเป็นบวกแล้ว"
        if prem >= PREMIUM_RECOVER_LONG:
            return "premium ฟื้นตัวแล้ว แต่ยังไม่บวก"
        return "premium ยังไม่หนุนฝั่งขึ้น"
    if prem <= 0:
        return "premium กลับเป็นลบแล้ว"
    if prem <= PREMIUM_RECOVER_SHORT:
        return "premium อ่อนลงแล้ว แต่ยังไม่ลบ"
    return "premium ยังไม่หนุนฝั่งลง"


def entry_timing_mode(side, cur, atr_v, reversal=None, auto_entry=None):
    if not auto_entry or atr_v is None:
        return "ยังไม่มีจังหวะเข้า", None
    entry_level = auto_entry.get("entry_level")
    if entry_level is None:
        return "ยังไม่มีจุดเข้า", None
    pullback_band = atr_v * PULLBACK_ATR_PCT
    if side == "LONG":
        if cur["c"] >= entry_level and cur["c"] <= entry_level + pullback_band:
            return "โซนเข้าแบบ pullback", entry_level
        if cur["c"] > entry_level + pullback_band:
            return "ขึ้นไปแล้ว รอ pullback ดีกว่า", entry_level
        return "ยังไม่ถึงจุดเข้า", entry_level
    else:
        if cur["c"] <= entry_level and cur["c"] >= entry_level - pullback_band:
            return "โซนเข้าแบบ pullback", entry_level
        if cur["c"] < entry_level - pullback_band:
            return "ลงไปแล้ว รอ pullback ดีกว่า", entry_level
        return "ยังไม่ถึงจุดเข้า", entry_level


# ================= COMMIT CHECK =================
def commit_check(side, cur, auto_entry, atr_v, oi_v, prem):
    if not auto_entry:
        return {
            "commit": False,
            "label": "ยังไม่มีจุดที่รายใหญ่ commit",
            "fails": ["ยังไม่มีสัญญาณเข้า"],
            "hold_ok": False,
            "oi_ok": False,
            "premium_ok": False,
        }

    entry_level = auto_entry.get("entry_level")
    hold_ok = False
    oi_ok = False
    premium_ok = False
    fails = []

    if side == "LONG":
        if entry_level is not None:
            hold_ok = cur["c"] >= entry_level
        oi_ok = (oi_v is not None and oi_v >= COMMIT_OI_LONG)
        premium_ok = (prem is not None and prem >= COMMIT_PREMIUM_LONG)
    else:
        if entry_level is not None:
            hold_ok = cur["c"] <= entry_level
        oi_ok = (oi_v is not None and oi_v <= COMMIT_OI_SHORT)
        premium_ok = (prem is not None and prem <= COMMIT_PREMIUM_SHORT)

    if not hold_ok:
        fails.append("ราคายังยืนเหนือ/ใต้จุดเข้าไม่ชัด")
    if not oi_ok:
        fails.append("OI ยังไม่บอกว่ารายใหญ่ commit")
    if not premium_ok:
        fails.append("premium ยังไม่บอกว่ารายใหญ่ commit")

    commit = hold_ok and oi_ok and premium_ok
    label = "รายใหญ่ commit จริงแล้ว" if commit else "ยังไม่ใช่จุดที่รายใหญ่ commit จริง"
    return {
        "commit": commit,
        "label": label,
        "fails": fails,
        "hold_ok": hold_ok,
        "oi_ok": oi_ok,
        "premium_ok": premium_ok,
    }


def commit_text(info):
    if not info:
        return "ยังไม่ได้เช็ก"
    if info.get("commit"):
        return "commit จริงแล้ว — เข้าได้"
    return f"ยังไม่ commit ({' | '.join(info.get('fails', []))})"


# ================= TRAP / REVERSAL =================
def detect_short_trap(cur, prev, atr_v, ob, oi_v, prem, checks):
    traps = []
    near_prev_low = False
    if atr_v:
        near_prev_low = dist_to_level(cur["c"], prev["l"]) <= atr_v * TRAP_DISTANCE_ATR
    if checks["trend"] and checks["htf"] and not checks["break"]:
        if oi_v is not None and oi_v >= TRAP_OI_STRONG and (prem is None or prem > PREMIUM_SHORT):
            traps.append("LIQUIDITY BUILD — OI up but no breakdown")
    if checks["trend"] and checks["htf"] and ob is not None and ob >= TRAP_BOOK_OPPOSITE_SHORT:
        traps.append("BUYER ABSORPTION — book opposes short bias")
    if checks["trend"] and checks["htf"] and not checks["break"] and near_prev_low:
        if body_pct(cur) <= TRAP_REJECTION_BODY_PCT or lower_wick_pct(cur) >= TRAP_WICK_PCT:
            traps.append("FAILED BREAKDOWN — tested low but got rejected")
    if oi_v is not None and oi_v >= TRAP_OI_VERY_STRONG and (prem is None or prem > TRAP_PREMIUM_WEAK_SHORT):
        traps.append("CROWDED POSITIONING — OI strong but premium weak")
    return traps


def detect_long_trap(cur, prev, atr_v, ob, oi_v, prem, checks):
    traps = []
    near_prev_high = False
    if atr_v:
        near_prev_high = dist_to_level(cur["c"], prev["h"]) <= atr_v * TRAP_DISTANCE_ATR
    if checks["trend"] and checks["htf"] and not checks["break"]:
        if oi_v is not None and oi_v >= TRAP_OI_STRONG and (prem is None or prem < PREMIUM_LONG):
            traps.append("LIQUIDITY BUILD — OI up but no breakout")
    if checks["trend"] and checks["htf"] and ob is not None and ob <= TRAP_BOOK_OPPOSITE_LONG:
        traps.append("SELLER ABSORPTION — book opposes long bias")
    if checks["trend"] and checks["htf"] and not checks["break"] and near_prev_high:
        if body_pct(cur) <= TRAP_REJECTION_BODY_PCT or upper_wick_pct(cur) >= TRAP_WICK_PCT:
            traps.append("FAILED BREAKOUT — tested high but got rejected")
    if oi_v is not None and oi_v >= TRAP_OI_VERY_STRONG and (prem is None or prem < TRAP_PREMIUM_WEAK_LONG):
        traps.append("CROWDED POSITIONING — OI strong but premium weak")
    return traps


def trap_severity(traps):
    n = len(traps)
    if n >= 3:
        return "STRONG TRAP"
    if n == 2:
        return "EARLY TRAP"
    if n == 1:
        return "TRAP RISK"
    return "NONE"


def remember_trap(side, cur, prev, traps):
    return {
        "side": side,
        "trap_close_time": cur["close_time"],
        "trap_open_time": cur["open_time"],
        "trap_candle_high": cur["h"],
        "trap_candle_low": cur["l"],
        "prev_high": prev["h"],
        "prev_low": prev["l"],
        "traps": traps[:],
    }


def remember_reversal(side, cur, trap_info, reasons, entry_hint, reclaim_level):
    return {
        "side": side,
        "reversal_close_time": cur["close_time"],
        "reversal_open_time": cur["open_time"],
        "reversal_candle_high": cur["h"],
        "reversal_candle_low": cur["l"],
        "trap_info": trap_info,
        "reasons": reasons[:],
        "entry_hint": entry_hint,
        "reclaim_level": reclaim_level,
    }


def detect_reversal_after_short_trap(cur, ob, oi_v, prem, trap_info):
    if not trap_info:
        return None
    reasons = []
    reclaim_level = max(trap_info["trap_candle_high"], trap_info["prev_high"])
    if cur["c"] > reclaim_level:
        reasons.append("reclaimed above trap structure")
    if ob is not None and ob >= REVERSAL_BOOK_LONG:
        reasons.append("buyer control on orderbook")
    if prem is not None and prem >= REVERSAL_PREMIUM_LONG:
        reasons.append("premium recovered")
    if oi_v is not None and oi_v <= 0:
        reasons.append("shorts may be closing")
    if len(reasons) >= 2:
        return {
            "side": "LONG",
            "label": "SHORT TRAP COMPLETE",
            "reasons": reasons,
            "entry_hint": f"watch LONG, reclaim above {fmt_price(reclaim_level)}",
            "reclaim_level": reclaim_level,
        }
    return None


def detect_reversal_after_long_trap(cur, ob, oi_v, prem, trap_info):
    if not trap_info:
        return None
    reasons = []
    reclaim_level = min(trap_info["trap_candle_low"], trap_info["prev_low"])
    if cur["c"] < reclaim_level:
        reasons.append("reclaimed below trap structure")
    if ob is not None and ob <= REVERSAL_BOOK_SHORT:
        reasons.append("seller control on orderbook")
    if prem is not None and prem <= REVERSAL_PREMIUM_SHORT:
        reasons.append("premium deteriorated")
    if oi_v is not None and oi_v <= 0:
        reasons.append("longs may be closing")
    if len(reasons) >= 2:
        return {
            "side": "SHORT",
            "label": "LONG TRAP COMPLETE",
            "reasons": reasons,
            "entry_hint": f"watch SHORT, reclaim below {fmt_price(reclaim_level)}",
            "reclaim_level": reclaim_level,
        }
    return None


# ================= AUTO ENTRY =================
def trap_age_in_candles(cur, ref_close_time):
    if ref_close_time is None:
        return None
    return int((cur["close_time"] - ref_close_time) / (15 * 60))


def detect_auto_entry_after_short_trap(cur, ob, oi_v, prem, atr_v, reversal_info):
    if not reversal_info:
        return None
    age = trap_age_in_candles(cur, reversal_info["reversal_close_time"])
    if age is None or age < 0 or age > POST_TRAP_MAX_WAIT_CANDLES:
        return None
    reclaim = reversal_info["reclaim_level"]
    buffer = (atr_v * POST_TRAP_CLOSE_BUFFER_ATR) if atr_v else 0.0
    reasons = []
    if cur["c"] > reclaim + buffer:
        reasons.append("close held above reclaim level")
    if body_pct(cur) >= POST_TRAP_MIN_BODY_PCT:
        reasons.append("strong candle body")
    if ob is not None and ob >= POST_TRAP_BOOK_LONG:
        reasons.append("buyer still in control")
    if prem is not None and prem >= POST_TRAP_PREMIUM_LONG:
        reasons.append("premium improving")
    if oi_v is not None and oi_v >= 0:
        reasons.append("OI not fighting reversal")
    if len(reasons) >= 3:
        return {
            "side": "LONG",
            "label": "AUTO ENTRY LONG AFTER SHORT TRAP",
            "reasons": reasons,
            "entry_hint": f"LONG entry valid above {fmt_price(reclaim)}",
            "entry_level": reclaim,
        }
    return None


def detect_auto_entry_after_long_trap(cur, ob, oi_v, prem, atr_v, reversal_info):
    if not reversal_info:
        return None
    age = trap_age_in_candles(cur, reversal_info["reversal_close_time"])
    if age is None or age < 0 or age > POST_TRAP_MAX_WAIT_CANDLES:
        return None
    reclaim = reversal_info["reclaim_level"]
    buffer = (atr_v * POST_TRAP_CLOSE_BUFFER_ATR) if atr_v else 0.0
    reasons = []
    if cur["c"] < reclaim - buffer:
        reasons.append("close held below reclaim level")
    if body_pct(cur) >= POST_TRAP_MIN_BODY_PCT:
        reasons.append("strong candle body")
    if ob is not None and ob <= POST_TRAP_BOOK_SHORT:
        reasons.append("seller still in control")
    if prem is not None and prem <= POST_TRAP_PREMIUM_SHORT:
        reasons.append("premium worsening")
    if oi_v is not None and oi_v >= 0:
        reasons.append("OI not fighting reversal")
    if len(reasons) >= 3:
        return {
            "side": "SHORT",
            "label": "AUTO ENTRY SHORT AFTER LONG TRAP",
            "reasons": reasons,
            "entry_hint": f"SHORT entry valid below {fmt_price(reclaim)}",
            "entry_level": reclaim,
        }
    return None


# ================= MEMORY =================
def remaining_auto_entry_candles(cur, reversal_info):
    if not reversal_info:
        return None
    age = trap_age_in_candles(cur, reversal_info.get("reversal_close_time"))
    if age is None:
        return None
    return POST_TRAP_MAX_WAIT_CANDLES - age


def current_bias_side(trend_s, trend_l, htf_s, htf_l):
    if trend_s and htf_s:
        return "SHORT"
    if trend_l and htf_l:
        return "LONG"
    return "MIXED"


def update_bias_memory(cur, bias_side):
    global _last_bias_side, _last_bias_change_time
    changed = False
    if bias_side != _last_bias_side:
        _last_bias_side = bias_side
        _last_bias_change_time = cur["close_time"]
        changed = True
    return changed


def bias_age_in_bars(cur):
    if _last_bias_change_time is None:
        return None
    return trap_age_in_candles(cur, _last_bias_change_time)


def clear_side_memory(side):
    global _last_short_trap, _last_long_trap, _last_short_reversal, _last_long_reversal
    changed = False
    if side == "SHORT":
        if _last_long_trap is not None:
            _last_long_trap = None
            changed = True
        if _last_short_reversal is not None:
            _last_short_reversal = None
            changed = True
    elif side == "LONG":
        if _last_short_trap is not None:
            _last_short_trap = None
            changed = True
        if _last_long_reversal is not None:
            _last_long_reversal = None
            changed = True
    return changed


def maybe_reset_memory_on_bias_flip(cur, bias_side):
    if not BIAS_FLIP_RESET_ON_CLOSED:
        return False
    age = bias_age_in_bars(cur)
    if bias_side not in {"SHORT", "LONG"}:
        return False
    if age is None or age < BIAS_FLIP_CONFIRM_BARS:
        return False
    changed = clear_side_memory(bias_side)
    if changed:
        save_state(force=True)
    return changed


def stage_text(cur):
    if _last_long_reversal:
        remain = remaining_auto_entry_candles(cur, _last_long_reversal)
        if remain is not None and remain >= 0:
            return f"REVERSAL LONG ACTIVE → auto-entry window {remain}"
    if _last_short_reversal:
        remain = remaining_auto_entry_candles(cur, _last_short_reversal)
        if remain is not None and remain >= 0:
            return f"REVERSAL SHORT ACTIVE → auto-entry window {remain}"
    if _last_short_trap:
        return "SHORT TRAP DETECTED → wait LONG reversal"
    if _last_long_trap:
        return "LONG TRAP DETECTED → wait SHORT reversal"
    return "NO ACTIVE TIMELINE"


def easy_stage_text(cur):
    s = stage_text(cur)
    if "NO ACTIVE TIMELINE" in s:
        return "ยังไม่มีจังหวะชัด"
    if "SHORT TRAP DETECTED" in s:
        return "ตลาดอาจกำลังหลอกฝั่ง short แล้วรอดูเด้งกลับ"
    if "LONG TRAP DETECTED" in s:
        return "ตลาดอาจกำลังหลอกฝั่ง long แล้วรอดูย่อลง"
    if "REVERSAL LONG ACTIVE" in s:
        return "เริ่มมีสัญญาณกลับขึ้น กำลังรอแท่งยืนยันเข้า long"
    if "REVERSAL SHORT ACTIVE" in s:
        return "เริ่มมีสัญญาณกลับลง กำลังรอแท่งยืนยันเข้า short"
    return s


def memory_status_line(cur):
    parts = []
    if _last_short_trap:
        parts.append(f"short_trap@{ts_to_str(_last_short_trap['trap_close_time'])}")
    if _last_long_trap:
        parts.append(f"long_trap@{ts_to_str(_last_long_trap['trap_close_time'])}")
    if _last_long_reversal:
        remain = remaining_auto_entry_candles(cur, _last_long_reversal)
        status = "expired" if remain is not None and remain < 0 else f"remain={remain}"
        parts.append(f"long_reversal[{status}]")
    if _last_short_reversal:
        remain = remaining_auto_entry_candles(cur, _last_short_reversal)
        status = "expired" if remain is not None and remain < 0 else f"remain={remain}"
        parts.append(f"short_reversal[{status}]")
    if _last_bias_side:
        parts.append(f"bias={_last_bias_side}")
    return " | ".join(parts) if parts else "none"


def prune_memory(cur):
    global _last_short_trap, _last_long_trap, _last_short_reversal, _last_long_reversal
    changed = False
    if _last_long_reversal:
        remain = remaining_auto_entry_candles(cur, _last_long_reversal)
        if remain is not None and remain < 0:
            _last_long_reversal = None
            changed = True
    if _last_short_reversal:
        remain = remaining_auto_entry_candles(cur, _last_short_reversal)
        if remain is not None and remain < 0:
            _last_short_reversal = None
            changed = True
    if _last_short_trap and _last_long_reversal is None:
        age = trap_age_in_candles(cur, _last_short_trap.get("trap_close_time"))
        if age is not None and age > (POST_TRAP_MAX_WAIT_CANDLES + TRAP_MEMORY_TTL_EXTRA):
            _last_short_trap = None
            changed = True
    if _last_long_trap and _last_short_reversal is None:
        age = trap_age_in_candles(cur, _last_long_trap.get("trap_close_time"))
        if age is not None and age > (POST_TRAP_MAX_WAIT_CANDLES + TRAP_MEMORY_TTL_EXTRA):
            _last_long_trap = None
            changed = True
    if changed:
        save_state(force=True)


# ================= CHECKS / FILTER =================
def build_checks(cur, prev, trend_s, trend_l, htf_s, htf_l, ob, oi_v, prem):
    checks_s = {
        "trend": trend_s,
        "htf": htf_s,
        "break": cur["c"] < prev["l"],
        "orderbook": ob <= SHORT_OB_MAX,
        "oi": (oi_v is not None and oi_v >= OI_SPIKE),
        "premium": (prem is not None and prem <= PREMIUM_SHORT),
    }
    checks_l = {
        "trend": trend_l,
        "htf": htf_l,
        "break": cur["c"] > prev["h"],
        "orderbook": ob >= LONG_OB_MIN,
        "oi": (oi_v is not None and oi_v >= OI_SPIKE),
        "premium": (prem is not None and prem >= PREMIUM_LONG),
    }
    return checks_s, checks_l


def compute_intent_momentum(cur, prev, checks, ob, oi_v, prem, atr_v, fake_move=None):
    checks = checks or {}
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    stretch_up = max(0.0, cur["h"] - prev["h"])
    stretch_dn = max(0.0, prev["l"] - cur["l"])

    long_score = 0
    short_score = 0

    if ob is not None:
        if ob >= LONG_OB_MIN:
            long_score += 18
        elif ob <= SHORT_OB_MAX:
            short_score += 18

    if oi_v is not None:
        if oi_v >= OI_SHIFT_POSITIVE:
            long_score += 12
        elif oi_v <= -OI_SHIFT_POSITIVE:
            short_score += 12

    if prem is not None:
        if prem >= EARLY_BREAK_PREMIUM_LONG:
            long_score += 14
        if prem <= EARLY_BREAK_PREMIUM_SHORT:
            short_score += 14

    if checks.get("trend"):
        long_score += 8 if checks.get("break") else 4
    if checks.get("htf"):
        long_score += 6
    # if caller passed short-oriented checks, reward short path instead
    if checks.get("trend") and checks.get("premium") and checks.get("orderbook") and not checks.get("break"):
        short_score += 4

    if cur["c"] > prev["h"]:
        long_score += 10
    elif cur["c"] < prev["l"]:
        short_score += 10

    if cur["l"] < prev["l"]:
        short_score += 8
    if cur["h"] > prev["h"]:
        long_score += 8

    if stretch_up >= atr_ref * EARLY_BREAK_ATR_PCT:
        long_score += 6
    if stretch_dn >= atr_ref * EARLY_BREAK_ATR_PCT:
        short_score += 6

    if fake_move and fake_move.get("active"):
        if fake_move.get("type") == "FAKE PUMP":
            short_score += 20
            long_score -= 6
        elif fake_move.get("type") == "FAKE DUMP":
            long_score += 20
            short_score -= 6

    return max(0, int(long_score)), max(0, int(short_score))


def detect_early_break(side, cur, prev, ob, oi_v, prem, atr_v):
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    early_down = cur["l"] <= (prev["l"] - atr_ref * EARLY_BREAK_ATR_PCT)
    early_up = cur["h"] >= (prev["h"] + atr_ref * EARLY_BREAK_ATR_PCT)

    if side == "SHORT":
        if early_down and ob is not None and ob <= EARLY_BREAK_OB_SHORT and (prem is None or prem <= EARLY_BREAK_PREMIUM_SHORT):
            return {"active": True, "side": "SHORT", "label": "EARLY BREAK SHORT"}
    else:
        if early_up and ob is not None and ob >= EARLY_BREAK_OB_LONG and (prem is None or prem >= EARLY_BREAK_PREMIUM_LONG):
            return {"active": True, "side": "LONG", "label": "EARLY BREAK LONG"}
    return None



def detect_probable_smash(side, cur, prev, ob, oi_v, prem, atr_v, checks=None, fake_move=None):
    checks = checks or {}
    long_mom, short_mom = compute_intent_momentum(cur, prev, checks, ob, oi_v, prem, atr_v, fake_move)
    if side == "SHORT":
        early = detect_early_break("SHORT", cur, prev, ob, oi_v, prem, atr_v)
        if early and short_mom >= PROBABLE_SMASH_MOMENTUM and ob is not None and ob <= PROBABLE_SMASH_OB_SHORT and (prem is None or prem <= PROBABLE_SMASH_PREMIUM_SHORT):
            return {
                "active": True,
                "side": "SHORT",
                "label": "PROBABLE SMASH DOWN",
                "why": f"early break + short momentum {short_mom} + seller pressure"
            }
    if side == "LONG":
        early = detect_early_break("LONG", cur, prev, ob, oi_v, prem, atr_v)
        if early and long_mom >= PROBABLE_SMASH_MOMENTUM and ob is not None and ob >= PROBABLE_SMASH_OB_LONG and (prem is None or prem >= PROBABLE_SMASH_PREMIUM_LONG):
            return {
                "active": True,
                "side": "LONG",
                "label": "PROBABLE SMASH UP",
                "why": f"early break + long momentum {long_mom} + buyer pressure"
            }
    return None


def detect_probe_entry(side, checks, prob=None, probable_smash=None, early_break=None):
    if probable_smash and probable_smash.get("active") and prob is not None and prob >= PROBE_ENTRY_MIN_PROB:
        return {
            "active": True,
            "side": side,
            "label": f"PROBE ENTRY {side}",
            "reason": probable_smash.get("label"),
            "risk_tag": "PROBE SIZE",
        }
    if early_break and early_break.get("active") and prob is not None and prob >= PROBE_ENTRY_MIN_PROB + 4:
        return {
            "active": True,
            "side": side,
            "label": f"PROBE ENTRY {side}",
            "reason": early_break.get("label"),
            "risk_tag": "PROBE SIZE",
        }
    return None


def detect_distribution_zone(side, cur, prev, atr_v, ef_value=None, em_value=None, es_value=None, ob=None, oi_v=None, prem=None, fake_move=None):
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    ema_refs = [x for x in [ef_value, em_value, es_value] if x is not None]
    near_ema = False
    if ema_refs:
        near_ema = min(abs(cur["c"] - e) for e in ema_refs) <= atr_ref * DISTRIBUTION_NEAR_EMA_ATR

    if side == "SHORT":
        rejection = upper_wick_pct(cur) >= DISTRIBUTION_WICK_PCT or (cur["h"] > prev["h"] and cur["c"] < cur["h"])
        oi_not_expanding = oi_v is None or oi_v <= DISTRIBUTION_MAX_OI
        premium_not_long = prem is None or prem <= DISTRIBUTION_PREMIUM_SHORT_MAX
        if fake_move and fake_move.get("active") and fake_move.get("type") == "FAKE PUMP" and near_ema and rejection and oi_not_expanding and premium_not_long:
            return {
                "active": True,
                "side": "SHORT",
                "label": "DISTRIBUTION SHORT ZONE",
                "why": "ลากขึ้นใกล้ EMA แต่ยังไม่ใช่ long commitment",
            }
    else:
        rejection = lower_wick_pct(cur) >= DISTRIBUTION_WICK_PCT or (cur["l"] < prev["l"] and cur["c"] > cur["l"])
        oi_not_expanding = oi_v is None or oi_v >= -DISTRIBUTION_MAX_OI
        premium_not_short = prem is None or prem >= DISTRIBUTION_PREMIUM_LONG_MIN
        if fake_move and fake_move.get("active") and fake_move.get("type") == "FAKE DUMP" and near_ema and rejection and oi_not_expanding and premium_not_short:
            return {
                "active": True,
                "side": "LONG",
                "label": "ACCUMULATION LONG ZONE",
                "why": "กดลงใกล้ EMA แต่ยังไม่ใช่ short commitment",
            }
    return None


def detect_layered_probe_entry(side, prob=None, probable_smash=None, early_break=None, distribution_zone=None):
    if probable_smash and probable_smash.get("active") and prob is not None and prob >= PROBE_ENTRY_MIN_PROB:
        return {
            "active": True,
            "side": side,
            "label": f"PROBE ENTRY {side}",
            "reason": probable_smash.get("label"),
            "risk_tag": "PROBE SIZE",
            "layer": 2,
        }
    if early_break and early_break.get("active") and prob is not None and prob >= PROBE_ENTRY_MIN_PROB + 4:
        return {
            "active": True,
            "side": side,
            "label": f"PROBE ENTRY {side}",
            "reason": early_break.get("label"),
            "risk_tag": "PROBE SIZE",
            "layer": 2,
        }
    if distribution_zone and distribution_zone.get("active") and prob is not None and prob >= DISTRIBUTION_PROBE_MIN_PROB:
        return {
            "active": True,
            "side": distribution_zone.get("side", side),
            "label": f"PROBE ENTRY {distribution_zone.get('side', side)}",
            "reason": distribution_zone.get("label"),
            "risk_tag": "SMALL PROBE",
            "layer": 1,
        }
    return None

def detect_institutional_smash(cur, prev, ob, oi_v, prem, atr_v):
    atr_ref = atr_v or max(abs(cur["h"] - cur["l"]), 1.0)
    rng = cur["h"] - cur["l"]
    body = abs(cur["c"] - cur["o"])
    body_ratio = (body / rng) if rng > 0 else 0.0

    smash_down = (
        cur["c"] < prev["l"]
        and rng >= atr_ref * SMASH_RANGE_ATR_MULT
        and body_ratio >= SMASH_BODY_PCT
        and oi_v is not None and oi_v <= SMASH_OI_SHORT
        and prem is not None and prem <= SMASH_PREMIUM_SHORT
    )
    if smash_down:
        return {
            "active": True,
            "side": "SHORT",
            "label": "INSTITUTIONAL SMASH DOWN",
            "why": "range expansion + body dominant + OI/premium confirm",
        }

    smash_up = (
        cur["c"] > prev["h"]
        and rng >= atr_ref * SMASH_RANGE_ATR_MULT
        and body_ratio >= SMASH_BODY_PCT
        and oi_v is not None and oi_v >= SMASH_OI_LONG
        and prem is not None and prem >= SMASH_PREMIUM_LONG
    )
    if smash_up:
        return {
            "active": True,
            "side": "LONG",
            "label": "INSTITUTIONAL SMASH UP",
            "why": "range expansion + body dominant + OI/premium confirm",
        }
    return None


def weakening_phase_from_scores(long_score, short_score):
    if short_score - long_score >= INTENT_SHIFT_MIN_DELTA:
        return "WEAKENING LONG"
    if long_score - short_score >= INTENT_SHIFT_MIN_DELTA:
        return "WEAKENING SHORT"
    return "NEUTRAL"


def choose_side(checks_s, checks_l):
    short_score = sum(1 for v in checks_s.values() if v)
    long_score = sum(1 for v in checks_l.values() if v)
    if short_score >= long_score:
        return "SHORT", checks_s
    return "LONG", checks_l


def probability_score(side, checks, traps, reversal=None, auto_entry=None, ob=None, oi_v=None, prem=None):
    score = sum(1 for v in checks.values() if bool(v)) * 12
    if traps:
        score += min(len(traps) * 10, 25)
    if reversal:
        score += 20
    if auto_entry:
        score += 28
    if side == "SHORT":
        if ob is not None and ob < 0.45:
            score += 6
        elif ob is not None and ob > 0.60:
            score -= 10
        if prem is not None and prem < -0.0004:
            score += 5
    if side == "LONG":
        if ob is not None and ob > 0.55:
            score += 6
        elif ob is not None and ob < 0.40:
            score -= 10
        if prem is not None and prem > 0.0004:
            score += 5
    if oi_v is not None and oi_v > 0:
        score += 4
    return max(0, min(100, int(score)))


def build_entry_plan(side, price, atr_v, reversal=None, auto_entry=None):
    if atr_v is None:
        return None
    if auto_entry and auto_entry.get("entry_level") is not None:
        entry = auto_entry["entry_level"]
    elif reversal and reversal.get("reclaim_level") is not None:
        entry = reversal["reclaim_level"]
    else:
        entry = price
    if side == "LONG":
        sl = entry - atr_v * ENTRY_SL_ATR
        tp1 = entry + atr_v * ENTRY_TP1_ATR
        tp2 = entry + atr_v * ENTRY_TP2_ATR
    else:
        sl = entry + atr_v * ENTRY_SL_ATR
        tp1 = entry - atr_v * ENTRY_TP1_ATR
        tp2 = entry - atr_v * ENTRY_TP2_ATR
    risk = abs(entry - sl)
    reward1 = abs(tp1 - entry)
    reward2 = abs(tp2 - entry)
    rr1 = reward1 / risk if risk > 0 else None
    rr2 = reward2 / risk if risk > 0 else None
    return {
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
        "rr1": rr1, "rr2": rr2, "valid": (rr1 is not None and rr1 >= MIN_RR_FOR_ENTRY)
    }


def entry_plan_text(plan):
    if not plan:
        return "ยังไม่มีแผนเข้า"
    valid_text = "ใช้ได้" if plan["valid"] else "ยังไม่คุ้ม"
    return (
        f"entry={fmt_price(plan['entry'])} | sl={fmt_price(plan['sl'])} | "
        f"tp1={fmt_price(plan['tp1'])} | tp2={fmt_price(plan['tp2'])} | "
        f"rr1={fmt_rr(plan['rr1'])} | rr2={fmt_rr(plan['rr2'])} | {valid_text}"
    )


def true_commit_check(side, cur, prev, checks, auto_entry=None, entry_filter=None, commit_info=None, is_closed=False):
    if not A_PLUS_ONLY_MODE:
        return {"passed": False, "reasons": ["A+ only mode disabled"]}
    reasons = []
    if not auto_entry:
        reasons.append("ยังไม่มี auto-entry")
    if not entry_filter or not entry_filter.get("passed"):
        reasons.append("A+ entry filter ยังไม่ผ่าน")
    if not commit_info or not commit_info.get("commit"):
        reasons.append("ยังไม่เกิด true commit")
    for k in ["trend", "htf"]:
        if not checks.get(k):
            reasons.append(f"{k} ยังไม่ผ่าน")
    if TRUE_COMMIT_REQUIRE_BREAK and not checks.get("break"):
        reasons.append("break ยังไม่ผ่าน")
    if TRUE_COMMIT_REQUIRE_ORDERBOOK and not checks.get("orderbook"):
        reasons.append("orderbook ยังไม่ผ่าน")
    if TRUE_COMMIT_REQUIRE_OI and not checks.get("oi"):
        reasons.append("OI ยังไม่ผ่าน")
    if TRUE_COMMIT_REQUIRE_PREMIUM and not checks.get("premium"):
        reasons.append("premium ยังไม่ผ่าน")
    if TRUE_COMMIT_REQUIRE_TRIGGER_TOUCH and auto_entry and auto_entry.get("entry_level") is not None:
        if not entry_trigger_touched(side, cur, auto_entry.get("entry_level"), is_closed=is_closed):
            reasons.append("ราคายังไม่แตะ trigger จริง")
    return {"passed": len(reasons) == 0, "reasons": reasons}


def a_plus_only_grade(side, checks, auto_entry=None, entry_filter=None, commit_info=None, is_closed=False, cur=None, prev=None):
    tc = true_commit_check(side, cur or {}, prev or {}, checks, auto_entry, entry_filter, commit_info, is_closed=is_closed)
    return ("A+", tc) if tc["passed"] else ("NO TRADE", tc)


def confidence_layer(prob, quality, traps, reversal=None, auto_entry=None):
    if auto_entry and prob >= 75:
        return "Strong A+"
    if auto_entry or (quality == "A+" and prob >= 68):
        return "A+"
    if reversal or (quality in {"VERY CLOSE", "CLOSE"} and prob >= 50):
        return "พอใช้"
    if traps:
        return "เสี่ยงโดนหลอก"
    if prob >= 35 or quality == "WATCH":
        return "เฝ้าดู"
    return "ยังไม่ชัด"


def entry_timing_text(side, quality, traps, reversal=None, auto_entry=None, plan=None):
    if auto_entry:
        if plan and plan.get("valid"):
            return "เข้าได้เมื่อแท่งปิดยืนยัน หรือรอ pullback เล็ก ๆ ถ้าไม่อยากไล่ราคา"
        return "มีสัญญาณเข้า แต่ RR ยังไม่เด่น รอ pullback ก่อน"
    if reversal:
        return "ยังไม่เข้า รอแท่งปิดยืนยันอีก 1 แท่ง"
    if traps:
        return "ยังห้ามเข้า ฝั่งนี้เสี่ยงโดนหลอก"
    if quality == "A+":
        return "เข้าได้เมื่อแท่งปิด"
    if quality in {"VERY CLOSE", "CLOSE"}:
        return "รอแท่งปิดก่อน ยังไม่ควรรีบ"
    if quality == "WATCH":
        return "รอดูต่อ ยังไม่ใช่จังหวะเข้า"
    return "ยังไม่เข้า รอให้ชัดกว่านี้"


def entry_trigger_touched(side, cur, entry_level, is_closed=False):
    if entry_level is None:
        return False
    if side == "LONG":
        return cur["c"] >= entry_level if is_closed else cur["h"] >= entry_level
    return cur["c"] <= entry_level if is_closed else cur["l"] <= entry_level


def final_entry_filter(side, cur, checks, extra, auto_entry=None, is_closed=False, prob_for_filter=None):
    if not auto_entry:
        return {"checked": True, "passed": False, "reason": "ยังไม่มีสัญญาณเข้า", "fails": [], "prob": 0}

    prob = prob_for_filter if prob_for_filter is not None else probability_score(
        side, checks, [], None, auto_entry, extra.get("ob"), extra.get("oi"), extra.get("premium")
    )

    entry_level = auto_entry.get("entry_level")
    fails = []
    if ENTRY_FILTER_REQUIRE_TRIGGER_TOUCH and not entry_trigger_touched(side, cur, entry_level, is_closed=is_closed):
        fails.append("ราคายังไม่แตะจุดเข้า")
    if ENTRY_FILTER_REQUIRE_ORDERBOOK and not checks.get("orderbook"):
        fails.append("orderbook ยังไม่หนุน")
    if ENTRY_FILTER_REQUIRE_OI and not checks.get("oi"):
        fails.append("OI ยังไม่หนุน")
    if ENTRY_FILTER_REQUIRE_PREMIUM and not checks.get("premium"):
        fails.append("premium ยังไม่หนุน")
    if prob < ENTRY_FILTER_MIN_PROB:
        fails.append(f"probability ต่ำกว่า {ENTRY_FILTER_MIN_PROB}")

    passed = len(fails) == 0
    return {
        "checked": True,
        "passed": passed,
        "reason": "ผ่าน A+ ENTRY FILTER" if passed else " | ".join(fails),
        "fails": fails,
        "prob": prob,
    }


def entry_filter_text(info):
    if not info:
        return "ยังไม่ได้เช็ก"
    return "ผ่าน — เข้าได้" if info.get("passed") else f"ล็อกไว้ก่อน ({info.get('reason')})"


def exec_lock_text(info):
    if not info:
        return "ยังไม่ได้เช็ก"
    if info.get("passed"):
        return "ปลดล็อกแล้ว — เข้าได้"
    return f"ระบบล็อกไว้ก่อน: {info.get('reason')}"


# ================= STATE / ACTION =================
def state_text(side, checks, traps, reversal=None, auto_entry=None):
    trend_ok = checks["trend"]
    htf_ok = checks["htf"]
    break_ok = checks["break"]
    oi_ok = checks["oi"]
    prem_ok = checks["premium"]

    if auto_entry:
        return f"{auto_entry['label']} → enter {auto_entry['side']}"
    if reversal:
        return f"{reversal['label']} → watch {reversal['side']}"
    if all(checks.values()):
        return f"{side} confirmed"
    if traps:
        return f"{side} bias with trap risk"
    if trend_ok and htf_ok and not break_ok and (not oi_ok or not prem_ok):
        return f"{side} bias but not real break"
    if trend_ok and htf_ok and not break_ok:
        return f"{side} bias waiting break"
    if htf_ok and not trend_ok:
        return f"HTF {side} but LTF not ready"
    if trend_ok or htf_ok:
        return f"{side} setup building"
    return "No clear edge"


def action_now_text(side, quality, checks, prev, traps, reversal=None, auto_entry=None):
    if auto_entry:
        return f"ENTER {auto_entry['side']} — follow-through confirmed"
    if reversal:
        return f"WATCH {reversal['side']} — trap complete, wait follow-through"
    if traps:
        if side == "SHORT":
            return f"NO SHORT — trap risk, wait close below {fmt_price(prev['l'])}"
        return f"NO LONG — trap risk, wait close above {fmt_price(prev['h'])}"
    if quality == "A+":
        return f"Enter {side}"
    if quality == "VERY CLOSE":
        return f"Wait one more confirm for {side}"
    if quality == "CLOSE":
        return f"Watch {side}, not entry yet"
    if quality == "WATCH":
        return f"Monitor {side} only"
    return "Stand aside"


def final_summary_text(side, quality, checks, traps, reversal=None, auto_entry=None):
    failed = [k for k, v in checks.items() if not v]
    if auto_entry:
        return f"{auto_entry['label']} | {' + '.join(auto_entry['reasons'])}"
    if reversal:
        return f"{reversal['label']} | {' + '.join(reversal['reasons'])}"
    if quality == "A+":
        return f"A+ {side} | entry ready now | all checks passed"
    if traps:
        return f"Trap risk on {side} | market may be building liquidity first"
    if quality == "VERY CLOSE":
        return f"Very close {side} | still missing: {', '.join(failed)}"
    if quality == "CLOSE":
        return f"Close to {side} | wait for cleaner confirmation"
    if quality == "WATCH":
        return f"Watch {side} | setup forming but not enough edge"
    return "No trade | bias may exist but setup still weak"


def decision_text(side, quality, reversal=None, auto_entry=None):
    if auto_entry:
        return f"ENTER {auto_entry['side']}"
    if reversal:
        return f"WATCH {reversal['side']}"
    return "STAND ASIDE" if quality != "A+" else f"ENTER {side}"


def price_trigger_hint(side, prev, reversal=None, auto_entry=None):
    if auto_entry:
        return auto_entry["entry_hint"]
    if reversal:
        return reversal["entry_hint"]
    if side == "SHORT":
        return f"close below prev_low {fmt_price(prev['l'])}"
    return f"close above prev_high {fmt_price(prev['h'])}"


def liquidity_targets(side, prev, trap_info=None, reversal=None, atr_v=None):
    atr_pad = atr_v or 0.0
    if reversal and reversal.get("side") == "LONG":
        base = reversal.get("reclaim_level", prev["h"])
        return {
            "near": base + atr_pad * 0.5,
            "main": max(prev["h"], base) + atr_pad,
            "stretch": max(prev["h"], base) + atr_pad * 1.8,
        }
    if reversal and reversal.get("side") == "SHORT":
        base = reversal.get("reclaim_level", prev["l"])
        return {
            "near": base - atr_pad * 0.5,
            "main": min(prev["l"], base) - atr_pad,
            "stretch": min(prev["l"], base) - atr_pad * 1.8,
        }
    if trap_info and trap_info.get("side") == "SHORT":
        ref = max(trap_info.get("trap_candle_high", prev["h"]), trap_info.get("prev_high", prev["h"]))
        return {"near": ref, "main": ref + atr_pad * 0.8, "stretch": ref + atr_pad * 1.5}
    if trap_info and trap_info.get("side") == "LONG":
        ref = min(trap_info.get("trap_candle_low", prev["l"]), trap_info.get("prev_low", prev["l"]))
        return {"near": ref, "main": ref - atr_pad * 0.8, "stretch": ref - atr_pad * 1.5}
    if side == "SHORT":
        return {"near": prev["l"], "main": prev["l"] - atr_pad, "stretch": prev["l"] - atr_pad * 1.8}
    return {"near": prev["h"], "main": prev["h"] + atr_pad, "stretch": prev["h"] + atr_pad * 1.8}


def market_phase_label(prob, traps, reversal=None, auto_entry=None):
    if auto_entry:
        return "เข้าได้"
    if reversal:
        return "เริ่มกลับตัว"
    if traps:
        return "เริ่มมีจังหวะหลอก"
    if prob < 35:
        return "ยังลังเล"
    if prob < 50:
        return "เริ่มก่อตัว"
    return "รอจังหวะยืนยัน"


def final_verdict_text(side, quality, traps, entry_filter=None, commit_info=None, reversal=None, auto_entry=None,
                       grade=None, true_commit=None):
    if true_commit and true_commit.get("passed"):
        return f"ENTER {side} — A+ ONLY HARD LOCK ผ่านแล้ว"
    return "NO TRADE — ยังไม่ใช่ A+ จริง"


def quick_take_text(state):
    side = state.get("side")
    checks = state.get("checks") or {}
    traps = state.get("traps") or []
    reversal = state.get("reversal")
    auto_entry = state.get("auto_entry")
    entry_filter = state.get("entry_filter")
    commit_info = state.get("commit_info")
    grade = state.get("grade")
    fake_move = state.get("fake_move") or {}
    early_entry = state.get("early_entry") or {}
    trap_exploit = state.get("trap_exploit") or {}
    expansion_long = state.get("expansion_long") or {}
    squeeze_sync = state.get("squeeze_sync") or {}

    missing = [k for k, v in checks.items() if not v]
    if fake_move.get("active"):
        return f"{grade or 'NO TRADE'} | {fake_move.get('type')}"
    if auto_entry:
        lock_txt = "unlock" if entry_filter and entry_filter.get("passed") else "lock"
        commit_txt = "commit" if commit_info and commit_info.get("commit") else "no-commit"
        return f"{grade or 'SETUP'} | auto-entry {auto_entry['side']} | {lock_txt} | {commit_txt}"
    if squeeze_sync.get("active"):
        return f"{grade or 'SETUP'} | squeeze-sync LONG | score={squeeze_sync.get('score', '?')}"
    if expansion_long.get("active"):
        return f"{grade or 'SETUP'} | early-expansion LONG | building"
    if early_entry.get("active"):
        return f"{grade or 'SETUP'} | early-entry {early_entry.get('side')} | {early_entry.get('risk_tag')}"
    if trap_exploit.get("active"):
        return f"{grade or 'SETUP'} | trap-exploit {trap_exploit.get('side')} | {trap_exploit.get('risk_tag')}"
    if reversal:
        return f"{grade or 'SETUP'} | reversal {reversal['side']} | wait confirm"
    if traps:
        return f"{grade or 'SETUP'} | trap risk | avoid {str(side).lower()}"
    if checks and not missing:
        return f"{grade or 'SETUP'} | {str(side).lower()} fully confirmed"
    return f"{grade or 'SETUP'} | missing: {', '.join(missing) if missing else '-'}"


def grade_explain_text(grade):
    if grade == "A+":
        return "เข้าได้เต็มสิทธิ์"
    if grade == "A":
        return "เข้าได้ แต่ควรเบาไม้กว่า A+"
    if grade == "WATCHLIST":
        return "มีทรง แต่ยังไม่ใช่จุดเข้า"
    return "ยังไม่ควรเทรด"


def print_section(title):
    print("-" * 100)
    print(title)


# ================= NARRATIVE ENGINE =================
def smart_money_group(side, checks, traps, reversal=None, auto_entry=None, fake_move=None, prob=None, flip_setup=None, expansion_long=None, squeeze_sync=None):
    if auto_entry:
        return "SMART MONEY COMMIT"
    if squeeze_sync:
        return "SMART MONEY SHORT SQUEEZE"
    if expansion_long:
        return "SMART MONEY EARLY EXPANSION"
    if flip_setup:
        return "SMART MONEY AUTO FLIP"
    if reversal:
        return "SMART MONEY REVERSAL"
    if fake_move and fake_move.get("active"):
        return "SMART MONEY FAKE MOVE"
    if traps:
        return "SMART MONEY TRAP / LIQUIDITY HUNT"
    if checks.get("htf") and not checks.get("trend"):
        return "SMART MONEY PREP / WAITING"
    if prob is not None and prob >= 60:
        return "SMART MONEY BUILDUP"
    return "SMART MONEY NEUTRAL"


def detect_fake_move(side, checks, cur, prev, ob, oi_v, prem):
    active = False
    move_type = None
    reasons = []

    broke_up = cur["h"] > prev["h"] or cur["c"] > prev["h"]
    broke_down = cur["l"] < prev["l"] or cur["c"] < prev["l"]

    # fake pump: price pushes up but no real long commitment
    if broke_up and not checks.get("trend") and not checks.get("break"):
        if ob is not None and ob >= 0.60:
            reasons.append("ราคาดันขึ้นแรง")
        if oi_v is None or oi_v < OI_SPIKE:
            reasons.append("OI ไม่หนุน long จริง")
        if prem is None or prem < PREMIUM_LONG:
            reasons.append("premium ยังไม่หนุน long จริง")
        if len(reasons) >= 2:
            active = True
            move_type = "FAKE PUMP"

    # fake dump: price pushes down but no real short commitment
    if not active and broke_down and checks.get("trend") and not checks.get("break"):
        reasons2 = []
        if ob is not None and ob <= 0.40:
            reasons2.append("ราคากดลงแรง")
        if oi_v is None or oi_v < OI_SPIKE:
            reasons2.append("OI ไม่หนุน short จริง")
        if prem is None or prem > PREMIUM_SHORT:
            reasons2.append("premium ยังไม่หนุน short จริง")
        if len(reasons2) >= 2:
            active = True
            move_type = "FAKE DUMP"
            reasons = reasons2

    return {"active": active, "type": move_type, "reasons": reasons}


def smart_money_now_text(group_name, side, checks, traps, reversal=None, auto_entry=None, fake_move=None, flip_setup=None, expansion_long=None, squeeze_sync=None):
    if auto_entry:
        return f"กำลัง commit ฝั่ง {auto_entry['side']} และเริ่มเดินเกมจริง"
    if squeeze_sync:
        return "แรงเด้งเริ่ม sync กันแบบ short squeeze และกำลังบีบคน short ออก"
    if expansion_long:
        return "แรงขึ้นต้นทางเริ่มมา แต่ยังต้องดูว่าจะ follow-through เป็น squeeze จริงไหม"
    if flip_setup:
        return "กดลงเพื่อหลอก แล้วกำลัง auto-flip bias ไปฝั่ง LONG"
    if reversal:
        return f"กำลังพลิกเกมจาก trap ไปฝั่ง {reversal['side']}"
    if fake_move and fake_move.get('active'):
        if fake_move.get('type') == 'FAKE PUMP':
            return "กำลังลากขึ้นเพื่อเช็ก liquidity ด้านบน แต่ยังไม่ใช่ long commitment"
        return "กำลังกดลงเพื่อเช็ก liquidity ด้านล่าง แต่ยังไม่ใช่ short commitment"
    if traps:
        if side == 'SHORT':
            return "กำลังล่อให้คน short ผิดจังหวะ แล้วค่อยเลือกทาง"
        return "กำลังล่อให้คน long ผิดจังหวะ แล้วค่อยเลือกทาง"
    if checks.get('htf') and not checks.get('trend'):
        return "ยังถือ bias ใหญ่ไว้ แต่ยังไม่เริ่ม push ใน timeframe นี้"
    return "ยังไม่เผยไพ่ชัด กำลังดู reaction ของตลาด"


def smart_money_next_text(side, checks, prev, traps, reversal=None, auto_entry=None, fake_move=None, flip_setup=None, expansion_long=None, squeeze_sync=None):
    if auto_entry:
        return f"ถ้า follow-through ต่อ มีโอกาสไปหา liquidity ฝั่ง {auto_entry['side']} ต่อ"
    if squeeze_sync:
        return f"ถัดไปต้องดูว่าจะ hold เหนือ {fmt_price(squeeze_sync['reclaim_level'])} แล้วเร่งเป็น short squeeze เต็มตัวได้หรือไม่"
    if expansion_long:
        return f"ถัดไปต้องดูว่าแรงขยายจะต่อเนื่องเหนือ {fmt_price(expansion_long['reclaim_level'])} หรือไม่"
    if flip_setup:
        return f"ถัดไปต้องดูว่าจะ reclaim เหนือ {fmt_price(flip_setup['reclaim_level'])} แล้วไปต่อฝั่ง LONG ได้หรือไม่"
    if reversal:
        return f"ถัดไปต้องดูว่าจะ reclaim แล้วไปต่อฝั่ง {reversal['side']} ได้หรือไม่"
    if fake_move and fake_move.get('active'):
        if fake_move.get('type') == 'FAKE PUMP':
            return f"มีโอกาส sweep high/sideway ต่อ ก่อนดูว่าจะ reject ลงหรือไม่"
        return f"มีโอกาส sweep low/sideway ต่อ ก่อนดูว่าจะเด้งกลับหรือไม่"
    if traps:
        return "ถัดไปมักมีการกิน stop อีกฝั่ง แล้วค่อยเฉลยทางจริง"
    if side == 'SHORT':
        return f"ต้องรอหลุด {fmt_price(prev['l'])} แบบมีแรงตาม ถึงจะนับว่ากดจริง"
    return f"ต้องรอผ่าน {fmt_price(prev['h'])} แบบมีแรงตาม ถึงจะนับว่าดันจริง"


def smart_money_targets_text(side, prev, traps, reversal=None, auto_entry=None, fake_move=None):
    if auto_entry and auto_entry.get('side') == 'LONG':
        return f"เป้าแรก = เหนือ {fmt_price(prev['h'])} | เป้าต่อ = liquidity high ถัดไป"
    if auto_entry and auto_entry.get('side') == 'SHORT':
        return f"เป้าแรก = ใต้ {fmt_price(prev['l'])} | เป้าต่อ = liquidity low ถัดไป"
    if fake_move and fake_move.get('active'):
        if fake_move.get('type') == 'FAKE PUMP':
            return f"เป้าปัจจุบัน = กวาด high เหนือ {fmt_price(prev['h'])} หรือค้างบนเพื่อหลอก short"
        return f"เป้าปัจจุบัน = กวาด low ใต้ {fmt_price(prev['l'])} หรือค้างล่างเพื่อหลอก long"
    if traps:
        return "เป้าปัจจุบัน = ล่า liquidity ของฝั่งที่รีบเข้า"
    return "เป้าปัจจุบัน = รอให้ liquidity สะสมมากพอแล้วค่อยเร่ง"


def smart_money_result_text(side, checks, traps, reversal=None, auto_entry=None, fake_move=None):
    if auto_entry:
        return "ผลลัพธ์ที่คาด = ตลาดเริ่มวิ่งจริง ถ้าตามด้วย volume/OI จะเป็น expansion"
    if reversal:
        return "ผลลัพธ์ที่คาด = ถ้า follow-through ผ่าน จะเปลี่ยนจาก trap เป็น reversal"
    if fake_move and fake_move.get('active'):
        return "ผลลัพธ์ที่คาด = คนที่ไล่ราคามีโอกาสโดนติด แล้วตลาดค่อยเฉลยทิศ"
    if traps:
        return "ผลลัพธ์ที่คาด = ตลาดยังกิน stop ทั้งสองฝั่งก่อนเลือกทาง"
    return "ผลลัพธ์ที่คาด = ยัง sideway / test reaction ต่อจนกว่าจะมี commitment"


def fake_move_text(fake_move):
    if not fake_move or not fake_move.get('active'):
        return 'NONE | ไม่มี fake move ชัด'
    return f"{fake_move.get('type')} | {' | '.join(fake_move.get('reasons', []))}"


# ================= LOGGING =================
def print_block(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def fmt_targets(targets):
    if not targets:
        return "n/a"
    return f"near={fmt_price(targets.get('near'))} | main={fmt_price(targets.get('main'))} | stretch={fmt_price(targets.get('stretch'))}"



def checklist_mark(ok):
    return "✅" if ok else "❌"


def decision_grade_sync(decision, quality=None):
    quality = quality or "NO TRADE"
    if decision == "ENTER":
        return "A+" if quality == "A+" else "A"
    if decision == "PREPARE":
        return "WATCHLIST"
    return "NO TRADE"


def hard_decision_engine(side, checks, prev, quality=None, entry_filter=None, commit_info=None, reversal=None, auto_entry=None):
    checks = checks or {}
    trend_ok = bool(checks.get("trend"))
    htf_ok = bool(checks.get("htf"))
    break_ok = bool(checks.get("break"))
    ob_ok = bool(checks.get("orderbook"))
    oi_ok = bool(checks.get("oi"))
    prem_ok = bool(checks.get("premium"))
    filter_ok = bool(entry_filter and entry_filter.get("passed"))
    commit_ok = bool(commit_info and commit_info.get("commit"))
    has_reversal = bool(reversal)
    has_auto_entry = bool(auto_entry)
    quality = quality or signal_quality(checks)

    trigger_hint = price_trigger_hint(side, prev, reversal, auto_entry)
    bias_ok = trend_ok and htf_ok
    structure_ok = break_ok or has_reversal or has_auto_entry
    flow_ok = ob_ok and (oi_ok or prem_ok)
    execution_ok = filter_ok or commit_ok or has_auto_entry

    if bias_ok and structure_ok and flow_ok and execution_ok:
        decision = "ENTER"
        action_text = f"ENTER {auto_entry.get('side', side) if has_auto_entry else side}"
        reason_text = "ครบทั้ง bias + break + flow + commit"
    elif bias_ok and (structure_ok or flow_ok or execution_ok):
        decision = "PREPARE"
        wait_bits = []
        if not structure_ok:
            wait_bits.append(trigger_hint)
        if not flow_ok:
            wait_bits.append("รอ flow confirm (orderbook + oi/premium)")
        if not execution_ok:
            wait_bits.append("รอ commit จริง")
        action_text = "PREPARE — " + " | ".join(wait_bits[:2] if wait_bits else ["รอเงื่อนไขครบ"])
        reason_text = "bias มาแล้ว แต่ยังไม่ครบชุดเข้า"
    else:
        decision = "NO TRADE"
        wait_bits = []
        if not bias_ok:
            wait_bits.append("bias ยังไม่ตรง trend/htf")
        if not structure_ok:
            wait_bits.append(trigger_hint)
        if not flow_ok:
            wait_bits.append("flow ยังไม่มา")
        action_text = "NO TRADE — " + " | ".join(wait_bits[:2] if wait_bits else ["ยังไม่ใช่จุดเข้า"])
        reason_text = "ยังไม่ใช่จังหวะเข้า"

    synced_grade = decision_grade_sync(decision, quality)

    return {
        "decision": decision,
        "action_text": action_text,
        "reason_text": reason_text,
        "bias_ok": bias_ok,
        "structure_ok": structure_ok,
        "flow_ok": flow_ok,
        "execution_ok": execution_ok,
        "trigger_hint": trigger_hint,
        "quality": synced_grade,
        "raw_quality": quality,
    }


def entry_checklist_5s(side, checks, prev, quality=None, entry_filter=None, commit_info=None, reversal=None, auto_entry=None):
    decision = hard_decision_engine(side, checks, prev, quality, entry_filter, commit_info, reversal, auto_entry)
    action_emoji = "🎯" if decision["decision"] == "ENTER" else "🟡" if decision["decision"] == "PREPARE" else "🧘"

    if auto_entry:
        break_text = "auto-entry confirmed"
    elif reversal:
        break_text = "reversal confirmed"
    elif decision["structure_ok"]:
        break_text = "structure confirmed"
    else:
        break_text = decision["trigger_hint"]

    commit_line = "เข้าได้" if decision["execution_ok"] else commit_text(commit_info)

    return (
        "\n📋 HARD DECISION 5 วิ\n"
        f"1) Bias {checklist_mark(decision['bias_ok'])} trend/htf\n"
        f"2) Break {checklist_mark(decision['structure_ok'])} {break_text}\n"
        f"3) Flow {checklist_mark(decision['flow_ok'])} orderbook + (oi/premium)\n"
        f"4) Commit {checklist_mark(decision['execution_ok'])} {commit_line}\n"
        f"5) Decision {action_emoji} {decision['action_text']}\n"
        f"mode: {decision['decision']}\n"
        f"grade: {decision['quality']}"
    )


def sniper_mode_summary(side, true_commit=None, auto_entry=None, entry_filter=None, commit_info=None, plan=None, cur=None, prev=None, checks=None, traps=None, fake_move=None, flip_setup=None):
    checks = checks or {}
    traps = traps or []
    reasons = []
    if true_commit and true_commit.get("passed"):
        return {
            "status": "READY TO FIRE",
            "action": f"กดเข้า {side} ได้",
            "gate": "A+ ผ่านครบทุกด่าน",
            "note": "จุดนี้คือ sniper entry ของระบบ",
        }

    if flip_setup and flip_setup.get("active"):
        return {
            "status": "ARMED",
            "action": "เตรียมมอง LONG ถ้า reclaim ผ่าน",
            "gate": f"auto-flip bias -> LONG above {fmt_price(flip_setup.get('reclaim_level'))}",
            "note": flip_setup.get("label"),
        }

    if fake_move and fake_move.get("active"):
        return {
            "status": "SAFETY ON",
            "action": "ยังไม่กดเข้า",
            "gate": "เจอ fake move",
            "note": fake_move.get("type", "fake move"),
        }

    if traps:
        reasons.append("มี trap risk")

    if auto_entry:
        if entry_filter and entry_filter.get("passed") and commit_info and not commit_info.get("commit"):
            return {
                "status": "ARMED",
                "action": "เตรียมตัว แต่ยังไม่กด",
                "gate": "filter ผ่าน แต่ commit ยังไม่ครบ",
                "note": commit_text(commit_info),
            }
        return {
            "status": "TRACKING",
            "action": "ดู trigger อย่างใกล้ชิด",
            "gate": "มี auto-entry แต่ยังไม่ผ่าน hard lock",
            "note": entry_filter_text(entry_filter),
        }

    missing = [k for k, v in checks.items() if not v]
    if missing:
        gate = ", ".join(missing[:3])
        if len(missing) > 3:
            gate += ", ..."
    else:
        gate = "ยังไม่มี edge ชัด"

    note = " | ".join(reasons) if reasons else "ยังไม่ถึงจุด sniper"
    return {
        "status": "WAIT",
        "action": "stand aside",
        "gate": gate,
        "note": note,
    }


def compact_live_levels(side, prev, atr_v=None, reversal=None, auto_entry=None):
    plan_side = auto_entry["side"] if auto_entry else (reversal["side"] if reversal else side)

    if auto_entry and auto_entry.get("entry_level") is not None:
        trigger_level = auto_entry["entry_level"]
    elif reversal and reversal.get("reclaim_level") is not None:
        trigger_level = reversal["reclaim_level"]
    elif plan_side == "SHORT":
        trigger_level = prev["l"]
    else:
        trigger_level = prev["h"]

    plan = build_entry_plan(plan_side, trigger_level, atr_v, reversal, auto_entry)
    if plan and plan.get("sl") is not None:
        invalidation = plan["sl"]
    elif plan_side == "SHORT":
        invalidation = prev["h"]
    else:
        invalidation = prev["l"]

    return f"trigger={fmt_price(trigger_level)} | invalidation={fmt_price(invalidation)}"


def live_event_text(side, grade, traps, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None, true_commit=None):
    if true_commit and true_commit.get("passed"):
        return f"A+ ENTER {side}"
    return "NO TRADE"


def live_reason_text(side, checks, traps, reversal=None, auto_entry=None, fake_move=None):
    if auto_entry:
        return "follow-through confirmed, setup unlocked"
    if reversal:
        return "trap complete, waiting follow-through"
    if fake_move and fake_move.get("active"):
        reasons = fake_move.get("reasons") or []
        return reasons[0] if reasons else "fake move detected"
    if traps:
        return easy_trap_warning(traps)
    missing = [k for k, v in checks.items() if not v]
    return f"missing: {', '.join(missing)}" if missing else f"{side.lower()} confirmed"


def live_do_dont_text(side, grade, traps, reversal=None, auto_entry=None, fake_move=None, true_commit=None):
    if true_commit and true_commit.get("passed"):
        return f"DO=execute {side.lower()} now | DON'T=hesitate"
    return "DO=stand aside | DON'T=force trade"



def live_phase_text(side, traps, reversal=None, auto_entry=None, fake_move=None, checks=None,
                    cur=None, prev=None, ob=None, oi_v=None, prem=None, atr_v=None):
    traps = traps or []
    checks = checks or {}
    if auto_entry:
        return f"CONFIRM {auto_entry['side']}"
    if reversal:
        return f"BUILD {reversal['side']}"
    if fake_move and fake_move.get("active"):
        if fake_move.get("type") == "FAKE DUMP":
            return "BUILD LONG"
        if fake_move.get("type") == "FAKE PUMP":
            return "BUILD SHORT"
    if traps:
        if side == "SHORT":
            return "BUILD LONG"
        if side == "LONG":
            return "BUILD SHORT"
    if cur is not None and prev is not None:
        long_score, short_score = compute_intent_momentum(cur, prev, checks, ob, oi_v, prem, atr_v, fake_move)
        weak = weakening_phase_from_scores(long_score, short_score)
        if weak != "NEUTRAL":
            return weak
    if all(checks.get(k) for k in ["trend", "htf", "break", "orderbook", "oi", "premium"]):
        return f"COMMIT {side}"
    if checks.get("trend") and checks.get("htf"):
        return f"BUILD {side}"
    return "NEUTRAL"

def live_smart_money_type(side, traps, reversal=None, auto_entry=None, fake_move=None):
    if auto_entry:
        return f"AUTO_ENTRY_{auto_entry['side']}"
    if reversal:
        return f"REVERSAL_{reversal['side']}"
    if fake_move and fake_move.get("active"):
        return fake_move.get("type", "FAKE_MOVE")
    if traps:
        return f"{trap_severity(traps)}_{side}"
    return f"FLOW_{side}"


def normalize_live_price(value):
    if value is None:
        return "n/a"
    return f"{round(float(value), 1):.1f}"



def phase_confidence(phase, checks, traps=None, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None):
    traps = traps or []
    score = sum(1 for v in (checks or {}).values() if v)
    if smash and getattr(smash, "get", None) and smash.get("active"):
        return 92
    if probable_smash and getattr(probable_smash, "get", None) and probable_smash.get("active"):
        return 86
    if probe_entry and getattr(probe_entry, "get", None) and probe_entry.get("active"):
        return 78
    if distribution_zone and getattr(distribution_zone, "get", None) and distribution_zone.get("active"):
        return 74
    if auto_entry:
        return 90
    if reversal:
        return 80
    if fake_move and fake_move.get("active"):
        return 72
    if traps:
        return 70
    if phase.startswith("COMMIT"):
        return 85 if score >= 5 else 68
    if phase.startswith("BUILD"):
        return 58 + score * 2
    return 40 + score * 2


def phase_direction(phase):
    if not phase:
        return "NEUTRAL"
    if phase.endswith("LONG"):
        return "LONG"
    if phase.endswith("SHORT"):
        return "SHORT"
    return "NEUTRAL"


def stabilize_live_phase(raw_phase, checks, traps=None, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None):
    global _last_stable_live_phase, _last_stable_live_phase_ts, _live_candidate_phase, _live_candidate_phase_count
    global _last_intent, _last_intent_ts, _intent_candidate, _intent_candidate_count
    now_ts = time.time()
    conf = phase_confidence(raw_phase, checks, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone)

    if auto_entry:
        _last_stable_live_phase = raw_phase
        _last_stable_live_phase_ts = now_ts
        _live_candidate_phase = None
        _live_candidate_phase_count = 0
        return raw_phase

    if reversal:
        target_phase = f"BUILD {reversal['side']}"
        _last_stable_live_phase = target_phase
        _last_stable_live_phase_ts = now_ts
        _live_candidate_phase = None
        _live_candidate_phase_count = 0
        return target_phase

    if _last_stable_live_phase is None:
        _last_stable_live_phase = raw_phase
        _last_stable_live_phase_ts = now_ts
        return raw_phase

    if raw_phase == _last_stable_live_phase:
        _live_candidate_phase = None
        _live_candidate_phase_count = 0
        _last_stable_live_phase_ts = now_ts
        return _last_stable_live_phase

    stable_dir = phase_direction(_last_stable_live_phase)
    raw_dir = phase_direction(raw_phase)
    if stable_dir != "NEUTRAL" and raw_dir != "NEUTRAL" and stable_dir != raw_dir:
        if (now_ts - _last_stable_live_phase_ts) < PHASE_HOLD_SECONDS:
            return _last_stable_live_phase
        if conf < PHASE_FLIP_MIN_CONFIDENCE:
            return _last_stable_live_phase

    if raw_phase == _live_candidate_phase:
        _live_candidate_phase_count += 1
    else:
        _live_candidate_phase = raw_phase
        _live_candidate_phase_count = 1
        return _last_stable_live_phase

    if _live_candidate_phase_count < LIVE_STATE_CONFIRM_TICKS:
        return _last_stable_live_phase

    _last_stable_live_phase = raw_phase
    _last_stable_live_phase_ts = now_ts
    _live_candidate_phase = None
    _live_candidate_phase_count = 0
    return raw_phase



def derive_live_intent(side, checks, cur=None, prev=None, ob=None, oi_v=None, prem=None, atr_v=None,
                       traps=None, reversal=None, auto_entry=None, fake_move=None, smash=None):
    traps = traps or []
    if smash and smash.get("active"):
        return f"SMASH_{smash['side']}"
    if auto_entry:
        return f"COMMIT_{auto_entry['side']}"
    if reversal:
        return f"BUILD_{reversal['side']}"

    if cur is not None and prev is not None:
        early_break = detect_early_break(side, cur, prev, ob, oi_v, prem, atr_v)
        if early_break and early_break.get("active"):
            return f"EARLY_BREAK_{early_break['side']}"

    if fake_move and fake_move.get("active"):
        if fake_move.get("type") == "FAKE PUMP":
            return "SWEEP_UP_FADE"
        if fake_move.get("type") == "FAKE DUMP":
            return "SWEEP_DOWN_RECLAIM"

    if traps:
        if side == "SHORT":
            return "TRAP_SHORT_LOOK_LONG"
        if side == "LONG":
            return "TRAP_LONG_LOOK_SHORT"

    if cur is not None and prev is not None:
        long_score, short_score = compute_intent_momentum(cur, prev, checks or {}, ob, oi_v, prem, atr_v, fake_move)
        if short_score - long_score >= INTENT_SHIFT_MIN_DELTA:
            return "SHIFT_TO_SHORT"
        if long_score - short_score >= INTENT_SHIFT_MIN_DELTA:
            return "SHIFT_TO_LONG"

    if checks.get("trend") and checks.get("htf") and checks.get("break"):
        return f"BREAK_{side}"
    if checks.get("htf") and not checks.get("trend"):
        return f"HTF_{side}_WAIT"
    return "RANGE_REACTION"

def intent_direction(intent):
    if not intent:
        return "NEUTRAL"
    if any(k in intent for k in ["LONG", "RECLAIM"]):
        return "LONG"
    if any(k in intent for k in ["SHORT", "FADE"]):
        return "SHORT"
    return "NEUTRAL"


def stabilize_intent(raw_intent, checks, traps=None, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None):
    global _last_intent, _last_intent_ts, _intent_candidate, _intent_candidate_count
    now_ts = time.time()
    conf = phase_confidence(
        phase=(f"CONFIRM {auto_entry['side']}" if auto_entry else f"BUILD {reversal['side']}" if reversal else "BUILD"),
        checks=checks,
        traps=traps,
        reversal=reversal,
        auto_entry=auto_entry,
        fake_move=fake_move,
        smash=smash,
        probable_smash=probable_smash,
        probe_entry=probe_entry,
        distribution_zone=distribution_zone,
    )

    if auto_entry:
        _last_intent = raw_intent
        _last_intent_ts = now_ts
        _intent_candidate = None
        _intent_candidate_count = 0
        return raw_intent

    if reversal:
        _last_intent = raw_intent
        _last_intent_ts = now_ts
        _intent_candidate = None
        _intent_candidate_count = 0
        return raw_intent

    if _last_intent is None:
        _last_intent = raw_intent
        _last_intent_ts = now_ts
        return raw_intent

    if raw_intent == _last_intent:
        _intent_candidate = None
        _intent_candidate_count = 0
        _last_intent_ts = now_ts
        return _last_intent

    stable_dir = intent_direction(_last_intent)
    raw_dir = intent_direction(raw_intent)

    if stable_dir != "NEUTRAL" and raw_dir != "NEUTRAL" and stable_dir != raw_dir:
        if (now_ts - _last_intent_ts) < INTENT_HOLD_SECONDS:
            return _last_intent
        if conf < PHASE_FLIP_MIN_CONFIDENCE:
            return _last_intent

    if raw_intent == _intent_candidate:
        _intent_candidate_count += 1
    else:
        _intent_candidate = raw_intent
        _intent_candidate_count = 1
        return _last_intent

    if _intent_candidate_count < INTENT_CONFIRM_TICKS:
        return _last_intent

    _last_intent = raw_intent
    _last_intent_ts = now_ts
    _intent_candidate = None
    _intent_candidate_count = 0
    return raw_intent



def phase_from_intent(intent, raw_phase):
    if not intent:
        return raw_phase
    mapping = {
        "COMMIT_LONG": "COMMIT LONG",
        "COMMIT_SHORT": "COMMIT SHORT",
        "BUILD_LONG": "BUILD LONG",
        "BUILD_SHORT": "BUILD SHORT",
        "SWEEP_UP_FADE": "BUILD SHORT",
        "SWEEP_DOWN_RECLAIM": "BUILD LONG",
        "TRAP_SHORT_LOOK_LONG": "BUILD LONG",
        "TRAP_LONG_LOOK_SHORT": "BUILD SHORT",
        "BREAK_LONG": "BUILD LONG",
        "BREAK_SHORT": "BUILD SHORT",
        "EARLY_BREAK_LONG": "BUILD LONG",
        "EARLY_BREAK_SHORT": "BUILD SHORT",
        "SHIFT_TO_LONG": "WEAKENING SHORT",
        "SHIFT_TO_SHORT": "WEAKENING LONG",
    }
    return mapping.get(intent, raw_phase)

def make_live_state_signature(side, bias_text, checks, cur, prev, atr_v=None, ob=None, oi_v=None, prem=None, traps=None, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None):
    traps = traps or []
    grade, _ = setup_grade(side, checks, traps, reversal, auto_entry, None, None, None, None, None, fake_move, None, None, None, None)
    tc_sig = true_commit_check(side, cur, prev, checks, auto_entry, None, {"commit": False}, is_closed=False) if not auto_entry else true_commit_check(side, cur, prev, checks, auto_entry, {"passed": False}, {"commit": False}, is_closed=False)
    event = live_event_text(side, grade, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone, tc_sig)
    raw_phase = live_phase_text(side, traps, reversal, auto_entry, fake_move, checks, cur=cur, prev=prev, ob=ob, oi_v=oi_v, prem=prem, atr_v=atr_v)
    raw_intent = derive_live_intent(side, checks, cur=cur, prev=prev, ob=ob, oi_v=oi_v, prem=prem, atr_v=atr_v, traps=traps, reversal=reversal, auto_entry=auto_entry, fake_move=fake_move, smash=smash)
    stable_intent = stabilize_intent(raw_intent, checks, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone)
    intent_phase = phase_from_intent(stable_intent, raw_phase)
    stable_phase = stabilize_live_phase(intent_phase, checks, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone)

    plan_side = auto_entry["side"] if auto_entry else (reversal["side"] if reversal else side)
    if auto_entry and auto_entry.get("entry_level") is not None:
        trigger_level = auto_entry["entry_level"]
    elif reversal and reversal.get("reclaim_level") is not None:
        trigger_level = reversal["reclaim_level"]
    elif plan_side == "SHORT":
        trigger_level = prev["l"]
    else:
        trigger_level = prev["h"]

    plan = build_entry_plan(plan_side, trigger_level, atr_v, reversal, auto_entry)
    if plan and plan.get("sl") is not None:
        invalidation = plan["sl"]
    elif plan_side == "SHORT":
        invalidation = prev["h"]
    else:
        invalidation = prev["l"]

    checks_key = ''.join('1' if checks.get(k) else '0' for k in ["trend", "htf", "break", "orderbook", "oi", "premium"])
    return '|'.join([
        bias_text,
        stable_intent or 'NONE',
        stable_phase,
        normalize_live_price(trigger_level),
        normalize_live_price(invalidation),
        checks_key,
    ])


def should_emit_live_state(event, traps=None, reversal=None, auto_entry=None, fake_move=None, checks=None, extra=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None):
    traps = traps or []
    checks = checks or {}
    extra = extra or {}
    if smash or probable_smash or probe_entry or distribution_zone or auto_entry or reversal or fake_move or traps:
        return True
    score = sum(1 for v in checks.values() if v)
    if score >= 5:
        return True
    if LIVE_ALERT_IF_ABNORMAL:
        ob = extra.get("ob")
        if ob is not None and (ob >= LIVE_ABNORMAL_OB_SHORT or ob <= LIVE_ABNORMAL_OB_LONG):
            return True
    return event != "NO TRADE"



def print_log(title, side, bias_text, checks, extra, cur, prev, quality, traps, reversal=None, auto_entry=None,
              entry_filter=None, timing_mode=None, oi_shift=None, premium_shift=None, commit_info=None,
              fake_move=None, early_entry=None, trap_exploit=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None, flip_setup=None, expansion_long=None, squeeze_sync=None, is_closed=True):
    failed = [k for k, v in checks.items() if not v]
    state = state_text(side, checks, traps, reversal, auto_entry)
    action = action_now_text(side, quality, checks, prev, traps, reversal, auto_entry)
    summary = final_summary_text(side, quality, checks, traps, reversal, auto_entry)
    trigger = price_trigger_hint(side, prev, reversal, auto_entry)
    tlevel = trap_severity(traps)
    active_trap = _last_short_trap if side == "SHORT" else _last_long_trap
    prob = probability_score(side, checks, traps, reversal, auto_entry, extra.get("ob"), extra.get("oi"), extra.get("premium"))
    targets = liquidity_targets(side, prev, active_trap, reversal or auto_entry, extra.get("atr"))
    plan_side = auto_entry["side"] if auto_entry else (reversal["side"] if reversal else side)
    plan = build_entry_plan(plan_side, cur["c"], extra.get("atr"), reversal, auto_entry)
    grade_prob = probability_score(side, checks, traps, reversal, auto_entry, extra.get("ob"), extra.get("oi"), extra.get("premium"))
    grade, _grade_prob = setup_grade(side, checks, traps, reversal, auto_entry, entry_filter, commit_info, extra.get("ob"), extra.get("oi"), extra.get("premium"), fake_move, early_entry, trap_exploit, expansion_long, squeeze_sync)
    grade, true_commit = a_plus_only_grade(side, checks, auto_entry, entry_filter, commit_info, is_closed=is_closed, cur=cur, prev=prev) if grade == "A+" else (grade, true_commit_check(side, cur, prev, checks, auto_entry, entry_filter, commit_info, is_closed=is_closed))
    verdict = final_verdict_text(side, quality, traps, entry_filter, commit_info, reversal, auto_entry, grade, true_commit)
    sniper = sniper_mode_summary(side, true_commit, auto_entry, entry_filter, commit_info, plan, cur, prev, checks, traps, fake_move, flip_setup)
    quick_take = quick_take_text({
        "side": side,
        "checks": checks,
        "traps": traps,
        "reversal": reversal,
        "auto_entry": auto_entry,
        "entry_filter": entry_filter,
        "commit_info": commit_info,
        "grade": grade,
        "fake_move": fake_move,
        "early_entry": early_entry,
        "trap_exploit": trap_exploit,
        "expansion_long": expansion_long,
        "squeeze_sync": squeeze_sync,
    })
    sm_group = smart_money_group(side, checks, traps, reversal, auto_entry, fake_move, prob, flip_setup, expansion_long, squeeze_sync)
    sm_now = smart_money_now_text(sm_group, side, checks, traps, reversal, auto_entry, fake_move, flip_setup, expansion_long, squeeze_sync)
    sm_next = smart_money_next_text(side, checks, prev, traps, reversal, auto_entry, fake_move, flip_setup, expansion_long, squeeze_sync)

    print_block(f"[{now()}] {title} | V9.1 EARLY EXPANSION / SHORT SQUEEZE SYNC ENGINE | {MODE_PROFILE}")
    candle_status = "CLOSED" if is_closed else "OPEN"

    if not is_closed:
        live_event = live_event_text(side, grade, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone, true_commit)
        live_do_dont = live_do_dont_text(side, grade, traps, reversal, auto_entry, fake_move, true_commit)
        live_levels = compact_live_levels(side, prev, extra.get("atr"), reversal, auto_entry)

        raw_live_phase = live_phase_text(side, traps, reversal, auto_entry, fake_move, checks, cur=cur, prev=prev, ob=extra.get("ob"), oi_v=extra.get("oi"), prem=extra.get("premium"), atr_v=extra.get("atr"))
        raw_intent = derive_live_intent(side, checks, cur=cur, prev=prev, ob=extra.get("ob"), oi_v=extra.get("oi"), prem=extra.get("premium"), atr_v=extra.get("atr"), traps=traps, reversal=reversal, auto_entry=auto_entry, fake_move=fake_move, smash=smash)
        live_intent = stabilize_intent(raw_intent, checks, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone)
        live_phase = stabilize_live_phase(phase_from_intent(live_intent, raw_live_phase), checks, traps, reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone)

        print_section("LIVE SNAPSHOT")
        print(f"CANDLE       : {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])} | {candle_status}")
        print(f"PRICE        : now={fmt_price(cur['c'])} | high={fmt_price(cur['h'])} | low={fmt_price(cur['l'])}")
        print(f"BIAS         : {bias_text}")
        long_mom, short_mom = compute_intent_momentum(cur, prev, checks, extra.get("ob"), extra.get("oi"), extra.get("premium"), extra.get("atr"), fake_move)
        print(f"INTENT       : {live_intent}")
        print(f"INTENT MOM   : long={long_mom} | short={short_mom}")
        print(f"PHASE        : {live_phase}")
        print(f"SMART MONEY  : {sm_now}")
        print(f"EVENT        : {live_event}")
        print(f"TRIGGER      : {trigger}")
        print(f"LEVELS       : {live_levels}")
        print(f"DO / DON'T   : {live_do_dont}")

        print_section("SNIPER MODE")
        print(f"STATUS       : {sniper['status']}")
        print(f"ACTION       : {sniper['action']}")
        print(f"GATE         : {sniper['gate']}")
        print(f"NOTE         : {sniper['note']}")
        print("=" * 100)
        return

    print_section("SNAPSHOT")
    print(f"CANDLE       : {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])} | {candle_status}")
    print(f"PRICE        : close={fmt_price(cur['c'])} | prev_high={fmt_price(prev['h'])} | prev_low={fmt_price(prev['l'])}")
    print(f"BIAS         : {bias_text}")
    print(f"GRADE        : {grade} ({grade_explain_text(grade)}) | prob={grade_prob}/100")
    print(f"VERDICT      : {verdict}")

    print_section("SMART MONEY")
    print(f"NOW          : {sm_now}")
    print(f"NEXT         : {sm_next}")
    if traps:
        print(f"TRAP         : {tlevel} | {easy_trap_warning(traps)}")
    if fake_move and fake_move.get('active'):
        print(f"FAKE MOVE    : {fake_move_text(fake_move)}")
    if flip_setup and flip_setup.get('active'):
        print(f"AUTO FLIP    : {flip_setup.get('label')} | {' + '.join(flip_setup.get('reasons', []))}")
    if smash and smash.get('active'):
        print(f"SMASH        : {smash.get('label')} | {smash.get('why')}")
    if probable_smash and probable_smash.get('active'):
        print(f"PROBABLE     : {probable_smash.get('label')} | {probable_smash.get('why')}")
    if distribution_zone and distribution_zone.get('active'):
        print(f"ZONE         : {distribution_zone.get('label')} | {distribution_zone.get('why')}")
    if probe_entry and probe_entry.get('active'):
        print(f"PROBE ENTRY  : {probe_entry.get('label')} | {probe_entry.get('risk_tag')} | {probe_entry.get('reason')}")
    if reversal:
        print(f"REVERSAL     : {reversal['label']} | {' + '.join(reversal['reasons'])}")
    if auto_entry:
        print(f"AUTO ENTRY   : {auto_entry['label']} | {' + '.join(auto_entry['reasons'])}")

    print_section("WHY")
    print(f"CHECKS       : {compact_reason(checks)}")
    print(f"STRUCTURE    : trend={passfail(checks['trend'])} | htf={passfail(checks['htf'])} | break={passfail(checks['break'])}")
    print(f"PRESSURE     : orderbook={passfail(checks['orderbook'])} | oi={passfail(checks['oi'])} | premium={passfail(checks['premium'])}")
    print(f"RAW          : ob={fmt_num(extra.get('ob'),4)} | oi={fmt_pct(extra.get('oi'),4)} | premium={fmt_num(extra.get('premium'),8)} | atr={fmt_price(extra.get('atr'))}")
    print(f"SHIFT        : OI={oi_shift or 'n/a'} | PREMIUM={premium_shift or 'n/a'}")
    mom_long, mom_short = compute_intent_momentum(cur, prev, checks, extra.get("ob"), extra.get("oi"), extra.get("premium"), extra.get("atr"), fake_move)
    print(f"INTENT MOM   : long={mom_long} | short={mom_short}")
    if failed:
        print(f"MISSING      : {failed}")

    print_section("PLAN")
    print(f"ACTION       : {action}")
    print(f"TRIGGER      : {trigger}")
    print(f"ENTRY STATUS : {verdict}")
    print(f"ENTRY PLAN   : {entry_plan_text(plan)}")
    print(f"ENTRY LOCK   : {exec_lock_text(entry_filter)}")
    print(f"COMMIT       : {commit_text(commit_info)}")
    print(f"TARGETS      : {fmt_targets(targets)}")

    print_section("SNIPER MODE")
    print(f"STATUS       : {sniper['status']}")
    print(f"ACTION       : {sniper['action']}")
    print(f"GATE         : {sniper['gate']}")
    print(f"NOTE         : {sniper['note']}")
    print("=" * 100)


def build_alert_message(side, price, checks, cur, prev, extra, traps, reversal=None, auto_entry=None, entry_filter=None, commit_info=None):
    prob = probability_score(side, checks, traps, reversal, auto_entry, extra.get("ob"), extra.get("oi"), extra.get("premium"))
    targets = liquidity_targets(side, prev, _last_short_trap if side == "SHORT" else _last_long_trap, reversal or auto_entry, extra.get("atr"))
    target_txt = fmt_targets(targets)
    quality = signal_quality(checks)
    checklist = entry_checklist_5s(side, checks, prev, quality, entry_filter, commit_info, reversal, auto_entry)
    if auto_entry:
        return (
            f"🚀 {auto_entry['label']} {SYMBOL}\n"
            f"time: {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])}\n"
            f"price: {fmt_price(price)}\n"
            f"filter: {entry_filter_text(entry_filter)}\n"
            f"exec_lock: {exec_lock_text(entry_filter)}\n"
            f"commit: {commit_text(commit_info)}\n"
            f"probability: {prob}/100\n"
            f"targets: {target_txt}\n"
            f"why: {' + ' .join(auto_entry['reasons'])}"
            f"{checklist}"
        )
    if reversal:
        return (
            f"↩️ {reversal['label']} {SYMBOL}\n"
            f"time: {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])}\n"
            f"price: {fmt_price(price)}\n"
            f"probability: {prob}/100\n"
            f"targets: {target_txt}\n"
            f"why: {' + ' .join(reversal['reasons'])}"
            f"{checklist}"
        )
    if traps:
        return (
            f"🪤 TRAP ALERT {side} {SYMBOL}\n"
            f"time: {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])}\n"
            f"price: {fmt_price(price)}\n"
            f"probability: {prob}/100\n"
            f"warning: {easy_trap_warning(traps)}"
            f"{checklist}"
        )
    return (
        f"🔥 A+ {side} {SYMBOL}\n"
        f"time: {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])}\n"
        f"price: {fmt_price(price)}\n"
        f"probability: {prob}/100\n"
        f"targets: {target_txt}"
        f"{checklist}"
    )

def build_special_event_message(tag, cur, prev, extra, detail, side=None, checks=None, traps=None):
    checks = checks or {}
    traps = traps or []
    side_ctx = side or detail.get("side") or "LONG"
    prob = probability_score(side_ctx, checks, traps, None, None, extra.get("ob"), extra.get("oi"), extra.get("premium"))
    headline = {
        "FAKE_MOVE": "🎭 FAKE MOVE",
        "SMASH": "💥 INSTITUTIONAL SMASH",
        "PROBABLE_SMASH": "⚠️ PROBABLE SMASH",
        "FLIP": "🔄 AUTO FLIP",
        "SQUEEZE": "🧨 SHORT SQUEEZE",
        "LIVE": "📡 LIVE UPDATE",
    }.get(tag, f"📣 {tag}")
    reasons = detail.get("reasons") or []
    why = detail.get("why") or detail.get("reason") or (' + ' .join(reasons) if reasons else '-')
    trigger = detail.get("entry_hint") or detail.get("label") or "watch reaction"
    reclaim = detail.get("reclaim_level")
    reclaim_txt = fmt_price(reclaim) if reclaim is not None else "n/a"
    checklist = entry_checklist_5s(side_ctx, checks, prev, signal_quality(checks), None, None, None, None)
    return (
        f"{headline} {SYMBOL}\n"
        f"time: {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])}\n"
        f"price: {fmt_price(cur['c'])}\n"
        f"event: {detail.get('label', tag)}\n"
        f"side: {side_ctx}\n"
        f"probability: {prob}/100\n"
        f"reclaim/trigger: {reclaim_txt} | {trigger}\n"
        f"ob={fmt_num(extra.get('ob'),4)} | oi={fmt_pct(extra.get('oi'),4)} | premium={fmt_num(extra.get('premium'),8)}\n"
        f"why: {why}"
        f"{checklist}"
    )

def maybe_send_live_summary(side, cur, prev, checks, extra, traps, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, flip_setup=None, squeeze_sync=None):
    global _last_live_summary_ts
    if not ENABLE_TELEGRAM or not ENABLE_TELEGRAM_LIVE_LOG:
        return
    now_ts = time.time()
    if (now_ts - _last_live_summary_ts) < LIVE_SUMMARY_MIN_SECONDS:
        return
    priority = any([auto_entry, reversal, fake_move, smash, probable_smash, flip_setup, squeeze_sync, traps])
    score = sum(1 for v in checks.values() if v)
    if not priority and score < 5:
        return
    _last_live_summary_ts = now_ts
    phase = live_phase_text(side, traps, reversal, auto_entry, fake_move, checks, cur=cur, prev=prev, ob=extra.get("ob"), oi_v=extra.get("oi"), prem=extra.get("premium"), atr_v=extra.get("atr"))
    quality = signal_quality(checks)
    live_msg = (
        f"📡 LIVE SNAPSHOT {SYMBOL}\n"
        f"time: {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])}\n"
        f"price: {fmt_price(cur['c'])} | high={fmt_price(cur['h'])} | low={fmt_price(cur['l'])}\n"
        f"bias: {side} | phase: {phase}\n"
        f"checks: {compact_reason(checks)}\n"
        f"state: {state_text(side, checks, traps, reversal, auto_entry)}\n"
        f"action: {action_now_text(side, quality, checks, prev, traps, reversal, auto_entry)}\n"
        f"raw: ob={fmt_num(extra.get('ob'),4)} | oi={fmt_pct(extra.get('oi'),4)} | premium={fmt_num(extra.get('premium'),8)}"
        f"{entry_checklist_5s(side, checks, prev, quality, None, None, reversal, auto_entry)}"
    )
    send_telegram(live_msg)

def should_print_live_log(side, bias_text, checks, extra, cur, prev, traps, reversal=None, auto_entry=None, fake_move=None, smash=None, probable_smash=None, probe_entry=None, distribution_zone=None):
    global _last_live_log_ts, _last_live_state_signature, _last_live_state_print_ts
    global _live_candidate_state_signature, _live_candidate_state_count

    if not ENABLE_LIVE_OPEN_CANDLE_LOG:
        return False

    signature = make_live_state_signature(
        side=side,
        bias_text=bias_text,
        checks=checks,
        cur=cur,
        prev=prev,
        atr_v=extra.get("atr"),
        ob=extra.get("ob"),
        oi_v=extra.get("oi"),
        prem=extra.get("premium"),
        traps=traps,
        reversal=reversal,
        auto_entry=auto_entry,
        fake_move=fake_move,
        smash=smash,
        probable_smash=probable_smash,
        probe_entry=probe_entry,
        distribution_zone=distribution_zone,
    )

    grade, _ = setup_grade(side, checks, traps or [], reversal, auto_entry, None, None, extra.get("ob"), extra.get("oi"), extra.get("premium"), fake_move, None, None, None, None)
    tc_evt = {"passed": False}
    event = live_event_text(side, grade, traps or [], reversal, auto_entry, fake_move, smash, probable_smash, probe_entry, distribution_zone, tc_evt)
    if not should_emit_live_state(event, traps, reversal, auto_entry, fake_move, checks, extra, smash, probable_smash, probe_entry, distribution_zone):
        return False

    now_ts = time.time()

    # state เดิมที่เคยยืนยันแล้ว = ไม่ต้องพิมพ์ซ้ำ และล้าง candidate เก่า
    if signature == _last_live_state_signature:
        _live_candidate_state_signature = None
        _live_candidate_state_count = 0
        return False

    # confirmation layer: ต้องเจอ state ใหม่ซ้ำ N ticks ก่อน
    if signature == _live_candidate_state_signature:
        _live_candidate_state_count += 1
    else:
        _live_candidate_state_signature = signature
        _live_candidate_state_count = 1
        save_state()
        return False

    if _live_candidate_state_count < LIVE_STATE_CONFIRM_TICKS:
        save_state()
        return False

    # cooldown กัน state flip ไปมาเร็วเกิน
    if _last_live_state_print_ts and (now_ts - _last_live_state_print_ts) < LIVE_STATE_CHANGE_COOLDOWN_SEC:
        save_state()
        return False

    _last_live_state_signature = signature
    _last_live_state_print_ts = now_ts
    _last_live_log_ts = now_ts
    _live_candidate_state_signature = None
    _live_candidate_state_count = 0
    save_state()
    return True


# ================= MAIN =================
def run_engine_forever():
    global _last_closed_candle_logged, _last_short_trap, _last_long_trap, _last_long_reversal, _last_short_reversal
    apply_mode_profile(MODE_PROFILE)
    setup_file_logging()
    print(f"[{now()}] BOT STARTED | V9.1 EARLY EXPANSION / SHORT SQUEEZE SYNC ENGINE | MODE={MODE_PROFILE}")
    load_state()
    startup_telegram_test()

    while True:
        try:
            candles = klines_closed(INTERVAL)
            htf = klines_closed(HTF_INTERVAL)

            if len(candles) < 210 or len(htf) < 210:
                print(f"[{now()}] Not enough candles")
                time.sleep(SLEEP)
                continue

            close = [x["c"] for x in candles]
            close_h = [x["c"] for x in htf]

            ef = ema(close, EMA_FAST)
            em = ema(close, EMA_MID)
            es = ema(close, EMA_SLOW)

            efh = ema(close_h, EMA_FAST)
            emh = ema(close_h, EMA_MID)
            esh = ema(close_h, EMA_SLOW)

            cur = candles[-1]
            prev = candles[-2]

            prune_memory(cur)

            ob = orderbook()
            oi_v = oi()
            prem = premium()
            atr_v = atr(candles)

            trend_s = ef[-1] < em[-1] < es[-1]
            trend_l = ef[-1] > em[-1] > es[-1]
            htf_s = efh[-1] < emh[-1] < esh[-1]
            htf_l = efh[-1] > emh[-1] > esh[-1]

            bias_side = current_bias_side(trend_s, trend_l, htf_s, htf_l)
            if update_bias_memory(cur, bias_side):
                save_state(force=True)
            maybe_reset_memory_on_bias_flip(cur, bias_side)

            checks_s, checks_l = build_checks(cur, prev, trend_s, trend_l, htf_s, htf_l, ob, oi_v, prem)
            extra = {
                "ob": round(ob, 4),
                "oi": oi_v,
                "premium": prem,
                "atr": atr_v,
                "range": cur["h"] - cur["l"],
                "body": abs(cur["c"] - cur["o"]),
            }

            if _last_closed_candle_logged != cur["close_time"]:
                _last_closed_candle_logged = cur["close_time"]

                traps_s = detect_short_trap(cur, prev, atr_v, ob, oi_v, prem, checks_s)
                traps_l = detect_long_trap(cur, prev, atr_v, ob, oi_v, prem, checks_l)

                if traps_s:
                    _last_short_trap = remember_trap("SHORT", cur, prev, traps_s)
                if traps_l:
                    _last_long_trap = remember_trap("LONG", cur, prev, traps_l)

                reversal = detect_reversal_after_short_trap(cur, ob, oi_v, prem, _last_short_trap)
                if reversal and reversal["side"] == "LONG":
                    _last_long_reversal = remember_reversal("LONG", cur, _last_short_trap, reversal["reasons"], reversal["entry_hint"], reversal["reclaim_level"])

                if not reversal:
                    reversal = detect_reversal_after_long_trap(cur, ob, oi_v, prem, _last_long_trap)
                    if reversal and reversal["side"] == "SHORT":
                        _last_short_reversal = remember_reversal("SHORT", cur, _last_long_trap, reversal["reasons"], reversal["entry_hint"], reversal["reclaim_level"])

                auto_entry = None
                if _last_long_reversal:
                    auto_entry = detect_auto_entry_after_short_trap(cur, ob, oi_v, prem, atr_v, _last_long_reversal)
                if not auto_entry and _last_short_reversal:
                    auto_entry = detect_auto_entry_after_long_trap(cur, ob, oi_v, prem, atr_v, _last_short_reversal)

                side, chosen_checks = choose_side(checks_s, checks_l)
                bias_text = market_bias_text(trend_s, trend_l, htf_s, htf_l)
                chosen_traps = traps_s if side == "SHORT" else traps_l
                fake_pump = detect_fake_pump(cur, prev, atr_v, ob, oi_v, prem, trend_l, htf_s)
                fake_dump = detect_fake_dump(cur, prev, atr_v, ob, oi_v, prem, trend_s, htf_l)
                fake_move = fake_pump or fake_dump
                flip_setup = detect_fake_dump_flip_long_setup(cur, prev, ob, oi_v, prem, atr_v, fake_move, checks_l)
                expansion_long = detect_early_expansion_long(cur, prev, ob, oi_v, prem, atr_v, checks_l, fake_move, reversal)
                squeeze_sync = detect_short_squeeze_sync(cur, prev, ob, oi_v, prem, atr_v, fake_move, checks_l, reversal, expansion_long)
                if squeeze_sync and not reversal:
                    reversal = {
                        "side": "LONG",
                        "label": squeeze_sync["label"],
                        "reasons": squeeze_sync["reasons"],
                        "entry_hint": squeeze_sync["entry_hint"],
                        "reclaim_level": squeeze_sync["reclaim_level"],
                    }
                elif flip_setup and not reversal:
                    reversal = {
                        "side": "LONG",
                        "label": flip_setup["label"],
                        "reasons": flip_setup["reasons"],
                        "entry_hint": flip_setup["entry_hint"],
                        "reclaim_level": flip_setup["reclaim_level"],
                    }

                prob_context_side = auto_entry["side"] if auto_entry else (flip_setup["side"] if flip_setup else side)
                prob_context_checks = checks_l if auto_entry and auto_entry["side"] == "LONG" else (checks_s if auto_entry and auto_entry["side"] == "SHORT" else chosen_checks)
                prob_context_traps = chosen_traps
                prob_context_reversal = reversal if (reversal and (not auto_entry or reversal["side"] == prob_context_side)) else None
                prob_context_auto = auto_entry if auto_entry else None
                prob_for_filter = probability_score(
                    prob_context_side,
                    prob_context_checks,
                    prob_context_traps,
                    prob_context_reversal,
                    prob_context_auto,
                    extra.get("ob"),
                    extra.get("oi"),
                    extra.get("premium"),
                )

                entry_filter = final_entry_filter(
                    auto_entry["side"], cur,
                    checks_l if auto_entry and auto_entry["side"] == "LONG" else checks_s,
                    extra, auto_entry, is_closed=True, prob_for_filter=prob_for_filter
                ) if auto_entry else {"checked": True, "passed": False, "reason": "ยังไม่มีสัญญาณเข้า", "fails": [], "prob": 0}

                timing_side = auto_entry["side"] if auto_entry else (reversal["side"] if reversal else side)
                commit_info = commit_check(timing_side, cur, auto_entry, atr_v, oi_v, prem)
                locked_auto_entry = auto_entry if (entry_filter.get("passed") and commit_info.get("commit")) else None
                shown_auto_entry = auto_entry if auto_entry else None

                fake_move = detect_fake_move(side, chosen_checks, cur, prev, ob, oi_v, prem)
                smash = detect_institutional_smash(cur, prev, ob, oi_v, prem, atr_v)
                probable_smash = detect_probable_smash(side, cur, prev, ob, oi_v, prem, atr_v, chosen_checks, fake_move)
                distribution_zone = detect_distribution_zone(side, cur, prev, atr_v, ef[-1], em[-1], es[-1], ob, oi_v, prem, fake_move)
                early_break_ctx = detect_early_break(side, cur, prev, ob, oi_v, prem, atr_v)
                probe_entry = detect_layered_probe_entry(side, prob_for_filter, probable_smash, early_break_ctx, distribution_zone)
                if fake_move and fake_move.get("active") and ENABLE_TELEGRAM_FAKE_MOVE_ALERT and can_send_alert(f"FAKE-{fake_move.get('type')}-{cur['close_time']}"):
                    send_telegram(build_special_event_message("FAKE_MOVE", cur, prev, extra, fake_move, side=side, checks=chosen_checks, traps=chosen_traps))
                if smash and smash.get("active") and ENABLE_TELEGRAM_SMASH_ALERT and can_send_alert(f"SMASH-{smash.get('side')}-{cur['close_time']}"):
                    send_telegram(build_special_event_message("SMASH", cur, prev, extra, smash, side=smash.get("side"), checks=chosen_checks, traps=chosen_traps))
                if probable_smash and probable_smash.get("active") and ENABLE_TELEGRAM_SMASH_ALERT and can_send_alert(f"PROBABLE-SMASH-{probable_smash.get('side')}-{cur['close_time']}"):
                    send_telegram(build_special_event_message("PROBABLE_SMASH", cur, prev, extra, probable_smash, side=probable_smash.get("side"), checks=chosen_checks, traps=chosen_traps))
                if flip_setup and flip_setup.get("active") and can_send_alert(f"FLIP-{flip_setup.get('side')}-{cur['close_time']}"):
                    send_telegram(build_special_event_message("FLIP", cur, prev, extra, flip_setup, side=flip_setup.get("side"), checks=checks_l, traps=traps_s))
                if squeeze_sync and squeeze_sync.get("active") and can_send_alert(f"SQUEEZE-{squeeze_sync.get('side')}-{cur['close_time']}"):
                    send_telegram(build_special_event_message("SQUEEZE", cur, prev, extra, squeeze_sync, side=squeeze_sync.get("side"), checks=checks_l, traps=traps_s))
                if probe_entry and probe_entry.get("active") and ENABLE_TELEGRAM_PROBE_ALERT and can_send_alert(f"PROBE-{probe_entry.get('side')}-{cur['close_time']}"):
                    send_telegram(build_special_event_message("LIVE", cur, prev, extra, probe_entry, side=probe_entry.get("side"), checks=chosen_checks, traps=chosen_traps))
                early_entry = detect_early_entry(side, chosen_checks, reversal, shown_auto_entry, chosen_traps, prob_for_filter)
                trap_exploit = detect_trap_exploit(side, chosen_traps, reversal, prob_for_filter)

                timing_mode, _ = entry_timing_mode(timing_side, cur, atr_v, reversal, auto_entry)
                oi_shift = oi_shift_text(timing_side, oi_v)
                premium_shift = premium_shift_text(timing_side, prem)

                if all(checks_s.values()):
                    print_block(f"[{now()}] 🔥 A+ SHORT @ {fmt_price(cur['c'])} | V8.2 STRUCTURED STATE")
                    print(f"CANDLE       : {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])} | CLOSED")
                    print("BIAS         : SHORT BIAS")
                    print("STATE        : SHORT confirmed")
                    print("ACTION       : Enter SHORT")
                    print(f"TRIGGER      : {price_trigger_hint('SHORT', prev)}")
                    print(f"FAST READ    : {compact_reason(checks_s)}")
                    print("=" * 100)
                    if ENABLE_A_PLUS_ALERT and can_send_alert(f"SHORT-{cur['close_time']}"):
                        send_telegram(build_alert_message("SHORT", cur["c"], checks_s, cur, prev, extra, traps_s))
                elif all(checks_l.values()):
                    print_block(f"[{now()}] 🔥 A+ LONG @ {fmt_price(cur['c'])} | V8.2 STRUCTURED STATE")
                    print(f"CANDLE       : {ts_to_str(cur['open_time'])} → {ts_to_str(cur['close_time'])} | CLOSED")
                    print("BIAS         : LONG BIAS")
                    print("STATE        : LONG confirmed")
                    print("ACTION       : Enter LONG")
                    print(f"TRIGGER      : {price_trigger_hint('LONG', prev)}")
                    print(f"FAST READ    : {compact_reason(checks_l)}")
                    print("=" * 100)
                    if ENABLE_A_PLUS_ALERT and can_send_alert(f"LONG-{cur['close_time']}"):
                        send_telegram(build_alert_message("LONG", cur["c"], checks_l, cur, prev, extra, traps_l))
                else:
                    print_log(
                        title=f"{side} DEBUG",
                        side=side,
                        bias_text=bias_text,
                        checks=chosen_checks,
                        extra=extra,
                        cur=cur,
                        prev=prev,
                        quality=signal_quality(chosen_checks),
                        traps=chosen_traps,
                        reversal=reversal,
                        auto_entry=shown_auto_entry,
                        entry_filter=entry_filter,
                        timing_mode=timing_mode,
                        oi_shift=oi_shift,
                        premium_shift=premium_shift,
                        commit_info=commit_info,
                        fake_move=fake_move,
                        early_entry=early_entry,
                        trap_exploit=trap_exploit,
                        smash=smash,
                        probable_smash=probable_smash,
                        probe_entry=probe_entry,
                        distribution_zone=distribution_zone,
                        flip_setup=flip_setup,
                        expansion_long=expansion_long,
                        squeeze_sync=squeeze_sync,
                        is_closed=True,
                    )

                    if locked_auto_entry and ENABLE_AUTO_ENTRY_ALERT and can_send_alert(f"AUTO-{locked_auto_entry['side']}-{cur['close_time']}"):
                        send_telegram(build_alert_message(side, cur["c"], chosen_checks, cur, prev, extra, chosen_traps, reversal, locked_auto_entry, entry_filter, commit_info))
                    elif reversal and ENABLE_REVERSAL_ALERT and can_send_alert(f"REV-{reversal['side']}-{cur['close_time']}"):
                        send_telegram(build_alert_message(side, cur["c"], chosen_checks, cur, prev, extra, chosen_traps, reversal, None, entry_filter, commit_info))
                    elif chosen_traps and ENABLE_TRAP_ALERT and can_send_alert(f"TRAP-{side}-{cur['close_time']}"):
                        send_telegram(build_alert_message(side, cur["c"], chosen_checks, cur, prev, extra, chosen_traps))

                save_state(force=True)

            open_cur = latest_open_candle(INTERVAL)
            if open_cur is not None:
                live_close = close[:-1] + [open_cur["c"]] if len(close) >= 1 else [open_cur["c"]]
                ef_live = ema(live_close, EMA_FAST)
                em_live = ema(live_close, EMA_MID)
                es_live = ema(live_close, EMA_SLOW)

                trend_s_live = ef_live[-1] < em_live[-1] < es_live[-1]
                trend_l_live = ef_live[-1] > em_live[-1] > es_live[-1]

                checks_s_live, checks_l_live = build_checks(open_cur, cur, trend_s_live, trend_l_live, htf_s, htf_l, ob, oi_v, prem)
                side_live, chosen_live_checks = choose_side(checks_s_live, checks_l_live)
                extra_live = {"ob": round(ob, 4), "oi": oi_v, "premium": prem, "atr": atr_v}

                traps_live_s = detect_short_trap(open_cur, cur, atr_v, ob, oi_v, prem, checks_s_live)
                traps_live_l = detect_long_trap(open_cur, cur, atr_v, ob, oi_v, prem, checks_l_live)
                chosen_live_traps = traps_live_s if side_live == "SHORT" else traps_live_l
                fake_pump_live = detect_fake_pump(open_cur, cur, atr_v, ob, oi_v, prem, trend_l_live, htf_s)
                fake_dump_live = detect_fake_dump(open_cur, cur, atr_v, ob, oi_v, prem, trend_s_live, htf_l)
                fake_move_live = fake_pump_live or fake_dump_live
                flip_setup_live = detect_fake_dump_flip_long_setup(open_cur, cur, ob, oi_v, prem, atr_v, fake_move_live, checks_l_live)
                expansion_long_live = detect_early_expansion_long(open_cur, cur, ob, oi_v, prem, atr_v, checks_l_live, fake_move_live, None)
                squeeze_sync_live = detect_short_squeeze_sync(open_cur, cur, ob, oi_v, prem, atr_v, fake_move_live, checks_l_live, None, expansion_long_live)

                reversal_live = detect_reversal_after_short_trap(open_cur, ob, oi_v, prem, _last_short_trap)
                if squeeze_sync_live and not reversal_live:
                    reversal_live = {
                        "side": "LONG",
                        "label": squeeze_sync_live["label"],
                        "reasons": squeeze_sync_live["reasons"],
                        "entry_hint": squeeze_sync_live["entry_hint"],
                        "reclaim_level": squeeze_sync_live["reclaim_level"],
                    }
                elif flip_setup_live and not reversal_live:
                    reversal_live = {
                        "side": "LONG",
                        "label": flip_setup_live["label"],
                        "reasons": flip_setup_live["reasons"],
                        "entry_hint": flip_setup_live["entry_hint"],
                        "reclaim_level": flip_setup_live["reclaim_level"],
                    }
                if not reversal_live:
                    reversal_live = detect_reversal_after_long_trap(open_cur, ob, oi_v, prem, _last_long_trap)

                auto_entry_live = None
                if _last_long_reversal:
                    auto_entry_live = detect_auto_entry_after_short_trap(open_cur, ob, oi_v, prem, atr_v, _last_long_reversal)
                if not auto_entry_live and _last_short_reversal:
                    auto_entry_live = detect_auto_entry_after_long_trap(open_cur, ob, oi_v, prem, atr_v, _last_short_reversal)

                prob_context_side_live = auto_entry_live["side"] if auto_entry_live else (flip_setup_live["side"] if flip_setup_live else side_live)
                prob_context_checks_live = checks_l_live if auto_entry_live and auto_entry_live["side"] == "LONG" else (checks_s_live if auto_entry_live and auto_entry_live["side"] == "SHORT" else chosen_live_checks)
                prob_context_traps_live = chosen_live_traps
                prob_context_reversal_live = reversal_live if (reversal_live and (not auto_entry_live or reversal_live["side"] == prob_context_side_live)) else None
                prob_context_auto_live = auto_entry_live if auto_entry_live else None
                prob_for_filter_live = probability_score(
                    prob_context_side_live,
                    prob_context_checks_live,
                    prob_context_traps_live,
                    prob_context_reversal_live,
                    prob_context_auto_live,
                    extra_live.get("ob"),
                    extra_live.get("oi"),
                    extra_live.get("premium"),
                )

                entry_filter_live = final_entry_filter(
                    auto_entry_live["side"], open_cur,
                    checks_l_live if auto_entry_live and auto_entry_live["side"] == "LONG" else checks_s_live,
                    extra_live, auto_entry_live, is_closed=False, prob_for_filter=prob_for_filter_live
                ) if auto_entry_live else {"checked": True, "passed": False, "reason": "ยังไม่มีสัญญาณเข้า", "fails": [], "prob": 0}

                timing_side_live = auto_entry_live["side"] if auto_entry_live else (reversal_live["side"] if reversal_live else side_live)
                commit_info_live = commit_check(timing_side_live, open_cur, auto_entry_live, atr_v, oi_v, prem)
                shown_auto_entry_live = auto_entry_live
                locked_auto_entry_live = auto_entry_live if (entry_filter_live.get("passed") and commit_info_live.get("commit")) else None

                fake_move_live = detect_fake_move(side_live, chosen_live_checks, open_cur, cur, ob, oi_v, prem)
                smash_live = detect_institutional_smash(open_cur, cur, ob, oi_v, prem, atr_v)
                probable_smash_live = detect_probable_smash(side_live, open_cur, cur, ob, oi_v, prem, atr_v, chosen_live_checks, fake_move_live)
                distribution_zone_live = detect_distribution_zone(side_live, open_cur, cur, atr_v, ef_live[-1], em_live[-1], es_live[-1], ob, oi_v, prem, fake_move_live)
                early_break_live_ctx = detect_early_break(side_live, open_cur, cur, ob, oi_v, prem, atr_v)
                probe_entry_live = detect_layered_probe_entry(side_live, prob_for_filter_live, probable_smash_live, early_break_live_ctx, distribution_zone_live)
                early_entry_live = detect_early_entry(side_live, chosen_live_checks, reversal_live, shown_auto_entry_live, chosen_live_traps, prob_for_filter_live)
                trap_exploit_live = detect_trap_exploit(side_live, chosen_live_traps, reversal_live, prob_for_filter_live)

                timing_mode_live, _ = entry_timing_mode(timing_side_live, open_cur, atr_v, reversal_live, auto_entry_live)
                oi_shift_live = oi_shift_text(timing_side_live, oi_v)
                premium_shift_live = premium_shift_text(timing_side_live, prem)

                bias_text_live = market_bias_text(trend_s_live, trend_l_live, htf_s, htf_l)
                if should_print_live_log(side_live, bias_text_live, chosen_live_checks, extra_live, open_cur, cur, chosen_live_traps, reversal_live, shown_auto_entry_live, fake_move_live, smash_live, probable_smash_live, probe_entry_live, distribution_zone_live):
                    print_log(
                        title="LIVE OPEN-CANDLE MONITOR",
                        side=side_live,
                        bias_text=bias_text_live,
                        checks=chosen_live_checks,
                        extra=extra_live,
                        cur=open_cur,
                        prev=cur,
                        quality=signal_quality(chosen_live_checks),
                        traps=chosen_live_traps,
                        reversal=reversal_live,
                        auto_entry=shown_auto_entry_live,
                        entry_filter=entry_filter_live,
                        timing_mode=timing_mode_live,
                        oi_shift=oi_shift_live,
                        premium_shift=premium_shift_live,
                        commit_info=commit_info_live,
                        fake_move=fake_move_live,
                        early_entry=early_entry_live,
                        trap_exploit=trap_exploit_live,
                        smash=smash_live,
                        probable_smash=probable_smash_live,
                        probe_entry=probe_entry_live,
                        distribution_zone=distribution_zone_live,
                        flip_setup=flip_setup_live,
                        expansion_long=expansion_long_live,
                        squeeze_sync=squeeze_sync_live,
                        is_closed=False,
                    )

                    if locked_auto_entry_live and ENABLE_AUTO_ENTRY_ALERT and can_send_alert(f"LIVE-AUTO-{locked_auto_entry_live['side']}-{open_cur['open_time']}"):
                        send_telegram(build_alert_message(side_live, open_cur["c"], chosen_live_checks, open_cur, cur, extra_live, chosen_live_traps, reversal_live, locked_auto_entry_live, entry_filter_live, commit_info_live))
                    maybe_send_live_summary(
                        side_live, open_cur, cur, chosen_live_checks, extra_live, chosen_live_traps,
                        reversal_live, shown_auto_entry_live, fake_move_live, smash_live, probable_smash_live,
                        flip_setup_live, squeeze_sync_live,
                    )

            time.sleep(SLEEP)

        except KeyboardInterrupt:
            print(f"[{now()}] STOPPED BY USER")
            save_state(force=True)
            raise
        except Exception as e:
            print(f"[{now()}] ERROR: {e}")
            save_state(force=True)
            time.sleep(5)


if __name__ == "__main__":
    run_engine_forever()
