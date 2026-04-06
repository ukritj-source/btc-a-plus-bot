# BTC Telegram Log Engine V10

เวอร์ชันนี้ตัด dashboard ออก แล้วรัน `engine.py` ตรงเพื่อส่งสัญญาณสำคัญไป Telegram

## จุดเด่น
- ใช้ core logic เดิมของ V9.4.2 ต่อเนื่อง
- เพิ่ม file logging ใน `data/logs/YYYY-MM-DD.log`
- ส่ง Telegram alert สำหรับ A+, trap, reversal, auto-entry, fake move, institutional smash, auto-flip, short squeeze
- ส่ง live snapshot เป็นระยะเมื่อมีบริบทสำคัญ

## Railway
ตั้ง start command เป็น `python engine.py` หรือใช้ Procfile ที่ให้มา


## V10.2
- Hard Decision Engine for Telegram checklist
- Decision states: ENTER / PREPARE / NO TRADE
- Important alerts remain enabled
