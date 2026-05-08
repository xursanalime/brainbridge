"""
Migration: next_review va created_at ustunlarini words jadvaliga qo'shish.
Bir marta ishga tushiring, keyin o'chiring.

Ishlatish: python migrate.py
"""
import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL muhit o'zgaruvchisi o'rnatilmagan!")

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

migrations = [
    # next_review ustunini qo'shish (agar yo'q bo'lsa)
    """
    ALTER TABLE words
    ADD COLUMN IF NOT EXISTS next_review TIMESTAMP DEFAULT NOW();
    """,
    # created_at ustunini qo'shish (agar yo'q bo'lsa)
    """
    ALTER TABLE words
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
    """,
    # Indekslar
    "CREATE INDEX IF NOT EXISTS idx_user   ON words (user_id);",
    "CREATE INDEX IF NOT EXISTS idx_review ON words (user_id, box, next_review);",
]

for sql in migrations:
    try:
        cur.execute(sql)
        print(f"✅ Bajarildi: {sql.strip()[:60]}...")
    except Exception as e:
        print(f"❌ Xato: {e}")

cur.close()
conn.close()
print("\n✅ Migration tugadi!")
