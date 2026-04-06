# BTC Bot V9.3 Smart Dashboard

Telegram-backup-only dashboard package.

## Main upgrades
- Smart summary cards: Bias, Phase, Grade, Event, Verdict, Trigger
- Live log with SSE + polling fallback
- Stronger status API and health endpoint
- Daily log dropdown and download
- Railway-friendly SSE headers and bootstrap files

## Required Railway variables
RUN_BOT=true
DATA_DIR=./data
LOG_DIR=./data/logs
STATE_FILE=./data/btc_state.json
BACKUP_STATE_FILE=./data/backup_state.json
ENABLE_TELEGRAM=true
TELEGRAM_TOKEN=...
CHAT_ID=...
ENABLE_BACKUP=true
ENABLE_TELEGRAM_BACKUP=true
TELEGRAM_BACKUP_CHAT_ID=...
BACKUP_INTERVAL_SEC=300


V9.3.6 hard refresh fix:
- Dashboard uses hard page refresh fallback every 5 seconds.
- Also polls /api/status and /api/logs every 2 seconds.
- Intended to work reliably on Railway/browser cache edge cases.
