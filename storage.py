import os, logging
from datetime import datetime, timedelta, timezone
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
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 20, DATABASE_URL)
        log.info("✅ PostgreSQL ulangan.")
    except Exception as e:
        log.error(f"❌ PostgreSQL ulanish xatosi: {e}")
        _pool = None


def _db(query: str, params=None, fetch=None, commit=True):
    """Thread-safe database query executor with proper error handling."""
    if not _pool:
        return None
    conn = None
    try:
        conn = _pool.getconn()
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if commit:
                conn.commit()
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return cur.rowcount
    except Exception as e:
        if conn and commit:
            try:
                conn.rollback()
            except Exception:
                pass
        log.error(f"DB xato: {e} | Query: {query[:100]}")
        return None
    finally:
        if conn:
            try:
                _pool.putconn(conn)
            except Exception:
                pass


# ── INIT TABLES ───────────────────────────────────────────────────────────────
def init_db():
    if not _pool:
        return
    _db("""CREATE TABLE IF NOT EXISTS words(
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        uz TEXT NOT NULL,
        eng TEXT NOT NULL,
        box INTEGER DEFAULT 0,
        next_review TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE(user_id, uz))""")
    _db("CREATE INDEX IF NOT EXISTS idx_u ON words(user_id)")
    _db("CREATE INDEX IF NOT EXISTS idx_r ON words(user_id, box, next_review)")

    # Bloklangan userlar jadvali
    _db("""CREATE TABLE IF NOT EXISTS blocked_users(
        user_id BIGINT PRIMARY KEY,
        blocked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())""")

    # Eslatma holati (RAM o'rniga DB da)
    _db("""CREATE TABLE IF NOT EXISTS notification_log(
        user_id BIGINT NOT NULL,
        notified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY(user_id))""")


init_db()


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _now():
    """UTC vaqtni qaytaradi."""
    return datetime.now(timezone.utc)


def next_review_date(box: int) -> datetime:
    return _now() + timedelta(days=BOX_DAYS.get(box, 1))


def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "user_id": row[1], "uz": row[2], "eng": row[3],
        "box": row[4], "next_review": row[5], "created_at": row[6]
    }


# ── CRUD ──────────────────────────────────────────────────────────────────────
def get_all_words(uid: int) -> list:
    rows = _db(
        "SELECT id, user_id, uz, eng, box, next_review, created_at "
        "FROM words WHERE user_id=%s ORDER BY created_at DESC",
        (uid,), fetch="all"
    )
    if not rows:
        return []
    return [_row_to_dict(r) for r in rows]


def get_word_by_id(uid: int, word_id: int) -> dict | None:
    r = _db(
        "SELECT id, user_id, uz, eng, box, next_review, created_at "
        "FROM words WHERE user_id=%s AND id=%s",
        (uid, word_id), fetch="one"
    )
    return _row_to_dict(r) if r else None


def get_random_eng_words(uid: int, exclude_id: int, limit: int = 10) -> list:
    """Test uchun noto'g'ri variantlarni olish (samarali query)."""
    rows = _db(
        "SELECT eng FROM words WHERE user_id=%s AND id != %s "
        "ORDER BY RANDOM() LIMIT %s",
        (uid, exclude_id, limit), fetch="all"
    )
    if not rows:
        return []
    return [r[0].split(",")[0].strip() for r in rows]


def add_word(uid: int, uz: str, eng: str) -> str:
    """'added' | 'updated' | 'skipped'"""
    # Validatsiya: juda uzun so'zlarni cheklash
    if len(uz) > 100 or len(eng) > 200:
        return "skipped"

    row = _db("SELECT id, eng FROM words WHERE user_id=%s AND uz=%s", (uid, uz), fetch="one")
    if row:
        wid, old_eng = row
        old_syns = [x.strip() for x in old_eng.split(",")]
        new_syns = [x.strip() for x in eng.split(",")]
        merged = old_syns[:]
        added_any = False
        for s in new_syns:
            if s and s not in merged:
                merged.append(s)
                added_any = True
        if added_any:
            new_eng_str = ", ".join(merged)
            if len(new_eng_str) > 200:
                return "skipped"
            _db("UPDATE words SET eng=%s, box=0, next_review=NOW() WHERE id=%s", (new_eng_str, wid))
            return "updated"
        return "skipped"

    _db("INSERT INTO words (user_id, uz, eng, box, next_review) VALUES (%s, %s, %s, 0, NOW())",
        (uid, uz, eng))
    return "added"


def update_word_eng(uid: int, word_id: int, new_eng: str):
    if len(new_eng) > 200:
        return
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
    _db("UPDATE words SET box=%s, next_review=%s WHERE id=%s AND user_id=%s",
        (new_box, nxt, word_id, uid))


# ── QUERY HELPERS ─────────────────────────────────────────────────────────────
def words_new(uid: int) -> list:
    rows = _db(
        "SELECT id, user_id, uz, eng, box, next_review, created_at "
        "FROM words WHERE user_id=%s AND box=0",
        (uid,), fetch="all"
    )
    return [_row_to_dict(r) for r in rows] if rows else []


