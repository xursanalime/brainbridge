import telebot
import os
import random
import psycopg2
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# ================= DATABASE =================

cur.execute("""
CREATE TABLE IF NOT EXISTS words(
id SERIAL PRIMARY KEY,
user_id BIGINT,
uz TEXT,
eng TEXT,
box INTEGER DEFAULT 0
)
""")

# ================= INTERVAL =================

def next_review(box):
    intervals = {1:1,2:3,3:7,4:14,5:30}
    return datetime.now() + timedelta(days=intervals.get(box,1))

# ================= STATES =================

user_state = {}
quiz_state = {}

# ================= MENUS =================

def main_menu():
    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("➕ So'z qo‘shish","📝 Test (Yangi)")
    m.row("🔁 Takrorlash","❌ Tozalash")
    return m

def back_menu():
    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add("🔙 Orqaga")
    return m

def box_menu(user_id):

    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)

    counts={}

    for i in range(1,6):
        cur.execute(
        "SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s",
        (user_id,i))
        counts[i]=cur.fetchone()[0]

    m.row(f"📦 Quti 1 ({counts[1]})",f"📦 Quti 2 ({counts[2]})")
    m.row(f"📦 Quti 3 ({counts[3]})",f"📦 Quti 4 ({counts[4]})")
    m.row(f"📦 Quti 5 ({counts[5]})","🔙 Orqaga")

    return m

# ================= START =================

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        """📚 MNEMONIKA WORD BOT

    Bu bot so‘zlarni oddiy yodlash emas,
    balki 🧠 Leitner (qutilar) tizimi orqali uzoq muddatli xotiraga joylash uchun mo‘ljallangan.

    🔹 Qanday ishlaydi?

    1️⃣ ➕ So‘z qo‘shish  
    English=Uzbek formatda yangi so‘zlar qo‘shasiz.

    2️⃣ 📝 Test (Yangi)  
    Yangi so‘zlar birinchi marta test qilinadi.  
    To‘g‘ri javob → 📦 Quti 1 ga tushadi.

    3️⃣ 🔁 Takrorlash  
    Qutilar orqali takrorlash boshlanadi:

    📦 Quti 1 → 1 kun  
    📦 Quti 2 → 3 kun  
    📦 Quti 3 → 7 kun  
    📦 Quti 4 → 14 kun  
    📦 Quti 5 → 30 kun

    ✅ To‘g‘ri javob → keyingi qutiga o‘tadi  
    ❌ Xato javob → Quti 1 ga qaytadi  

    🎯 Maqsad — so‘zni Quti 5 gacha yetkazish.

    📊 Har testdan keyin natija va statistika ko‘rsatiladi.

    Boshlash uchun tugmalardan birini tanlang 👇
    """,
        reply_markup=main_menu()
    )

# ================= BACK =================

@bot.message_handler(func=lambda m: m.text=="🔙 Orqaga")
def back(message):

    quiz_state.pop(message.chat.id,None)
    user_state.pop(message.chat.id,None)

    bot.send_message(
        message.chat.id,
        "Bosh menyu",
        reply_markup=main_menu()
    )

# ================= ADD WORD =================

@bot.message_handler(func=lambda m: m.text=="➕ So'z qo‘shish")
def add_word(message):

    user_state[message.chat.id]="adding"

    bot.send_message(
        message.chat.id,
        "Format:\nuzbek=english\n\nMisol:\nsalom=hello",
        reply_markup=back_menu()
    )

@bot.message_handler(func=lambda m: user_state.get(m.chat.id)=="adding")
def save_word(message):

    user_id=message.chat.id
    count=0

    for line in message.text.split("\n"):

        if "=" not in line:
            continue

        uz,eng=line.split("=",1)

        uz=uz.strip().lower()
        eng=eng.strip().lower()

        cur.execute(
            "SELECT id, eng, box FROM words WHERE user_id=%s AND uz=%s",
            (user_id, uz)
        )

        row = cur.fetchone()

        if row:

            word_id, old_eng, old_box = row

            synonyms = [x.strip() for x in old_eng.split(",")]

            if eng not in synonyms:
                synonyms.append(eng)
                new_eng = ",".join(synonyms)

                cur.execute("""
                UPDATE words
                SET eng=%s,
                    box=1
                WHERE id=%s
                """, (new_eng, word_id))

                bot.send_message(
                    user_id,
                    "⚠️ Yangi sinonim qo‘shildi. So‘z 1-qutiga qaytarildi."
                )

        else:

            cur.execute("""
            INSERT INTO words(user_id,uz,eng,box)
            VALUES(%s,%s,%s,0)
            """,(user_id,uz,eng))

        count+=1

    user_state.pop(user_id,None)

    bot.send_message(
        user_id,
        f"✅ {count} ta so‘z saqlandi!",
        reply_markup=main_menu()
    )

# ================= TEST NEW =================

@bot.message_handler(func=lambda m: m.text=="📝 Test (Yangi)")
def new_test(message):

    user_id=message.chat.id

    cur.execute("""
    SELECT DISTINCT uz,eng
    FROM words
    WHERE user_id=%s
    AND box=0
    """,(user_id,))

    words=cur.fetchall()

    if not words:
        bot.send_message(user_id,"Yangi so‘z yo‘q.")
        return

    random.shuffle(words)

    quiz_state[user_id]={
        "words":words,
        "index":0,
        "answers":[],
        "used":[],
        "correct":0,
        "wrong":[]
    }

    ask_question(user_id)

