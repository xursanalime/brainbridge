"""
backup.py — PostgreSQL ↔ JSON backup/restore moduli.

Vazifalar:
  1. startup: PG bo'sh + JSON mavjud → JSON dan PG ga tiklash
  2. scheduler: har 6 soatda PG → JSON backup
"""
import json, os, logging, threading, time
from datetime import datetime

BACKUP_FILE  = os.path.join(os.path.dirname(__file__), "words.json")
INTERVAL_SEC = 6 * 3600   # 6 soat
log = logging.getLogger(__name__)


def _connect(database_url: str):
    import psycopg2
    return psycopg2.connect(database_url)


# ── PG → JSON ─────────────────────────────────────────────────────────────────

def backup(database_url: str):
    """PostgreSQL → words.json ga barcha so'zlarni saqlaydi."""
    try:
        conn = _connect(database_url)
        cur  = conn.cursor()
        cur.execute("""
            SELECT user_id, uz, eng, box,
                   next_review::text, created_at::text
            FROM words
        """)
        rows = cur.fetchall()
        conn.close()

        data = {
            "backup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count":       len(rows),
            "words": [
                {
                    "user_id":     uid,
                    "uz":          uz,
                    "eng":         eng,
                    "box":         box,
                    "next_review": nr,
                    "created_at":  ca,
                }
                for uid, uz, eng, box, nr, ca in rows
            ]
        }

        # Avval vaqtinchalik faylga yozib, keyin almashtir (atomic)
        tmp = BACKUP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, BACKUP_FILE)

        log.info(f"✅ Backup saqlandi: {len(rows)} ta so'z → {BACKUP_FILE}")
    except Exception as e:
        log.error(f"❌ Backup xatosi: {e}")


# ── JSON → PG ─────────────────────────────────────────────────────────────────

def restore_if_needed(database_url: str):
    """
    Startup da chaqiriladi.
    Agar PG bo'sh bo'lsa va words.json mavjud bo'lsa → JSON dan PG ga tiklaydi.
    """
    if not os.path.exists(BACKUP_FILE):
        log.info("words.json topilmadi — tiklash kerak emas.")
        return

    try:
        conn = _connect(database_url)
        cur  = conn.cursor()

        # PG da nechta so'z bor?
        cur.execute("SELECT COUNT(*) FROM words")
        pg_count = cur.fetchone()[0]

        if pg_count > 0:
            log.info(f"PG da {pg_count} ta so'z mavjud — tiklash kerak emas.")
            conn.close()
            return

        # PG bo'sh — JSON dan tiklash
        with open(BACKUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        words       = data.get("words", [])
        backup_time = data.get("backup_time", "noma'lum")

        if not words:
            log.info("JSON backup bo'sh — tiklash kerak emas.")
            conn.close()
            return

        log.info(f"PG bo'sh! JSON backupdan ({backup_time}) {len(words)} ta so'z tiklanmoqda...")

        for w in words:
            cur.execute("""
                INSERT INTO words (user_id, uz, eng, box, next_review, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, uz) DO NOTHING
            """, (
                w["user_id"], w["uz"], w["eng"],
                w.get("box", 0),
                w.get("next_review"),
                w.get("created_at"),
            ))

        conn.commit()
        conn.close()
        log.info(f"✅ Tiklash tugadi: {len(words)} ta so'z JSON → PG ga yuklandi.")

    except Exception as e:
        log.error(f"❌ Tiklash xatosi: {e}")


# ── SCHEDULER ─────────────────────────────────────────────────────────────────

def start_scheduler(database_url: str):
    """
    Background daemon thread: har 6 soatda PG → JSON backup qiladi.
    Bot bilan birga ishga tushadi, to'xtatilmaydi.
    """
    def _run():
        log.info(f"🕐 Backup scheduler ishga tushdi (har {INTERVAL_SEC//3600} soatda).")
        while True:
            time.sleep(INTERVAL_SEC)
            log.info("📦 Rejalashtirilgan backup boshlanmoqda...")
            backup(database_url)

    t = threading.Thread(target=_run, daemon=True, name="BackupScheduler")
    t.start()
    log.info("🟢 BackupScheduler thread ishga tushdi.")
