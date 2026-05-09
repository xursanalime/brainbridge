"""
JSON-based storage layer — BrainBridge
Ma'lumotlar words.json faylida saqlanadi.
Format: { "user_id": { "next_id": int, "words": { "id": {...} } } }
"""
import json, os, threading, logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)
DATA_FILE = os.path.join(os.path.dirname(__file__), "words.json")
_lock = threading.RLock()
BOX_DAYS = {0: 0, 1: 1, 2: 3, 3: 7, 4: 14, 5: 30}

# ── IN-MEMORY CACHE ───────────────────────────────────────────────────────────
_cache: dict | None = None

def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.exists(DATA_FILE):
        _cache = {}
        return _cache
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            _cache = json.load(f)
        except json.JSONDecodeError:
            _cache = {}
    return _cache

def _save(data: dict):
    global _cache
    _cache = data
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def _user(data: dict, uid: int) -> dict:
    key = str(uid)
    if key not in data:
        data[key] = {"next_id": 1, "words": {}}
    return data[key]

# ── HELPERS ───────────────────────────────────────────────────────────────────
def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _dt(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return datetime.now()

def next_review_date(box: int) -> str:
    return (datetime.now() + timedelta(days=BOX_DAYS.get(box, 1))).strftime("%Y-%m-%dT%H:%M:%S")

# ── CRUD ──────────────────────────────────────────────────────────────────────
def get_all_words(uid: int) -> list:
    """[{id, uz, eng, box, next_review, created_at}]"""
    with _lock:
        data = _load()
        u = _user(data, uid)
        return [{"id": int(k), **v} for k, v in u["words"].items()]

def get_word_by_id(uid: int, word_id: int) -> dict | None:
    with _lock:
        data = _load()
        w = data.get(str(uid), {}).get("words", {}).get(str(word_id))
        if w:
            return {"id": word_id, **w}
        return None

def add_word(uid: int, uz: str, eng: str) -> str:
    """'added' | 'updated' | 'skipped'"""
    with _lock:
        data = _load()
        u = _user(data, uid)
        for w in u["words"].values():
            if w["uz"] == uz:
                old_syns = [x.strip() for x in w["eng"].split(",")]
                new_syns = [x.strip() for x in eng.split(",")]
                merged = old_syns[:]
                added_any = False
                for s in new_syns:
                    if s not in merged:
                        merged.append(s)
                        added_any = True
                if added_any:
                    w["eng"] = ", ".join(merged)
                    w["box"] = 0
                    w["next_review"] = _now_str()
                    _save(data)
                    return "updated"
                return "skipped"
        wid = str(u["next_id"])
        u["next_id"] += 1
        u["words"][wid] = {
            "uz": uz, "eng": eng, "box": 0,
            "next_review": _now_str(), "created_at": _now_str()
        }
        _save(data)
        return "added"

def update_word_eng(uid: int, word_id: int, new_eng: str):
    """So'z tarjimasini yangilaydi, qutilar o'zgarmaydi."""
    with _lock:
        data = _load()
        w = data.get(str(uid), {}).get("words", {}).get(str(word_id))
        if w:
            w["eng"] = new_eng
            _save(data)

def delete_word(uid: int, word_id: int) -> str | None:
    """O'chirilgan so'zning 'uz' ini qaytaradi."""
    with _lock:
        data = _load()
        words = data.get(str(uid), {}).get("words", {})
        w = words.pop(str(word_id), None)
        if w:
            _save(data)
            return w["uz"]
        return None

def delete_all(uid: int) -> int:
    with _lock:
        data = _load()
        u = _user(data, uid)
        count = len(u["words"])
        u["words"] = {}
        u["next_id"] = 1
        _save(data)
        return count

def update_box(uid: int, word_id: int, new_box: int):
    """ID orqali qutini yangilaydi — O(1)."""
    with _lock:
        data = _load()
        w = data.get(str(uid), {}).get("words", {}).get(str(word_id))
        if w:
            w["box"] = new_box
            w["next_review"] = next_review_date(new_box)
            _save(data)

# ── QUERY HELPERS ─────────────────────────────────────────────────────────────
def words_new(uid: int) -> list:
    return [w for w in get_all_words(uid) if w["box"] == 0]

def words_in_box(uid: int, box: int, due_only=True) -> list:
    now = datetime.now()
    result = []
    for w in get_all_words(uid):
        if w["box"] != box:
            continue
        if due_only and _dt(w["next_review"]) > now:
            continue
        result.append(w)
    return result

def words_due(uid: int) -> list:
    now = datetime.now()
    return [w for w in get_all_words(uid)
            if w["box"] > 0 and _dt(w["next_review"]) <= now]

def count_box(uid: int, box: int) -> int:
    return sum(1 for w in get_all_words(uid) if w["box"] == box)

def count_due_box(uid: int, box: int) -> int:
    now = datetime.now()
    return sum(1 for w in get_all_words(uid)
               if w["box"] == box and _dt(w["next_review"]) <= now)

def next_due_time(uid: int) -> datetime | None:
    times = [_dt(w["next_review"]) for w in get_all_words(uid) if w["box"] > 0]
    return min(times) if times else None

def next_due_time_box(uid: int, box: int) -> datetime | None:
    times = [_dt(w["next_review"]) for w in get_all_words(uid) if w["box"] == box]
    return min(times) if times else None

def search_words(uid: int, query: str) -> list:
    q = query.lower()
    return [w for w in get_all_words(uid)
            if q in w["uz"].lower() or q in w["eng"].lower()]

def stats(uid: int) -> dict:
    all_w = get_all_words(uid)
    now = datetime.now()
    return {
        "total": len(all_w),
        "new":   sum(1 for w in all_w if w["box"] == 0),
        "done":  sum(1 for w in all_w if w["box"] == 5),
        "due":   sum(1 for w in all_w if w["box"] > 0 and _dt(w["next_review"]) <= now),
        "boxes": {i: sum(1 for w in all_w if w["box"] == i) for i in range(1, 6)},
    }

# ── MIGRATION FROM POSTGRESQL ─────────────────────────────────────────────────
def migrate_from_pg(database_url: str) -> int:
    """
    Startup'da chaqiriladi. Agar words.json bo'sh bo'lsa va DATABASE_URL mavjud bo'lsa,
    PostgreSQL'dagi barcha so'zlarni JSON ga ko'chiradi.
    Qaytadi: ko'chirilgan so'zlar soni (0 = kerak emas yoki xato).
    """
    # JSON allaqachon ma'lumot saqlagan bo'lsa — migratsiya kerak emas
    with _lock:
        existing = _load()
        total_existing = sum(len(v.get("words", {})) for v in existing.values())
    if total_existing > 0:
        log.info(f"✅ JSON'da {total_existing} ta so'z mavjud — migratsiya kerak emas.")
        return 0

    try:
        import psycopg2
    except ImportError:
        log.warning("⚠️ psycopg2 topilmadi — migratsiya o'tkazib yuborildi.")
        return 0

    try:
        conn = psycopg2.connect(database_url)
        cur  = conn.cursor()
        cur.execute("SELECT user_id, uz, eng, box, next_review, created_at FROM words")
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"⚠️ PostgreSQL ulanmadi, migratsiya o'tkazib yuborildi: {e}")
        return 0

    if not rows:
        log.info("📭 PostgreSQL bo'sh — migratsiya kerak emas.")
        return 0

    count = 0
    with _lock:
        data = _load()
        for uid, uz, eng, box, nr, ca in rows:
            u = _user(data, uid)
            # Takrorlanmaslik tekshiruvi
            if any(w["uz"] == uz for w in u["words"].values()):
                continue
            wid = str(u["next_id"])
            u["next_id"] += 1
            u["words"][wid] = {
                "uz":          uz,
                "eng":         eng,
                "box":         box or 0,
                "next_review": (nr or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
                "created_at":  (ca or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
            }
            count += 1
        _save(data)

    log.info(f"🎉 Migratsiya tugadi: {count} ta so'z PostgreSQL → JSON ga ko'chirildi.")
    return count
