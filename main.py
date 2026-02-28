import telebot
import os
import random
import re
import psycopg2
from datetime import datetime, timedelta
import threading
import time

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# ================= INTERVAL FUNCTION =================

def calculate_next_review(box):
    intervals = {
        1: 1,
        2: 3,
        3: 7,
        4: 14,
        5: 30
    }
    return datetime.now() + timedelta(days=intervals.get(box, 1))


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

    for i in range(1,6):
        cur.execute("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s",
                    (user_id, i))
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
    bot.send_message(
        message.chat.id,
        "📚 Mnemonika Word Bot\nLeitner tizimi asosida ishlaydi.",
        reply_markup=main_menu()
    )

# ================= ORQAGA =================

@bot.message_handler(func=lambda m: m.text == "🔙 Orqaga")
def go_back(message):
    quiz_state.pop(message.chat.id, None)
    user_state.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "Bosh menyu", reply_markup=main_menu())

# ================= ADD WORD =================

@bot.message_handler(func=lambda m: m.text == "➕ So'z qo‘shish")
def add_word(message):
    user_state[message.chat.id] = "adding"
    bot.send_message(message.chat.id,
                     "Format:\nenglish=uzbek",
                     reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "adding")
def save_word(message):
    user_id = message.chat.id
    count = 0

    for line in message.text.split("\n"):
        line = line.strip().replace("–", "-").replace("—", "-")

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
                VALUES (%s,%s,%s,0)
            """, (user_id, eng, uz))
            count += 1

    user_state.pop(user_id, None)
    bot.send_message(user_id,
                     f"✅ {count} ta so‘z saqlandi!",
                     reply_markup=main_menu())

# ================= TEST NEW =================

@bot.message_handler(func=lambda m: m.text == "📝 Test (Yangi)")
def start_new_test(message):
    user_id = message.chat.id

    cur.execute("SELECT eng, uz FROM words WHERE user_id=%s AND box=0",
                (user_id,))
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
def repetition(message):
    bot.send_message(message.chat.id,
                     "Qutini tanlang:",
                     reply_markup=box_menu(message.chat.id))

@bot.message_handler(func=lambda m: m.text and "Quti" in m.text)
def open_box(message):
    user_id = message.chat.id
    match = re.search(r"Quti\s+(\d)", message.text)
    if not match:
        return

    box = int(match.group(1))

    cur.execute("""
        SELECT eng, uz FROM words
        WHERE user_id=%s AND box=%s
          AND next_review <= NOW()
    """, (user_id, box))

    words = cur.fetchall()

    if not words:
        bot.send_message(user_id,
                         "Bu qutida hozir takrorlash vaqti kelgan so‘z yo‘q.",
                         reply_markup=box_menu(user_id))
        return

    quiz_state[user_id] = {
        "type": "box",
        "box": box,
        "words": words,
        "index": 0,
        "correct": 0
    }

    ask_question(user_id)

# ================= QUESTION =================

def ask_question(user_id):
    quiz = quiz_state.get(user_id)
    if not quiz:
        return

    if quiz["index"] >= len(quiz["words"]):
        finish_test(user_id)
        return

    eng, uz = quiz["words"][quiz["index"]]

    quiz["current_answer"] = eng

    bot.send_message(
        user_id,
        f"({quiz['index']+1}/{len(quiz['words'])})\n🇺🇿 {uz.upper()} → ?",
        reply_markup=back_menu()
    )

# ================= ANSWER =================

@bot.message_handler(func=lambda m: m.chat.id in quiz_state)
def check_answer(message):
    user_id = message.chat.id
    quiz = quiz_state[user_id]

    if message.text == "🔙 Orqaga":
        return

    eng, uz = quiz["words"][quiz["index"]]
    correct = quiz["current_answer"]

    if message.text.strip().lower() == correct:
        quiz["correct"] += 1
        bot.send_message(user_id, "✅ To‘g‘ri!")

        if quiz["type"] == "new":
            new_box = 1
        else:
            new_box = min(quiz["box"] + 1, 5)

        cur.execute("""
            UPDATE words
            SET box=%s,
                next_review=%s,
                reminded=FALSE
            WHERE user_id=%s AND eng=%s
        """, (new_box,
              calculate_next_review(new_box),
              user_id,
              eng))

    else:
        bot.send_message(user_id, f"❌ Xato! {correct}")

        reset_box = 1

        cur.execute("""
            UPDATE words
            SET box=%s,
                next_review=%s,
                reminded=FALSE
            WHERE user_id=%s AND eng=%s
        """, (reset_box,
              calculate_next_review(reset_box),
              user_id,
              eng))

    quiz["index"] += 1
    ask_question(user_id)

# ================= STATISTICS =================

def finish_test(user_id):
    quiz = quiz_state[user_id]

    total = len(quiz["words"])
    correct = quiz["correct"]
    percent = int((correct/total)*100)

    bot.send_message(
        user_id,
        f"🏁 Test tugadi!\n\n📊 Natija: {percent}%\n"
        f"📚 Jami: {total}\n"
        f"✅ To‘g‘ri: {correct}\n"
        f"❌ Xato: {total-correct}",
        reply_markup=main_menu()
    )

    quiz_state.pop(user_id, None)

# ================= REMINDER =================

def review_checker():
    while True:
        try:
            cur.execute("""
            SELECT user_id, box, COUNT(*)
            FROM words
            WHERE next_review <= NOW()
              AND reminded=FALSE
            GROUP BY user_id, box
            """)
            rows = cur.fetchall()

            for user_id, box, count in rows:
                bot.send_message(
                    user_id,
                    f"📦 {box}-box ni takrorlash vaqti keldi!\n"
                    f"📝 {count} ta so‘z seni kutyapti."
                )

                cur.execute("""
                UPDATE words
                SET reminded=TRUE
                WHERE user_id=%s
                  AND box=%s
                  AND next_review <= NOW()
                """, (user_id, box))

        except Exception as e:
            print("Reminder error:", e)

        time.sleep(1800)

# ================= CLEAR =================

@bot.message_handler(func=lambda m: m.text == "❌ Tozalash")
def clear_all(message):
    cur.execute("DELETE FROM words WHERE user_id=%s",
                (message.chat.id,))
    bot.send_message(message.chat.id,
                     "So‘zlaringiz tozalandi.",
                     reply_markup=main_menu())


threading.Thread(target=review_checker, daemon=True).start()

print("Bot Railway + Postgres bilan ishlayapti...")
bot.infinity_polling(skip_pending=True)