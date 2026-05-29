import os, logging
from datetime import datetime, timedelta
import psycopg2
from psycopg2 import pool

log = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")
BOX_DAYS = {0: 0, 1: 1, 2: 3, 3: 7, 4: 14, 5: 30}

# ── POSTGRESQL POOL ───────────────────────────────────────────────────────────
if not DATABASE_URL:
    log.warning("⚠️ DATABASE_URL o'rnatilmagan! DB ishlamaydi.")
    _pool = None
else:
    try:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL)
        log.info("✅ PostgreSQL ulangan.")
    except Exception as e:
        log.error(f"❌ PostgreSQL ulanish xatosi: {e}")
        _pool = None

def _db(query: str, params=None, fetch=None, commit=True):
    if not _pool: return None
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if commit: conn.commit()
            if fetch == "one": return cur.fetchone()
            if fetch == "all": return cur.fetchall()
            return cur.rowcount
    except Exception as e:
        if commit: conn.rollback()
        log.error(f"DB xato: {e}")
        raise e
    finally:
        _pool.putconn(conn)

def _scalar(query: str, params=None, default=0):
    """COUNT/MIN kabi bitta qiymat qaytaruvchi so'rovlar uchun xavfsiz yordamchi.
    DB ulanmagan bo'lsa (yoki natija bo'lmasa) `default` qaytaradi."""
    r = _db(query, params, fetch="one")
    if not r or r[0] is None:
        return default
    return r[0]

# ── INIT TABLES ───────────────────────────────────────────────────────────────
def init_db():
    if not _pool: return
    _db("""CREATE TABLE IF NOT EXISTS words(
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        uz TEXT NOT NULL,
        eng TEXT NOT NULL,
        box INTEGER DEFAULT 0,
        next_review TIMESTAMP DEFAULT NOW(),
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, uz))""")
    _db("CREATE INDEX IF NOT EXISTS idx_u ON words(user_id)")
    _db("CREATE INDEX IF NOT EXISTS idx_r ON words(user_id, box, next_review)")
    # Foydalanuvchilar + bildirishnoma sozlamalari
    _db("""CREATE TABLE IF NOT EXISTS users(
        user_id BIGINT PRIMARY KEY,
        first_name TEXT,
        notify BOOLEAN DEFAULT TRUE,
        last_notified TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW())""")

init_db()

# ── HELPERS ───────────────────────────────────────────────────────────────────
def next_review_date(box: int) -> datetime:
    return datetime.now() + timedelta(days=BOX_DAYS.get(box, 1))

def parse_synonyms(raw: str) -> list:
    """Vergul bilan ajratilgan sinonimlar satrini tozalangan ro'yxatga aylantiradi.

    - har bir elementni trim qiladi va ichki ortiqcha bo'shliqlarni siqadi
    - bo'sh elementlarni tashlab yuboradi  (mas: "allow, , permit" → ["allow", "permit"])
    - takrorlarni registrga bog'liqsiz (casefold) olib tashlaydi, tartibni saqlaydi
    - birinchi uchragan variantning yozilishini saqlab qoladi
    """
    if not raw:
        return []
    result, seen = [], set()
    for part in raw.split(","):
        token = " ".join(part.split())  # trim + ichki bo'shliqlarni bittaga keltirish
        if not token:
            continue
        key = token.casefold()
        if key not in seen:
            seen.add(key)
            result.append(token)
    return result

def merge_synonyms(old_raw: str, new_raw: str):
    """Eski va yangi sinonimlarni birlashtiradi (registrga bog'liqsiz, tartib saqlanadi).

    Qaytaradi: (birlashtirilgan_satr, nechta_yangi_qo'shildi)
    """
    merged = parse_synonyms(old_raw)
    seen = {s.casefold() for s in merged}
    added = 0
    for s in parse_synonyms(new_raw):
        if s.casefold() not in seen:
            merged.append(s)
            seen.add(s.casefold())
            added += 1
    return ", ".join(merged), added

def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "user_id": row[1], "uz": row[2], "eng": row[3],
        "box": row[4], "next_review": row[5], "created_at": row[6]
    }

