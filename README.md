# BTC Bot V9.2.2 Telegram Backup Only + Railway Web Dashboard

ชุดนี้ต่อยอดจาก V9.2.1 โดยทำให้เป็น **production-ready แบบ Telegram backup only**
เพื่อหลีกเลี่ยงการใช้ Google Drive ส่วนตัวและลดความเสี่ยงด้าน security

## มีอะไรในชุดนี้
- `app.py` = Flask dashboard + bot supervisor + live log + Telegram backup manager
- `engine.py` = bot engine
- `requirements.txt` = เหลือเฉพาะ dependency ที่จำเป็น
- `railway.toml` / `Procfile` = พร้อม deploy บน Railway

## จุดเด่นของ V9.2.2
- ตัด Google Drive backup ออกทั้งหมด
- บังคับสร้างไฟล์ log/state ตั้งแต่เริ่มระบบ
- trigger backup ทันทีเมื่อ log อัปเดต
- หน้า dashboard แสดงสถานะ Telegram backup อย่างเดียว ชัดขึ้น
- ลด dependency และ config ที่ไม่จำเป็น

## Environment Variables ที่แนะนำ
### พื้นฐาน
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

## ตัวแปรที่ไม่ต้องใช้แล้ว
ลบออกได้เลยถ้ามีอยู่ใน Railway:
- `ENABLE_GDRIVE_BACKUP`
- `GDRIVE_FOLDER_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_SERVICE_ACCOUNT_FILE`

## Railway Deploy แบบเร็ว
1. Push โฟลเดอร์นี้ขึ้น GitHub
2. Railway > New Project > Deploy from GitHub Repo
3. ตั้ง Environment Variables ตามด้านบน
4. Deploy / Redeploy

## หน้าใช้งาน
- `/` = dashboard
- `/health` = healthcheck
- `/api/status` = bot + backup status
- `/api/logs` = log ล่าสุด
- `/api/logs/<filename>` = อ่าน log รายวัน
- `/download/<filename>` = ดาวน์โหลดไฟล์ log

## เช็กว่าทำงานแล้วหรือยัง
ใน `/health` ควรเห็นประมาณนี้:
- `status = running`
- `backup.telegram.last_file` มีค่า
- `backup.telegram.last_success_at` มีค่า
- `backup.last_error = null` หรือไม่มี error ใหม่

## หมายเหตุ
ถ้า Railway account ของคุณไม่มี Volume ให้ใช้ ระบบยังรันได้ด้วย `./data`
แต่ถ้า service restart ข้อมูล local อาจหายได้ ดังนั้น Telegram backup คือ safety layer หลักของ V9.2.2
