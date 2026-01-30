import telebot
from telebot import types
import json
import os
import random
import re

# ================= CONFIG =================

TOKEN = "8402764062:AAHICTIKlOi26FfZIgfqyzxJt3dSMeaBqoU"
ADMIN_ID = 6651718779

DATA_FILE = "words.json"
STAT_FILE = "stats.json"

bot = telebot.TeleBot(TOKEN)

user_lang = {}
user_state = {}
quiz_data = {}
quiz_mode = {}

# ================= INIT =================

for f in [DATA_FILE, STAT_FILE]:
    if not os.path.exists(f):
        with open(f, "w", encoding="utf-8") as file:
            json.dump({}, file)


# ================= DB =================

def load_words():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_words(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_stats():
    with open(STAT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_stats(data):
    with open(STAT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def clear_state(cid):
    user_state.pop(cid, None)
    quiz_data.pop(cid, None)
    quiz_mode.pop(cid, None)


# ================= TEXT =================

TEXTS = {

    "uz": {
        "menu": "Asosiy menyu 👇",
        "add": "➕ So‘z qo‘shish",
        "quiz": "📝 Quiz",
        "stat": "📊 Statistika",
        "admin": "⚙️ Admin",
        "back": "⬅️ Orqaga",

        "mode": "Test turini tanlang:",
        "choice": "🟢 Variant",
        "write": "✍️ Yozma",
        "unit": "Unit tanlang:",

        "correct": "✅ To‘g‘ri!",
        "wrong": "❌ Xato! Javob: {a}",
        "finish": "🏁 Tugadi\nTo‘g‘ri: {c}\nXato: {w}",

        "format":
        "Format:\n\n"
        "Unit1\n"
        "apple=olma\n"
        "book=kitob\n\n"
        "Max 20 👇"
    },

    "en": {
        "menu": "Main menu 👇",
        "add": "➕ Add",
        "quiz": "📝 Quiz",
        "stat": "📊 Stats",
        "admin": "⚙️ Admin",
        "back": "⬅️ Back",

        "mode": "Choose mode:",
        "choice": "🟢 Choice",
        "write": "✍️ Write",
        "unit": "Choose unit:",

        "correct": "✅ Correct!",
        "wrong": "❌ Wrong! Answer: {a}",
        "finish": "🏁 Finished\nCorrect: {c}\nWrong: {w}",

        "format":
        "Format:\n\n"
        "Unit1\n"
        "apple=olma\n"
        "book=kitob\n\n"
        "Max 20 👇"
    },

    "ru": {
        "menu": "Главное меню 👇",
        "add": "➕ Добавить",
        "quiz": "📝 Тест",
        "stat": "📊 Статистика",
        "admin": "⚙️ Админ",
        "back": "⬅️ Назад",

        "mode": "Выберите режим:",
        "choice": "🟢 Варианты",
        "write": "✍️ Написать",
        "unit": "Выберите модуль:",

        "correct": "✅ Верно!",
        "wrong": "❌ Ошибка! Ответ: {a}",
        "finish": "🏁 Завершено\nВерно: {c}\nОшибки: {w}",

        "format":
        "Формат:\n\n"
        "Unit1\n"
        "apple=olma\n"
        "book=kitob\n\n"
        "Max 20 👇"
    }
}


def t(cid, key):
    return TEXTS[user_lang.get(cid, "uz")][key]


# ================= MENU =================

def show_menu(cid):

    clear_state(cid)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.add(t(cid, "add"))
    kb.add(t(cid, "quiz"), t(cid, "stat"))
    kb.add(t(cid, "admin"))

    bot.send_message(cid, t(cid, "menu"), reply_markup=kb)


# ================= START =================

@bot.message_handler(commands=["start"])
def start(message):

    clear_state(message.chat.id)

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton("🇺🇿 O‘zbek", callback_data="lang_uz"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")
    )

    bot.send_message(message.chat.id, "Choose language:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("lang_"))
def set_lang(call):

    user_lang[call.from_user.id] = call.data.split("_")[1]
    show_menu(call.from_user.id)


# ================= ADD =================

@bot.message_handler(func=lambda m: m.text in [
    TEXTS["uz"]["add"], TEXTS["en"]["add"], TEXTS["ru"]["add"]
])
def add_start(message):

    cid = message.chat.id

    clear_state(cid)

    user_state[cid] = "add"

    bot.send_message(cid, t(cid, "format"))


@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "add")
def add_process(message):

    cid = message.chat.id

    lines = message.text.strip().split("\n")

    if len(lines) < 2:
        bot.send_message(cid, "❌ Kamida 1 ta so‘z kiriting")
        return

    unit = lines[0].strip()
    pairs = lines[1:]

    if len(pairs) > 20:
        bot.send_message(cid, "❌ Max 20 ta so‘z mumkin")
        return

    data = load_words()

    if unit not in data:
        data[unit] = {}

    # 🔹 Barcha inglizcha so‘zlar
    all_eng = set()

    for u in data.values():
        for w in u:
            all_eng.add(w.lower())

    added = 0
    errors = []

    for i, line in enumerate(pairs, 1):

        if "=" not in line:
            errors.append(f"{i}: {line} (no =)")
            continue

        eng, uz = line.split("=", 1)

        eng = eng.strip()
        uz = uz.strip()

        if not eng or not uz:
            errors.append(f"{i}: {line} (empty)")
            continue

        if not re.fullmatch(r"[A-Za-z ]+", eng):
            errors.append(f"{i}: {eng} (invalid)")
            continue

        if eng.lower() in all_eng:
            errors.append(f"{i}: {eng} (already exists)")
            continue

        data[unit][eng] = uz
        all_eng.add(eng.lower())
        added += 1

    save_words(data)

    user_state.pop(cid, None)

    msg = f"✅ {added} ta qo‘shildi\n"

    if errors:
        msg += "\n❌ Xatolar:\n" + "\n".join(errors)

    bot.send_message(cid, msg)

    show_menu(cid)


# ================= QUIZ =================

@bot.message_handler(func=lambda m: m.text in [
    TEXTS["uz"]["quiz"], TEXTS["en"]["quiz"], TEXTS["ru"]["quiz"]
])
def quiz_menu(message):

    clear_state(message.chat.id)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.add(t(message.chat.id, "choice"))
    kb.add(t(message.chat.id, "write"))
    kb.add(t(message.chat.id, "back"))

    bot.send_message(message.chat.id, t(message.chat.id, "mode"), reply_markup=kb)


@bot.message_handler(func=lambda m: m.text in [
    TEXTS["uz"]["choice"], TEXTS["en"]["choice"], TEXTS["ru"]["choice"],
    TEXTS["uz"]["write"], TEXTS["en"]["write"], TEXTS["ru"]["write"]
])
def quiz_mode_select(message):

    if "🟢" in message.text:
        quiz_mode[message.chat.id] = "choice"
    else:
        quiz_mode[message.chat.id] = "write"

    data = load_words()

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    for u in data:
        kb.add(u)

    kb.add(t(message.chat.id, "back"))

    bot.send_message(message.chat.id, t(message.chat.id, "unit"), reply_markup=kb)


@bot.message_handler(func=lambda m: m.chat.id in quiz_mode and m.text in load_words())
def quiz_start(message):

    unit = message.text

    data = load_words()

    words = list(data[unit].items())
    random.shuffle(words)

    quiz_data[message.chat.id] = {
        "words": words,
        "i": 0,
        "score": 0,
        "ans": ""
    }

    ask(message.chat.id)


def ask(cid):

    q = quiz_data[cid]

    if q["i"] >= len(q["words"]):
        finish(cid)
        return

    eng, uz = q["words"][q["i"]]

    q["ans"] = uz

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    if quiz_mode[cid] == "choice":

        all_words = []

        for u in load_words().values():
            all_words += list(u.values())

        opts = [uz]

        while len(opts) < 4:
            x = random.choice(all_words)
            if x not in opts:
                opts.append(x)

        random.shuffle(opts)

        for o in opts:
            kb.add(o)

    kb.add(t(cid, "back"))

    bot.send_message(cid, f"{eng} = ?", reply_markup=kb)


@bot.message_handler(func=lambda m: m.chat.id in quiz_data)
def answer(message):

    cid = message.chat.id

    if message.text == t(cid, "back"):
        show_menu(cid)
        return

    q = quiz_data[cid]

    user = message.text.lower().strip()
    correct = q["ans"].lower()

    stats = load_stats()

    if str(cid) not in stats:
        stats[str(cid)] = {"ok": 0, "bad": 0}

    if user == correct:

        q["score"] += 1
        stats[str(cid)]["ok"] += 1

        bot.send_message(cid, t(cid, "correct"))

    else:

        stats[str(cid)]["bad"] += 1

        bot.send_message(cid, t(cid, "wrong").format(a=q["ans"]))

    save_stats(stats)

    q["i"] += 1

    ask(cid)


def finish(cid):

    q = quiz_data[cid]

    bot.send_message(
        cid,
        t(cid, "finish").format(
            c=q["score"],
            w=len(q["words"]) - q["score"]
        )
    )

    show_menu(cid)


# ================= STAT =================

@bot.message_handler(func=lambda m: m.text in [
    TEXTS["uz"]["stat"], TEXTS["en"]["stat"], TEXTS["ru"]["stat"]
])
def stat(message):

    clear_state(message.chat.id)

    stats = load_stats()

    s = stats.get(str(message.chat.id), {"ok": 0, "bad": 0})

    bot.send_message(message.chat.id, f"✅ {s['ok']} | ❌ {s['bad']}")


# ================= ADMIN =================

@bot.message_handler(func=lambda m: m.text in [
    TEXTS["uz"]["admin"], TEXTS["en"]["admin"], TEXTS["ru"]["admin"]
])
def admin(message):

    clear_state(message.chat.id)

    bot.send_message(
        message.chat.id,
        "👨‍💻 Admin: @xursanalime"
    )

    show_menu(message.chat.id)


# ================= BACK =================

@bot.message_handler(func=lambda m: m.text in [
    TEXTS["uz"]["back"], TEXTS["en"]["back"], TEXTS["ru"]["back"]
])
def back(message):

    show_menu(message.chat.id)


@bot.message_handler(commands=["clearall"])
def clear_all(message):

    cid = message.chat.id

    # Faqat admin ishlata oladi
    if cid != ADMIN_ID:
        bot.send_message(cid, "❌ Siz admin emassiz")
        return

    clear_state(cid)

    save_words({})
    save_stats({})

    bot.send_message(cid, "✅ Barcha so‘zlar va statistika tozalandi!")

    show_menu(cid)


# ================= RUN =================

bot.infinity_polling()