# ================= REPETITION =================

@bot.message_handler(func=lambda m: m.text=="🔁 Takrorlash")
def repetition(message):

    bot.send_message(
        message.chat.id,
        "Qutini tanlang:",
        reply_markup=box_menu(message.chat.id)
    )

@bot.message_handler(func=lambda m: m.text and "Quti" in m.text)
def open_box(message):

    user_id=message.chat.id

    match=re.search(r"Quti\s+(\d)",message.text)

    if not match:
        return

    box=int(match.group(1))

    cur.execute(
        "SELECT uz,eng FROM words WHERE user_id=%s AND box=%s",
        (user_id, box)
    )

    words = cur.fetchall()

    if not words:

        bot.send_message(
        user_id,
        "Bu qutida so‘z yo‘q.",
        reply_markup=box_menu(user_id))
        return

    random.shuffle(words)

    quiz_state[user_id]={
        "words":words,
        "index":0,
        "answers":[],
        "used":[],
        "correct":0,
        "wrong":[]
    }

    ask_question(user_id)

# ================= QUESTION =================

def ask_question(user_id):

    quiz=quiz_state.get(user_id)

    if not quiz:
        return

    if quiz["index"]>=len(quiz["words"]):

        finish_test(user_id)
        return

    uz,eng=quiz["words"][quiz["index"]]

    answers=[x.strip() for x in eng.split(",")]

    quiz["answers"]=answers
    quiz["used"]=[]

    bot.send_message(
        user_id,
        f"({quiz['index']+1}/{len(quiz['words'])})\n🇺🇿 {uz.upper()} → ?",
        reply_markup=back_menu()
    )

# ================= ANSWER =================

@bot.message_handler(func=lambda m: m.chat.id in quiz_state)
def check_answer(message):

    user_id=message.chat.id
    quiz=quiz_state[user_id]

    if message.text=="🔙 Orqaga":
        return

    answer=message.text.strip().lower()

    uz,eng=quiz["words"][quiz["index"]]
    answers=quiz["answers"]

    if answer in answers and answer not in quiz["used"]:

        quiz["used"].append(answer)
        quiz["correct"]+=1

        bot.send_message(user_id,"✅ To‘g‘ri")

        if len(quiz["used"])<len(answers):

            bot.send_message(user_id,"Yana sinonimini kiriting")
            return

        cur.execute(
        "SELECT box FROM words WHERE user_id=%s AND uz=%s",
        (user_id,uz))

        box=cur.fetchone()[0]

        new_box=min(box+1,5)

        cur.execute("""
        UPDATE words
        SET box=%s
        WHERE user_id=%s AND uz=%s
        """,(new_box,user_id,uz))

    else:

        bot.send_message(user_id,f"❌ Xato\nTo‘g‘ri: {eng}")

        quiz["wrong"].append((uz,eng))

        cur.execute("""
        UPDATE words
        SET box=1
        WHERE user_id=%s AND uz=%s
        """,(user_id,uz))

    quiz["index"]+=1

    ask_question(user_id)

# ================= FINISH =================

def finish_test(user_id):

    quiz=quiz_state[user_id]

    total=quiz["correct"]+len(quiz["wrong"])

    percent=0 if total==0 else int((quiz["correct"]/total)*100)

    bot.send_message(
        user_id,
        f"🏁 Test tugadi\n\n📊 {percent}%\n✅ {quiz['correct']}\n❌ {len(quiz['wrong'])}",
        reply_markup=main_menu()
    )

    if quiz["wrong"]:

        text="❌ Xato so‘zlar:\n\n"

        for uz,eng in quiz["wrong"]:
            text+=f"{uz} → {eng}\n"

        bot.send_message(user_id,text)

    else:
        bot.send_message(user_id,"🎉 Xatolar yo‘q")

    quiz_state.pop(user_id,None)

# ================= CLEAR =================

@bot.message_handler(func=lambda m: m.text=="❌ Tozalash")
def clear_confirm(message):

    m=telebot.types.InlineKeyboardMarkup()

    m.add(
        telebot.types.InlineKeyboardButton("✅ Ha",callback_data="yes"),
        telebot.types.InlineKeyboardButton("❌ Yo‘q",callback_data="no")
    )

    bot.send_message(
        message.chat.id,
        "Barcha so‘zlarni o‘chirmoqchimisiz?",
        reply_markup=m
    )

@bot.callback_query_handler(func=lambda call: True)
def callback(call):

    user_id=call.message.chat.id

    if call.data=="yes":

        cur.execute(
        "DELETE FROM words WHERE user_id=%s",
        (user_id,))

        bot.edit_message_text(
            "🗑 So‘zlar o‘chirildi",
            call.message.chat.id,
            call.message.message_id
        )

        bot.send_message(user_id,"Bosh menyu",reply_markup=main_menu())

    else:

        bot.edit_message_text(
            "❌ Bekor qilindi",
            call.message.chat.id,
            call.message.message_id
        )

print("BrainBridge bot ishlayapti...")

bot.infinity_polling(skip_pending=True)