# ── CRUD ──────────────────────────────────────────────────────────────────────
def get_all_words(uid: int) -> list:
    rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s ORDER BY created_at DESC", (uid,), fetch="all")
    if not rows: return []
    return [_row_to_dict(r) for r in rows]

def get_word_by_id(uid: int, word_id: int) -> dict | None:
    r = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND id=%s", (uid, word_id), fetch="one")
    return _row_to_dict(r) if r else None

def add_word(uid: int, uz: str, eng: str) -> str:
    """'added' | 'updated' | 'skipped'"""
    # Yangi sinonimlarni tozalaymiz (bo'sh va takror elementlardan xoli)
    clean_new = parse_synonyms(eng)
    if not clean_new:
        return "skipped"

    row = _db("SELECT id, eng, box FROM words WHERE user_id=%s AND uz=%s", (uid, uz), fetch="one")
    if row:
        wid, old_eng, box = row
        merged_str, added = merge_synonyms(old_eng, eng)
        if added == 0:
            return "skipped"
        # Faqat eng (tarjima) ni yangilaymiz — o'rganish jarayoni (box/next_review) saqlanadi.
        # Yangi so'z (box=0) bo'lsa o'sha holatda qoladi; o'rganilgan so'z darajasini yo'qotmaydi.
        _db("UPDATE words SET eng=%s WHERE id=%s", (merged_str, wid))
        return "updated"

    _db("INSERT INTO words (user_id, uz, eng, box, next_review) VALUES (%s, %s, %s, 0, NOW())",
        (uid, uz, ", ".join(clean_new)))
    return "added"

def update_word_eng(uid: int, word_id: int, new_eng: str):
    """Tahrirlash: tarjimani to'liq almashtiradi (tozalangan, takrorsiz holda)."""
    cleaned = ", ".join(parse_synonyms(new_eng))
    _db("UPDATE words SET eng=%s WHERE id=%s AND user_id=%s", (cleaned, word_id, uid))

def delete_word(uid: int, word_id: int) -> str | None:
    r = _db("SELECT uz FROM words WHERE id=%s AND user_id=%s", (word_id, uid), fetch="one")
    if r:
        _db("DELETE FROM words WHERE id=%s AND user_id=%s", (word_id, uid))
        return r[0]
    return None

def delete_all(uid: int) -> int:
    count = _db("DELETE FROM words WHERE user_id=%s", (uid,))
    return count if count is not None else 0

def update_box(uid: int, word_id: int, new_box: int):
    # next_review ni DB ning NOW() iga asoslaymiz — barcha vaqtlar bitta manbadan
    # (server vaqti) keladi, shunda taqqoslash (next_review <= NOW()) izchil bo'ladi.
    days = BOX_DAYS.get(new_box, 1)
    _db("UPDATE words SET box=%s, next_review = NOW() + make_interval(days => %s) WHERE id=%s AND user_id=%s",
        (new_box, days, word_id, uid))

# ── QUERY HELPERS ─────────────────────────────────────────────────────────────
def words_new(uid: int) -> list:
    rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND box=0", (uid,), fetch="all")
    return [_row_to_dict(r) for r in rows] if rows else []

def words_in_box(uid: int, box: int, due_only=True) -> list:
    if due_only:
        rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND box=%s AND next_review <= NOW()", (uid, box), fetch="all")
    else:
        rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND box=%s", (uid, box), fetch="all")
    return [_row_to_dict(r) for r in rows] if rows else []

def words_due(uid: int) -> list:
    rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND box>0 AND next_review <= NOW()", (uid,), fetch="all")
    return [_row_to_dict(r) for r in rows] if rows else []

def count_box(uid: int, box: int) -> int:
    return _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s", (uid, box))

def count_due_box(uid: int, box: int) -> int:
    return _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s AND next_review <= NOW()", (uid, box))

def next_due_time(uid: int) -> datetime | None:
    return _scalar("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box>0", (uid,), default=None)

def next_due_time_box(uid: int, box: int) -> datetime | None:
    return _scalar("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box=%s", (uid, box), default=None)

