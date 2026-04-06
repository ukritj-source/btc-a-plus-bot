# BTC Bot V9.2 Backup System + Railway Web Dashboard

ชุดนี้ต่อยอดจาก V9.1 ที่คุณแนบมา โดยเพิ่ม **Backup System 2 ทางพร้อมกัน**:
- Backup log/state ไป **Telegram**
- Backup log/state ไป **Google Drive**
- ยังมี **web dashboard** สำหรับดู live log, daily log, bot status, และ backup status

## โครงสร้าง
- `app.py` = Flask dashboard + supervisor + SSE live log + backup manager
- `engine.py` = bot V9.1 ของคุณ
- `requirements.txt` = dependency สำหรับ Flask + Google Drive API
- `railway.toml` = config สำหรับ Railway
- `Procfile` = start command fallback

## V9.2 เพิ่มอะไรบ้าง
- เก็บ log เป็นไฟล์รายวันใน `LOG_DIR`
- backup ไฟล์ log ล่าสุด + state file เป็นรอบ ๆ
- backup เฉพาะตอนที่ไฟล์เปลี่ยนจริง เพื่อลดการยิงซ้ำ
- หน้า dashboard มีสถานะ backup ของ Telegram และ Google Drive
- เก็บสถานะการ backup ไว้ที่ `BACKUP_STATE_FILE`

## Environment Variables แนะนำ
### พื้นฐาน
- `PORT` = Railway ใส่ให้เอง
- `DATA_DIR=./data`
- `LOG_DIR=./data/logs`
- `STATE_FILE=./data/btc_state.json`
- `BACKUP_STATE_FILE=./data/backup_state.json`
- `RUN_BOT=true`
- `AUTO_RESTART=true`
- `BOT_RESTART_DELAY_SEC=5`
- `TIMEZONE_OFFSET=7`

### Telegram alert ของ bot
- `ENABLE_TELEGRAM=true`
- `TELEGRAM_TOKEN=...`
- `CHAT_ID=...`

### Telegram backup
- `ENABLE_BACKUP=true`
- `ENABLE_TELEGRAM_BACKUP=true`
- `TELEGRAM_BACKUP_CHAT_ID=...`  
  ถ้าไม่ใส่ จะ fallback ไปใช้ `CHAT_ID`
- `BACKUP_INTERVAL_SEC=300`

### Google Drive backup
- `ENABLE_GDRIVE_BACKUP=true`
- `GDRIVE_FOLDER_ID=...`
- ใช้อย่างใดอย่างหนึ่ง
  - `GOOGLE_SERVICE_ACCOUNT_JSON={...json...}`
  - หรือ `GOOGLE_SERVICE_ACCOUNT_FILE=/app/secret/service-account.json`

## วิธีเตรียม Google Drive Backup
1. สร้าง Google Cloud service account
2. เปิด Google Drive API
3. ดาวน์โหลด service account JSON
4. แชร์โฟลเดอร์ Google Drive ปลายทางให้ email ของ service account
5. เอา Folder ID มาใส่ใน `GDRIVE_FOLDER_ID`
6. เอา JSON ไปใส่ใน `GOOGLE_SERVICE_ACCOUNT_JSON`

## Railway Deploy แบบเร็ว
1. Push โฟลเดอร์นี้ขึ้น GitHub
2. Railway > New Project > Deploy from GitHub Repo
3. ตั้ง Environment Variables ตามด้านบน
4. Deploy

> หมายเหตุ: ถ้า account Railway ของคุณไม่มี Volume ให้ใช้ ตอนนี้ระบบนี้ยังรันได้ โดยใช้ `./data` ชั่วคราว แต่ถ้า service restart ข้อมูลใน local disk อาจหายได้ ดังนั้น backup ไป Telegram + Google Drive คือ safety layer หลักของ V9.2

## หน้าใช้งาน
- `/` = dashboard
- `/health` = healthcheck endpoint
- `/api/status` = bot + state + backup status
- `/api/logs` = tail log ล่าสุด
- `/api/logs/<filename>` = อ่าน log รายวัน
- `/download/<filename>` = ดาวน์โหลดไฟล์ log

## หมายเหตุสำคัญ
- Telegram backup จะส่งไฟล์ log ล่าสุด และ state file เมื่อไฟล์เปลี่ยน
- Google Drive backup จะ upsert ไฟล์ชื่อเดิมใน folder เดิม
- ถ้า backup ผิดพลาด หน้า dashboard จะเห็น error ล่าสุด
