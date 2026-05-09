"""
backup.py — words.json uchun avtomatik zaxira moduli.
Har 6 soatda words.json ni words_backup.json ga ko'chiradi.
"""
import json, os, logging, threading, time, shutil
from datetime import datetime

DATA_FILE   = os.path.join(os.path.dirname(__file__), "words.json")
BACKUP_FILE = os.path.join(os.path.dirname(__file__), "words_backup.json")
INTERVAL_SEC = 6 * 3600
log = logging.getLogger(__name__)


def backup():
    """words.json → words_backup.json (atomic)."""
    if not os.path.exists(DATA_FILE):
        log.info("📭 words.json topilmadi — backup kerak emas.")
        return
    try:
        tmp = BACKUP_FILE + ".tmp"
        shutil.copy2(DATA_FILE, tmp)
        os.replace(tmp, BACKUP_FILE)
        size = os.path.getsize(BACKUP_FILE)
        log.info(f"✅ Backup saqlandi → words_backup.json ({size} bytes) [{datetime.now().strftime('%H:%M:%S')}]")
    except Exception as e:
        log.error(f"❌ Backup xatosi: {e}")


def start_scheduler():
    """Background daemon: startup da bir marta + har 6 soatda backup."""
    def _run():
        log.info(f"🕐 Backup scheduler ishga tushdi (har {INTERVAL_SEC//3600} soatda).")
        backup()  # ✅ FIX: startup da darhol bir marta bajaradi
        while True:
            time.sleep(INTERVAL_SEC)
            log.info("📦 Rejalashtirilgan backup boshlanmoqda...")
            backup()

    t = threading.Thread(target=_run, daemon=True, name="BackupScheduler")
    t.start()
    log.info("🟢 BackupScheduler thread ishga tushdi.")