def seconds_until_due(uid: int) -> float | None:
    """Eng yaqin takrorlashgacha qolgan soniyalar (DB ichida hisoblanadi —
    vaqt mintaqasi muammosisiz). None — tayyor so'z yo'q."""
    return _scalar(
        "SELECT EXTRACT(EPOCH FROM (MIN(next_review) - NOW())) "
        "FROM words WHERE user_id=%s AND box>0", (uid,), default=None)

def seconds_until_due_box(uid: int, box: int) -> float | None:
    """Berilgan qutidagi eng yaqin takrorlashgacha qolgan soniyalar."""
    return _scalar(
        "SELECT EXTRACT(EPOCH FROM (MIN(next_review) - NOW())) "
        "FROM words WHERE user_id=%s AND box=%s", (uid, box), default=None)

def search_words(uid: int, query: str) -> list:
    q = f"%{query.lower()}%"
    rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND (LOWER(uz) LIKE %s OR LOWER(eng) LIKE %s) ORDER BY uz LIMIT 20", (uid, q, q), fetch="all")
    return [_row_to_dict(r) for r in rows] if rows else []

def stats(uid: int) -> dict:
    total = _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s", (uid,))
    new_w = _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=0", (uid,))
    done = _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=5", (uid,))
    due = _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s AND box>0 AND next_review <= NOW()", (uid,))
    
    boxes = {}
    for i in range(1, 6):
        boxes[i] = _scalar("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s", (uid, i))
        
    return {
        "total": total,
        "new": new_w,
        "done": done,
        "due": due,
        "boxes": boxes,
    }

# ── USERS / BILDIRISHNOMA ─────────────────────────────────────────────────────
def register_user(uid: int, first_name: str = None):
    """Foydalanuvchini ro'yxatga oladi yoki ismini yangilaydi (notify holatiga tegmaydi)."""
    _db("""INSERT INTO users (user_id, first_name) VALUES (%s, %s)
           ON CONFLICT (user_id) DO UPDATE SET first_name = EXCLUDED.first_name""",
        (uid, first_name))

def get_notify(uid: int) -> bool:
    """Foydalanuvchining bildirishnoma sozlamasi (default: yoqilgan)."""
    r = _db("SELECT notify FROM users WHERE user_id=%s", (uid,), fetch="one")
    return bool(r[0]) if r else True

def set_notify(uid: int, enabled: bool):
    """Bildirishnomani yoqadi/o'chiradi (foydalanuvchi yo'q bo'lsa yaratadi)."""
    _db("""INSERT INTO users (user_id, notify) VALUES (%s, %s)
           ON CONFLICT (user_id) DO UPDATE SET notify = EXCLUDED.notify""",
        (uid, enabled))

def mark_notified(uid: int):
    """Oxirgi bildirishnoma vaqtini hozirgi vaqtga belgilaydi (spamning oldini olish)."""
    _db("UPDATE users SET last_notified = NOW() WHERE user_id=%s", (uid,))

def users_to_notify(cooldown_hours: int = 12) -> list:
    """Bildirishnoma yuborilishi kerak bo'lgan foydalanuvchilar ro'yxati.

    Shart:
    - notify = TRUE
    - kamida 1 ta muddati kelgan so'z bor (box>0 AND next_review <= NOW())
    - oxirgi bildirishnomadan beri `cooldown_hours` soat o'tgan (yoki hech qachon yuborilmagan)

    Qaytaradi: [(user_id, first_name, due_count), ...]
    """
    rows = _db("""
        SELECT u.user_id, u.first_name, COUNT(w.id) AS due_count
        FROM users u
        JOIN words w
          ON w.user_id = u.user_id
         AND w.box > 0
         AND w.next_review <= NOW()
        WHERE u.notify = TRUE
          AND (u.last_notified IS NULL
               OR u.last_notified <= NOW() - make_interval(hours => %s))
        GROUP BY u.user_id, u.first_name
        HAVING COUNT(w.id) > 0
    """, (cooldown_hours,), fetch="all")
    return [(r[0], r[1], r[2]) for r in rows] if rows else []