def words_in_box(uid: int, box: int, due_only=True) -> list:
    if due_only:
        rows = _db(
            "SELECT id, user_id, uz, eng, box, next_review, created_at "
            "FROM words WHERE user_id=%s AND box=%s AND next_review <= NOW()",
            (uid, box), fetch="all"
        )
    else:
        rows = _db(
            "SELECT id, user_id, uz, eng, box, next_review, created_at "
            "FROM words WHERE user_id=%s AND box=%s",
            (uid, box), fetch="all"
        )
    return [_row_to_dict(r) for r in rows] if rows else []


def words_due(uid: int) -> list:
    rows = _db(
        "SELECT id, user_id, uz, eng, box, next_review, created_at "
        "FROM words WHERE user_id=%s AND box>0 AND next_review <= NOW()",
        (uid,), fetch="all"
    )
    return [_row_to_dict(r) for r in rows] if rows else []


def count_box(uid: int, box: int) -> int:
    r = _db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s", (uid, box), fetch="one")
    return r[0] if r else 0


def count_due_box(uid: int, box: int) -> int:
    r = _db(
        "SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s AND next_review <= NOW()",
        (uid, box), fetch="one"
    )
    return r[0] if r else 0


def next_due_time(uid: int) -> datetime | None:
    r = _db("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box>0", (uid,), fetch="one")
    return r[0] if r else None


def next_due_time_box(uid: int, box: int) -> datetime | None:
    r = _db("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box=%s", (uid, box), fetch="one")
    return r[0] if r else None


def search_words(uid: int, query: str) -> list:
    q = f"%{query.lower()}%"
    rows = _db(
        "SELECT id, user_id, uz, eng, box, next_review, created_at "
        "FROM words WHERE user_id=%s AND (LOWER(uz) LIKE %s OR LOWER(eng) LIKE %s) "
        "ORDER BY uz LIMIT 20",
        (uid, q, q), fetch="all"
    )
    return [_row_to_dict(r) for r in rows] if rows else []


def stats(uid: int) -> dict:
    r = _db(
        """SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE box = 0),
            COUNT(*) FILTER (WHERE box = 5),
            COUNT(*) FILTER (WHERE box > 0 AND next_review <= NOW())
        FROM words WHERE user_id=%s""",
        (uid,), fetch="one"
    )
    if not r:
        return {"total": 0, "new": 0, "done": 0, "due": 0, "boxes": {}}

    total, new_w, done, due = r

    boxes = {}
    box_rows = _db(
        "SELECT box, COUNT(*) FROM words WHERE user_id=%s AND box BETWEEN 1 AND 5 GROUP BY box",
        (uid,), fetch="all"
    )
    if box_rows:
        for box_num, cnt in box_rows:
            boxes[box_num] = cnt
    for i in range(1, 6):
        boxes.setdefault(i, 0)

    return {
        "total": total,
        "new": new_w,
        "done": done,
        "due": due,
        "boxes": boxes,
    }


# ── REMINDER HELPERS ──────────────────────────────────────────────────────────
def get_users_with_due_words() -> list:
    """Takrorlash vaqti yetgan so'zlari bor foydalanuvchilarni qaytaradi.
    Bloklangan userlarni chiqarib tashlaydi.
    Har bir element: (user_id, due_count)"""
    rows = _db(
        """SELECT w.user_id, COUNT(*)
        FROM words w
        LEFT JOIN blocked_users b ON w.user_id = b.user_id
        WHERE w.box > 0 AND w.next_review <= NOW() AND b.user_id IS NULL
        GROUP BY w.user_id""",
        fetch="all"
    )
    return rows if rows else []


def is_recently_notified(uid: int, cooldown_minutes: int = 60) -> bool:
    """User yaqinda eslatma olganmi tekshiradi."""
    r = _db(
        "SELECT notified_at FROM notification_log WHERE user_id=%s",
        (uid,), fetch="one"
    )
    if not r or not r[0]:
        return False
    diff = _now() - r[0].replace(tzinfo=timezone.utc) if r[0].tzinfo is None else _now() - r[0]
    return diff.total_seconds() < cooldown_minutes * 60


def mark_notified(uid: int):
    """Userni eslatma oldi deb belgilaydi."""
    _db(
        """INSERT INTO notification_log (user_id, notified_at)
        VALUES (%s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET notified_at = NOW()""",
        (uid,)
    )


# ── BLOCKED USERS ─────────────────────────────────────────────────────────────
def add_blocked_user(uid: int):
    """Botni bloklagan userni saqlaydi."""
    _db(
        "INSERT INTO blocked_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (uid,)
    )


def remove_blocked_user(uid: int):
    """User qayta /start bersa, blokdan chiqaradi."""
    _db("DELETE FROM blocked_users WHERE user_id=%s", (uid,))


def is_blocked(uid: int) -> bool:
    r = _db("SELECT 1 FROM blocked_users WHERE user_id=%s", (uid,), fetch="one")
    return r is not None
