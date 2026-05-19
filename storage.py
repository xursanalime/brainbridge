import os, logging, threading
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

init_db()

# ── HELPERS ───────────────────────────────────────────────────────────────────
def next_review_date(box: int) -> datetime:
    return datetime.now() + timedelta(days=BOX_DAYS.get(box, 1))

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
    row = _db("SELECT id, eng FROM words WHERE user_id=%s AND uz=%s", (uid, uz), fetch="one")
    if row:
        wid, old_eng = row
        old_syns = [x.strip() for x in old_eng.split(",")]
        new_syns = [x.strip() for x in eng.split(",")]
        merged = old_syns[:]
        added_any = False
        for s in new_syns:
            if s not in merged:
                merged.append(s)
                added_any = True
        if added_any:
            new_eng_str = ", ".join(merged)
            _db("UPDATE words SET eng=%s, box=0, next_review=NOW() WHERE id=%s", (new_eng_str, wid))
            return "updated"
        return "skipped"
    
    _db("INSERT INTO words (user_id, uz, eng, box, next_review) VALUES (%s, %s, %s, 0, NOW())", (uid, uz, eng))
    return "added"

def update_word_eng(uid: int, word_id: int, new_eng: str):
    _db("UPDATE words SET eng=%s WHERE id=%s AND user_id=%s", (new_eng, word_id, uid))

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
    nxt = next_review_date(new_box)
    _db("UPDATE words SET box=%s, next_review=%s WHERE id=%s AND user_id=%s", (new_box, nxt, word_id, uid))

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
    r = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s", (uid, box), fetch="one")
    return r[0] if r else 0

def count_due_box(uid: int, box: int) -> int:
    r = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s AND next_review <= NOW()", (uid, box), fetch="one")
    return r[0] if r else 0

def next_due_time(uid: int) -> datetime | None:
    r = _db("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box>0", (uid,), fetch="one")
    return r[0] if r else None

def next_due_time_box(uid: int, box: int) -> datetime | None:
    r = _db("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box=%s", (uid, box), fetch="one")
    return r[0] if r else None

def search_words(uid: int, query: str) -> list:
    q = f"%{query.lower()}%"
    rows = _db("SELECT id, user_id, uz, eng, box, next_review, created_at FROM words WHERE user_id=%s AND (LOWER(uz) LIKE %s OR LOWER(eng) LIKE %s) ORDER BY uz LIMIT 20", (uid, q, q), fetch="all")
    return [_row_to_dict(r) for r in rows] if rows else []

def stats(uid: int) -> dict:
    total = _db("SELECT COUNT(*) FROM words WHERE user_id=%s", (uid,), fetch="one")[0]
    new_w = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=0", (uid,), fetch="one")[0]
    done = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=5", (uid,), fetch="one")[0]
    due = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box>0 AND next_review <= NOW()", (uid,), fetch="one")[0]
    
    boxes = {}
    for i in range(1, 6):
        boxes[i] = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s", (uid, i), fetch="one")[0]
        
    return {
        "total": total,
        "new": new_w,
        "done": done,
        "due": due,
        "boxes": boxes,
    }

def get_users_with_due_words() -> list:
    """Takrorlash vaqti yetgan so'zlari bor barcha foydalanuvchilarni qaytaradi.
    Har bir element: (user_id, due_count)"""
    rows = _db(
        "SELECT user_id, COUNT(*) FROM words WHERE box > 0 AND next_review <= NOW() GROUP BY user_id",
        fetch="all"
    )
    return rows if rows else []


def migrate_from_pg(database_url: str) -> int:
    # Artib PostgreSQL ga ulandik, JSON kerak emas. 
    return 0
