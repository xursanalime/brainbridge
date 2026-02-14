import telebot
import os
import random
import re
import psycopg2

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# ================= DATABASE INIT =================

cur.execute("""
CREATE TABLE IF NOT EXISTS words (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    eng TEXT,
    uz TEXT,
    box INTEGER DEFAULT 0,
    UNIQUE(user_id, eng)
)
""")

# ================= STATES =================

user_state = {}
quiz_state = {}

# ================= MENUS =================

def main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("➕ So'z qo‘shish", "📝 Test (Yangi)")
    markup.row("🔁 Takrorlash", "❌ Tozalash")
    return markup


def back_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Orqaga")
    return markup


def box_menu(user_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)

    counts = {}
    for i in range(1, 6):
        cur.execute(
            "SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s",
            (user_id, i)
        )
        counts[i] = cur.fetchone()[0]

    markup.row(f"📦 Quti 1 ({counts[1]})",
               f"📦 Quti 2 ({counts[2]})")

    markup.row(f"📦 Quti 3 ({counts[3]})",
               f"📦 Quti 4 ({counts[4]})")

    markup.row(f"📦 Quti 5 ({counts[5]})", "🔙 Orqaga")

    return markup

# ================= START =================

@bot.message_handler(commands=["start"])
def start(message):
    text = """
📚 MNEMONIKA WORD BOT

Bu bot Leitner tizimi orqali so‘zlarni uzoq muddatli xotiraga joylaydi.

🎯 Maqsad — so‘zni Quti 5 gacha yetkazish.
"""
    bot.send_message(message.chat.id, text, reply_markup=main_menu())

# ================= ORQAGA =================

@bot.message_handler(func=lambda m: m.text == "🔙 Orqaga")
def go_back(message):
    quiz_state.pop(message.chat.id, None)
    user_state.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "Bosh menyu", reply_markup=main_menu())

# ================= ADD WORD =================

@bot.message_handler(func=lambda m: m.text == "➕ So'z qo‘shish")
def add_words(message):
    user_state[message.chat.id] = "adding"
    bot.send_message(
        message.chat.id,
        "Format:\nenglish=uzbek",
        reply_markup=back_menu()
    )

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "adding")
def process_words(message):
    user_id = message.chat.id
    count = 0

    for line in message.text.split("\n"):
        if "=" in line:
            eng, uz = line.split("=", 1)
        elif "-" in line:
            eng, uz = line.split("-", 1)
        else:
            continue

        eng = eng.strip().lower()
        uz = uz.strip().lower()

        if eng and uz:
            cur.execute("""
                INSERT INTO words (user_id, eng, uz, box)
                VALUES (%s, %s, %s, 0)
                ON CONFLICT (user_id, eng)
                DO UPDATE SET uz=EXCLUDED.uz
            """, (user_id, eng, uz))
            count += 1

    user_state.pop(user_id, None)

    bot.send_message(
        user_id,
        f"✅ {count} ta so‘z saqlandi!",
        reply_markup=main_menu()
    )

# ================= TEST NEW =================

@bot.message_handler(func=lambda m: m.text == "📝 Test (Yangi)")
def start_new_test(message):
    user_id = message.chat.id

    cur.execute("""
        SELECT eng, uz FROM words
        WHERE user_id=%s AND box=0
    """, (user_id,))

    words = cur.fetchall()

    if not words:
        bot.send_message(user_id, "Yangi so‘z yo‘q.")
        return

    random.shuffle(words)

    quiz_state[user_id] = {
        "type": "new",
        "words": words,
        "index": 0,
        "correct": 0
    }

    ask_question(user_id)

# ================= TAKRORLASH =================

@bot.message_handler(func=lambda m: m.text == "🔁 Takrorlash")
def repetition_info(message):
    bot.send_message(
        message.chat.id,
        "Qutini tanlang:",
        reply_markup=box_menu(message.chat.id)
    )

@bot.message_handler(func=lambda m: m.text and "Quti" in m.text)
def open_box(message):
    user_id = message.chat.id
    match = re.search(r"Quti\s+(\d)", message.text)

    if not match:
        return

    box_number = int(match.group(1))

    cur.execute("""
        SELECT eng, uz FROM words
        WHERE user_id=%s AND box=%s
    """, (user_id, box_number))

    words = cur.fetchall()

    if not words:
        bot.send_message(
            user_id,
            "Bu quti bo‘sh.",
            reply_markup=box_menu(user_id)
        )
        return

    quiz_state[user_id] = {
        "type": "box",
        "box": box_number,
        "words": words,
        "index": 0,
        "correct": 0
    }

    ask_question(user_id)

# ================= SAVOL =================

def ask_question(chat_id):
    quiz = quiz_state.get(chat_id)

    if not quiz:
        return

    if quiz["index"] >= len(quiz["words"]):
        finish_test(chat_id)
        return

    eng, uz = quiz["words"][quiz["index"]]

    quiz["current_answer"] = eng

    question = f"({quiz['index']+1}/{len(quiz['words'])})\n🇺🇿 {uz.upper()} → ?"

    bot.send_message(chat_id, question, reply_markup=back_menu())

# ================= JAVOB =================

@bot.message_handler(func=lambda m: m.chat.id in quiz_state)
def check_answer(message):
    chat_id = message.chat.id

    if message.text == "🔙 Orqaga":
        return

    quiz = quiz_state[chat_id]

    user_answer = message.text.strip().lower()
    correct_answer = quiz["current_answer"]

    eng, _ = quiz["words"][quiz["index"]]

    if user_answer == correct_answer:
        quiz["correct"] += 1
        bot.send_message(chat_id, "✅ To‘g‘ri!")

        if quiz["type"] == "new":
            cur.execute("""
                UPDATE words
                SET box=1
                WHERE user_id=%s AND eng=%s
            """, (chat_id, eng))
        else:
            next_box = min(quiz["box"] + 1, 5)
            cur.execute("""
                UPDATE words
                SET box=%s
                WHERE user_id=%s AND eng=%s
            """, (next_box, chat_id, eng))
    else:
        bot.send_message(chat_id, f"❌ Xato! {correct_answer}")
        cur.execute("""
            UPDATE words
            SET box=1
            WHERE user_id=%s AND eng=%s
        """, (chat_id, eng))

    quiz["index"] += 1
    ask_question(chat_id)

# ================= FINISH =================

def finish_test(chat_id):
    quiz = quiz_state[chat_id]

    total = len(quiz["words"])
    correct = quiz["correct"]
    wrong = total - correct
    percent = int((correct / total) * 100)

    text = f"""
🏁 Test tugadi!

📊 Natija: {percent}%
📚 Jami: {total}
✅ To‘g‘ri: {correct}
❌ Xato: {wrong}
"""

    bot.send_message(chat_id, text, reply_markup=main_menu())
    quiz_state.pop(chat_id, None)

# ================= CLEAR =================

@bot.message_handler(func=lambda m: m.text == "❌ Tozalash")
def clear_all(message):
    cur.execute("DELETE FROM words WHERE user_id=%s", (message.chat.id,))
    bot.send_message(
        message.chat.id,
        "Sizning so‘zlaringiz tozalandi.",
        reply_markup=main_menu()
    )

# ================= RUN =================

print("Bot Railway + Postgres bilan ishlayapti...")
bot.infinity_polling(skip_pending=True)
