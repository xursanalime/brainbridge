import telebot
import json
import os
import random
import re

TOKEN = "8249270236:AAHhVgYuUI0cHbufR0I87322LIHvFFvmy8Y"
bot = telebot.TeleBot(TOKEN)

DATA_FILE = "data.json"

# ================= DATA =================

def default_data():
    return {
        "new_words": {},
        "boxes": {
            "1": {},
            "2": {},
            "3": {},
            "4": {},
            "5": {}
        }
    }

def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except:
            data = default_data()

    if "new_words" not in data:
        data["new_words"] = {}
    if "boxes" not in data:
        data["boxes"] = default_data()["boxes"]

    return data

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ================= STATES =================

user_state = {}
quiz_state = {}

# ================= MENUS =================

def main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)

    # 1-qator
    markup.row("➕ So'z qo‘shish", "📝 Test (Yangi)")

    # 2-qator (🔥 shu yerda bir qatorda)
    markup.row("🔁 Takrorlash", "❌ Tozalash")

    return markup


def back_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Orqaga")
    return markup

def box_menu():
    data = load_data()
    boxes = data["boxes"]

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)

    markup.row(f"📦 Quti 1 ({len(boxes['1'])})",
               f"📦 Quti 2 ({len(boxes['2'])})")

    markup.row(f"📦 Quti 3 ({len(boxes['3'])})",
               f"📦 Quti 4 ({len(boxes['4'])})")

    # 🔥 Quti 5 va Orqaga bir qatorda
    markup.row(f"📦 Quti 5 ({len(boxes['5'])})", "🔙 Orqaga")

    return markup


# ================= START =================

@bot.message_handler(commands=["start"])
def start(message):

    text = """
📚 MNEMONIKA WORD BOT

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
"""

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=main_menu()
    )

# ================= ORQAGA =================

@bot.message_handler(func=lambda m: m.text == "🔙 Orqaga")
def go_back(message):
    quiz_state.pop(message.chat.id, None)
    user_state.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "Bosh menyu", reply_markup=main_menu())

# ================= ADD WORDS =================

@bot.message_handler(func=lambda m: m.text == "➕ So'z qo‘shish")
def add_words(message):
    user_state[message.chat.id] = "adding"
    bot.send_message(message.chat.id,
                     "Format:\nenglish=uzbek",
                     reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "adding")
def process_words(message):

    data = load_data()
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
            data["new_words"][eng] = {"uz": uz}
            count += 1

    save_data(data)
    user_state.pop(message.chat.id, None)

    bot.send_message(message.chat.id,
                     f"✅ {count} ta so‘z saqlandi!",
                     reply_markup=main_menu())

# ================= TEST (YANGI) =================

@bot.message_handler(func=lambda m: m.text == "📝 Test (Yangi)")
def start_new_test(message):

    data = load_data()
    words = list(data["new_words"].items())

    if not words:
        bot.send_message(message.chat.id, "Yangi so‘z yo‘q.")
        return

    random.shuffle(words)

    quiz_state[message.chat.id] = {
        "type": "new",
        "words": words,
        "index": 0,
        "correct": 0
    }

    ask_question(message.chat.id)

# ================= TAKRORLASH =================

@bot.message_handler(func=lambda m: m.text == "🔁 Takrorlash")
def repetition_info(message):

    info_text = """
🔁 TAKRORLASH TIZIMI (Leitner)

📦 Quti 1 – 1 kun
📦 Quti 2 – 3 kun
📦 Quti 3 – 7 kun
📦 Quti 4 – 14 kun
📦 Quti 5 – 30 kun

To‘g‘ri → keyingi quti
Xato → Quti 1 ga qaytadi
"""

    bot.send_message(message.chat.id, info_text, reply_markup=box_menu())

# ================= QUTI TANLASH =================

@bot.message_handler(func=lambda m: m.text and "Quti" in m.text)
def open_box(message):

    match = re.search(r"Quti\s+(\d)", message.text)
    if not match:
        return

    box_number = match.group(1)

    data = load_data()
    box_words = data["boxes"].get(box_number, {})

    if not box_words:
        bot.send_message(message.chat.id, "Bu quti bo‘sh.", reply_markup=box_menu())
        return

    words = list(box_words.items())

    quiz_state[message.chat.id] = {
        "type": "box",
        "box": box_number,
        "words": words,
        "index": 0,
        "correct": 0,
        "wrong": 0
    }

    ask_question(message.chat.id)

# ================= SAVOL =================

def ask_question(chat_id):

    quiz = quiz_state.get(chat_id)
    if not quiz:
        return

    if quiz["index"] >= len(quiz["words"]):
        finish_test(chat_id)
        return

    eng, info = quiz["words"][quiz["index"]]
    uz = info["uz"]

    question = f"({quiz['index']+1}/{len(quiz['words'])})\n🇺🇿 {uz.upper()} → ?"

    quiz["current_answer"] = eng

    bot.send_message(chat_id, question, reply_markup=back_menu())

# ================= JAVOB =================

@bot.message_handler(func=lambda m: m.chat.id in quiz_state)
def check_answer(message):

    if message.text == "🔙 Orqaga":
        return

    chat_id = message.chat.id
    quiz = quiz_state[chat_id]

    user_answer = message.text.strip().lower()
    correct_answer = quiz["current_answer"].lower()

    data = load_data()
    eng, info = quiz["words"][quiz["index"]]

    if user_answer == correct_answer:
        quiz["correct"] += 1
        bot.send_message(chat_id, "✅ To‘g‘ri!")

        if quiz["type"] == "new":
            data["boxes"]["1"][eng] = info
            data["new_words"].pop(eng, None)

        elif quiz["type"] == "box":
            current_box = quiz["box"]
            next_box = str(min(int(current_box) + 1, 5))

            data["boxes"][current_box].pop(eng, None)
            data["boxes"][next_box][eng] = info

    else:
        bot.send_message(chat_id, f"❌ Xato! {correct_answer}")

        if quiz["type"] == "box":
            current_box = quiz["box"]
            data["boxes"][current_box].pop(eng, None)
            data["boxes"]["1"][eng] = info

    save_data(data)

    quiz["index"] += 1
    ask_question(chat_id)

# ================= STATISTIKA =================

def finish_test(chat_id):

    quiz = quiz_state[chat_id]

    total = len(quiz["words"])
    correct = quiz["correct"]
    wrong = total - correct
    percent = int((correct / total) * 100)

    if percent >= 90:
        level = "🔥 Zo'r natija!"
    elif percent >= 70:
        level = "👍 Yaxshi!"
    elif percent >= 50:
        level = "🙂 O‘rtacha"
    else:
        level = "📉 Ko‘proq takrorlash kerak"

    text = f"""
🏁 Test tugadi!

📊 Natija: {percent}%
{level}

📚 Jami savol: {total}
✅ To‘g‘ri: {correct}
❌ Xato: {wrong}
"""

    bot.send_message(chat_id, text, reply_markup=main_menu())
    quiz_state.pop(chat_id, None)

# ================= CLEAR =================

@bot.message_handler(func=lambda m: m.text == "❌ Tozalash")
def clear_all(message):
    save_data(default_data())
    bot.send_message(message.chat.id,
                     "Hammasi tozalandi.",
                     reply_markup=main_menu())

print("Bot ishlayapti...")
bot.infinity_polling(skip_pending=True)
