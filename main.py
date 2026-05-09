import telebot, os, random, re, logging
from datetime import datetime
import storage, backup

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan!")

bot = telebot.TeleBot(TOKEN, threaded=True)

BOX_ICON = ["🆕","1️⃣","2️⃣","3️⃣","4️⃣","🏆"]
PAGE_SIZE = 8
user_state: dict = {}
quiz_state: dict = {}

# ── MENUS ─────────────────────────────────────────────────────────────────────
def main_menu():
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ So'z qo'shish", "📝 Test (Yangi)")
    kb.row("🔁 Takrorlash",    "📊 Statistika")
    kb.row("🔍 Qidirish",      "📋 So'zlarim")
    kb.row("❌ Tozalash")
    return kb

def back_menu():
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔙 Orqaga")
    return kb

def box_menu(uid):
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    labels = []
    for i in range(1, 6):
        t = storage.count_box(uid, i)
        d = storage.count_due_box(uid, i)
        badge = f"🔴{d}" if d > 0 else "✅"
        labels.append(f"📦 Quti {i} ({badge}/{t})")
    kb.row(labels[0], labels[1])
    kb.row(labels[2], labels[3])
    kb.row(labels[4], "🔙 Orqaga")
    return kb

# ── HELPERS ───────────────────────────────────────────────────────────────────
def bar(done, total, w=10):
    f = int((done/total)*w) if total else 0
    return "█"*f + "░"*(w-f)

def send_word_cards(chat_id, words, header=""):
    if header:
        bot.send_message(chat_id, header, parse_mode="Markdown")
    for w in words:
        kb = telebot.types.InlineKeyboardMarkup()
        kb.row(
            telebot.types.InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_{w['id']}"),
            telebot.types.InlineKeyboardButton("🗑 O'chirish",  callback_data=f"del_{w['id']}")
        )
        bot.send_message(chat_id,
            f"{BOX_ICON[min(w['box'],5)]} *{w['uz']}* → `{w['eng']}`",
            parse_mode="Markdown", reply_markup=kb)

def send_page(uid, chat_id, page=0):
    words = storage.get_all_words(uid)
    total = len(words)
    if total == 0:
        bot.send_message(chat_id, "📭 So'zlar ro'yxati bo'sh.", reply_markup=main_menu()); return
    words.sort(key=lambda w: (-w["box"], w["uz"]))
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, pages-1))
    send_word_cards(chat_id, words[page*PAGE_SIZE:(page+1)*PAGE_SIZE],
        header=f"📋 *So'zlarim* — {page+1}/{pages} sahifa ({total} ta jami)")
    nav = telebot.types.InlineKeyboardMarkup(); btns = []
    if page > 0:     btns.append(telebot.types.InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_{uid}_{page-1}"))
    if page+1 < pages: btns.append(telebot.types.InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_{uid}_{page+1}"))
    if btns: nav.row(*btns); bot.send_message(chat_id, "▶️ Navigatsiya:", reply_markup=nav)

# ── START ─────────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    user_state.pop(msg.chat.id, None); quiz_state.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id,
        f"👋 Salom, *{msg.from_user.first_name or 'Doʻstim'}*!\n\n"
        "🧠 *BRAINBRIDGE — So'z Yodlash Boti*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📖 Ingliz so'zlarini *Leitner tizimi* orqali samarali yodlang!\n\n"
        "📦 *Takrorlash jadvali:*\n"
        "┣ 🆕 Yangi  → darhol\n"
        "┣ 1️⃣ Quti 1 → 1 kun\n"
        "┣ 2️⃣ Quti 2 → 3 kun\n"
        "┣ 3️⃣ Quti 3 → 7 kun\n"
        "┣ 4️⃣ Quti 4 → 14 kun\n"
        "┗ 🏆 Quti 5 → 30 kun\n\n"
        "✅ *To'g'ri* → keyingi qutiga ⬆️\n"
        "❌ *Xato*   → Quti 1 ga ⬇️\n\n"
        "💡 Boshlash uchun *➕ So'z qo'shish* ni bosing!",
        parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🔙 Orqaga")
def cmd_back(msg):
    quiz_state.pop(msg.chat.id, None); user_state.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id, "🏠 *Bosh menyu*", parse_mode="Markdown", reply_markup=main_menu())

# ── SO'Z QO'SHISH ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "➕ So'z qo'shish")
def cmd_add(msg):
    user_state[msg.chat.id] = "adding"
    bot.send_message(msg.chat.id,
        "✏️ *So'z Qo'shish*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *Format:* `o'zbek = ingliz`\n\n"
        "📝 *Ko'p so'z (har qatorga birdan):*\n"
        "```\nkitob = book\nuy = house\n```\n\n"
        "🔗 *Sinonimlar (vergul bilan):*\n"
        "`ruxsat = allow, permit, let`\n\n"
        "⬇️ So'zlaringizni yuboring:",
        parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "adding")
def handle_add(msg):
    uid = msg.chat.id; added = updated = skipped = 0
    for line in msg.text.strip().split("\n"):
        line = line.strip()
        if not line or "=" not in line: continue
        uz, eng = line.split("=", 1)
        uz, eng = uz.strip().lower(), eng.strip().lower()
        if not uz or not eng: skipped += 1; continue
        r = storage.add_word(uid, uz, eng)
        if r == "added":   added += 1
        elif r == "updated": updated += 1
        else: skipped += 1
    user_state.pop(uid, None)
    parts = []
    if added:   parts.append(f"✅ *{added} ta* yangi so'z saqlandi")
    if updated: parts.append(f"♻️ *{updated} ta* so'z yangilandi")
    if skipped: parts.append(f"⏭ *{skipped} ta* o'tkazib yuborildi")
    bot.send_message(uid, "📊 *Natija:*\n" + ("\n".join(parts) or "⚠️ Hech narsa saqlanmadi."),
        parse_mode="Markdown", reply_markup=main_menu())

# ── TEST YANGI ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📝 Test (Yangi)")
def cmd_new_test(msg):
    uid = msg.chat.id
    words = storage.words_new(uid)
    if not words:
        bot.send_message(uid,
            "📭 *Yangi so'zlar yo'q!*\n\n"
            "💡 *➕ So'z qo'shish* orqali yangi so'zlar qo'shing.",
            parse_mode="Markdown", reply_markup=main_menu()); return
    random.shuffle(words)
    quiz_state[uid] = {"words": [(w["id"], w["uz"], w["eng"]) for w in words],
                       "index": 0, "correct": 0, "wrong": [], "used": [], "answers": [], "mode": "new"}
    bot.send_message(uid, f"🎯 *Test Boshlandi!*\n\n📚 Jami: *{len(words)} ta* yangi so'z\n💪 Muvaffaqiyat!",
        parse_mode="Markdown")
    ask_q(uid)

# ── TAKRORLASH ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🔁 Takrorlash")
def cmd_rep(msg):
    uid = msg.chat.id
    if not storage.words_due(uid):
        nxt_t = storage.next_due_time(uid)
        if nxt_t:
            diff = nxt_t - datetime.now()
            h = int(diff.total_seconds()//3600); m = int((diff.total_seconds()%3600)//60)
            bot.send_message(uid,
                f"⏳ *Hozircha tayyor so'z yo'q.*\n\n🕐 Keyingi takrorlash: *{h} soat {m} daqiqadan* so'ng",
                parse_mode="Markdown", reply_markup=main_menu())
        else:
            bot.send_message(uid,
                "📭 *Takrorlanadigan so'z yo'q.*\n\n💡 Avval *📝 Test (Yangi)* ni ishlatib so'zlarni qutilariga joylashtiring!",
                parse_mode="Markdown", reply_markup=main_menu())
        return
    due = len(storage.words_due(uid))
    bot.send_message(uid,
        f"🔁 *Takrorlash*\n\n🔴 Tayyor so'zlar: *{due} ta*\n\n📦 Qutini tanlang:",
        parse_mode="Markdown", reply_markup=box_menu(uid))

@bot.message_handler(func=lambda m: m.text and "📦 Quti" in m.text)
def cmd_box(msg):
    uid = msg.chat.id
    match = re.search(r"Quti\s+(\d)", msg.text)
    if not match: return
    box = int(match.group(1))
    words = storage.words_in_box(uid, box, due_only=True)
    if not words:
        total = storage.count_box(uid, box)
        if total > 0:
            nxt_t = storage.next_due_time_box(uid, box)
            if nxt_t:
                diff = nxt_t - datetime.now()
                h = int(diff.total_seconds()//3600); m = int((diff.total_seconds()%3600)//60)
                bot.send_message(uid,
                    f"⏳ *Hali vaqt kelmagan.*\n\n🕐 Tayyor bo'ladi: *{h} soat {m} daqiqadan* so'ng",
                    parse_mode="Markdown", reply_markup=box_menu(uid))
        else:
            bot.send_message(uid, f"📭 *Quti {box}* da so'z yo'q.", parse_mode="Markdown", reply_markup=box_menu(uid))
        return
    random.shuffle(words)
    quiz_state[uid] = {"words": [(w["id"], w["uz"], w["eng"]) for w in words],
                       "index": 0, "correct": 0, "wrong": [], "used": [], "answers": [],
                       "mode": f"box_{box}", "box": box}
    bot.send_message(uid, f"📦 *Quti {box} — Test*\n\n📚 Jami: *{len(words)} ta* so'z\n💪 Davom eting!",
        parse_mode="Markdown")
    ask_q(uid)

# ── SAVOL / JAVOB ─────────────────────────────────────────────────────────────
def ask_q(uid):
    quiz = quiz_state.get(uid)
    if not quiz: return
    if quiz["index"] >= len(quiz["words"]): finish(uid); return
    wid, uz, eng = quiz["words"][quiz["index"]]
    answers = [x.strip() for x in eng.split(",")]
    quiz["answers"] = answers; quiz["used"] = []
    total = len(quiz["words"]); cur_i = quiz["index"] + 1
    pct = int(quiz["index"]/total*100)
    text = (f"*{cur_i}/{total}* `[{bar(quiz['index'],total)}]` {pct}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🇺🇿 *{uz.upper()}*\n\n🇬🇧 Inglizcha tarjimasini yozing:")
    if len(answers) > 1: text += f"\n\n💡 _{len(answers)} ta to'g'ri javob bor_"
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: m.chat.id in quiz_state)
def handle_ans(msg):
    uid = msg.chat.id; quiz = quiz_state.get(uid)
    if not quiz or msg.text == "🔙 Orqaga": return
    answer = msg.text.strip().lower()
    wid, uz, eng = quiz["words"][quiz["index"]]
    answers = quiz["answers"]
    if answer in answers and answer not in quiz["used"]:
        quiz["used"].append(answer)
        rem = [a for a in answers if a not in quiz["used"]]
        if rem:
            bot.send_message(uid, f"✅ *To'g'ri!* Yana *{len(rem)} ta* sinonim qoldi...", parse_mode="Markdown"); return
        quiz["correct"] += 1
        w = storage.get_word_by_id(uid, wid)
        if w:
            old_box = w["box"]; new_box = min(old_box + 1, 5)
            storage.update_box(uid, wid, new_box)
            txt = "🏆 *Ajoyib! So'z yakunlandi!* Quti 5 ga yetdi!" if new_box == 5 else f"✅ *To'g'ri!*\n📦 Quti {old_box} → {new_box}"
            bot.send_message(uid, txt, parse_mode="Markdown")
    else:
        quiz["wrong"].append((uz, eng))
        storage.update_box(uid, wid, 1)
        bot.send_message(uid,
            f"❌ *Xato!*\n\n✔️ To'g'ri javob: *{eng}*\n📦 → Quti 1 ga qaytarildi",
            parse_mode="Markdown")
    quiz["index"] += 1; ask_q(uid)

def finish(uid):
    quiz = quiz_state.pop(uid, None)
    if not quiz: return
    correct = quiz["correct"]; wrong = quiz["wrong"]
    total = correct + len(wrong); pct = 0 if total == 0 else int(correct/total*100)
    rating = ("🏆 Mukammal natija!" if pct == 100 else "🌟 A'lo!" if pct >= 80
              else "👍 Yaxshi!" if pct >= 60 else "📚 O'rtacha" if pct >= 40 else "💪 Davom eting!")
    bot.send_message(uid,
        f"🏁 *Test Yakunlandi!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 `[{bar(correct,total)}]` *{pct}%*\n\n"
        f"✅ To'g'ri: *{correct}* ta\n"
        f"❌ Xato:   *{len(wrong)}* ta\n"
        f"📝 Jami:   *{total}* ta\n\n{rating}",
        parse_mode="Markdown", reply_markup=main_menu())
    if wrong:
        lines = "\n".join(f"  • *{u}* → `{e}`" for u, e in wrong)
        bot.send_message(uid, f"📋 *Xato so'zlar — takrorlang:*\n\n{lines}", parse_mode="Markdown")
    else:
        bot.send_message(uid, "🎉 *Barcha javoblar to'g'ri!* Zo'r natija! 🥳")

# ── STATISTIKA ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def cmd_stats(msg):
    uid = msg.chat.id; s = storage.stats(uid)
    if s["total"] == 0:
        bot.send_message(uid, "📭 *Statistika yo'q.*\n\n💡 Avval so'z qo'shing!",
            parse_mode="Markdown", reply_markup=main_menu()); return
    done_pct = int(s["done"]/s["total"]*100) if s["total"] else 0
    boxes_text = "".join(
        f"  {'┣' if i<5 else '┗'} {BOX_ICON[i]} Quti {i}: *{s['boxes'].get(i,0)}* ta\n"
        for i in range(1, 6))
    bot.send_message(uid,
        f"📊 *Statistika*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📚 Jami so'zlar:      *{s['total']}* ta\n"
        f"🆕 Yangi (test yo'q): *{s['new']}* ta\n"
        f"🔴 Bugun takrorlash:  *{s['due']}* ta\n"
        f"🏆 Yakunlangan:       *{s['done']}* ta\n\n"
        f"📈 Progress: `[{bar(s['done'],s['total'])}]` *{done_pct}%*\n\n"
        f"📦 *Qutilar:*\n{boxes_text}",
        parse_mode="Markdown", reply_markup=main_menu())

# ── SO'ZLARIM ─────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📋 So'zlarim")
def cmd_words(msg): send_page(msg.chat.id, msg.chat.id, page=0)

# ── QIDIRISH ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🔍 Qidirish")
def cmd_search(msg):
    user_state[msg.chat.id] = "searching"
    bot.send_message(msg.chat.id,
        "🔍 *Qidirish*\n━━━━━━━━━━━━━━━━━━━━\n\nO'zbek yoki ingliz tilida so'z kiriting:",
        parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "searching")
def handle_search(msg):
    uid = msg.chat.id; q = msg.text.strip().lower(); user_state.pop(uid, None)
    words = storage.search_words(uid, q)
    if not words:
        bot.send_message(uid, f"📭 *\"{q}\"* topilmadi.\n\n💡 Boshqa so'z bilan qidiring.",
            parse_mode="Markdown", reply_markup=main_menu()); return
    send_word_cards(uid, words[:20], header=f"🔍 *\"{q}\"* — {len(words)} ta natija:")
    bot.send_message(uid, "🏠 Bosh menyu:", reply_markup=main_menu())

# ── TOZALASH ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "❌ Tozalash")
def cmd_clear(msg):
    uid = msg.chat.id; s = storage.stats(uid)
    if s["total"] == 0:
        bot.send_message(uid, "📭 O'chiriladigan so'z yo'q.", reply_markup=main_menu()); return
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(telebot.types.InlineKeyboardButton("✅ Ha, barchasini o'chir", callback_data="clear_yes"),
           telebot.types.InlineKeyboardButton("❌ Bekor qilish",          callback_data="clear_no"))
    bot.send_message(uid,
        f"⚠️ *Diqqat!*\n\n*{s['total']} ta* so'z butunlay o'chiriladi.\nBu amalni bekor qilib bo'lmaydi!\n\nRostan davom etasizmi?",
        parse_mode="Markdown", reply_markup=kb)

# ── CALLBACKS ─────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data in ("clear_yes", "clear_no"))
def cb_clear(call):
    uid = call.message.chat.id
    if call.data == "clear_yes":
        count = storage.delete_all(uid)
        bot.edit_message_text(f"🗑 *{count} ta* so'z o'chirildi.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.send_message(uid, "🏠 Bosh menyu", reply_markup=main_menu())
    else:
        bot.edit_message_text("❌ Bekor qilindi.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("page_"))
def cb_page(call):
    # ✅ FIX: uid callback'dan emas, chat.id dan olinadi
    parts = call.data.split("_"); pg = int(parts[2])
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    send_page(uid, call.message.chat.id, page=pg)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_confirm_"))
def cb_del_confirm(call):
    wid = int(call.data.split("_")[2]); uid = call.message.chat.id
    uz = storage.delete_word(uid, wid)
    if not uz:
        bot.answer_callback_query(call.id, "⚠️ So'z topilmadi."); return
    bot.edit_message_text(f"🗑 *{uz}* o'chirildi.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    bot.answer_callback_query(call.id, "✅ O'chirildi!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_") and not c.data.startswith("del_confirm_"))
def cb_del(call):
    wid = int(call.data.split("_")[1]); uid = call.message.chat.id
    w = storage.get_word_by_id(uid, wid)
    if not w:
        bot.answer_callback_query(call.id, "⚠️ Topilmadi."); return
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(telebot.types.InlineKeyboardButton("✅ Ha, o'chir", callback_data=f"del_confirm_{wid}"),
           telebot.types.InlineKeyboardButton("❌ Bekor",       callback_data="del_cancel"))
    bot.edit_message_text(f"⚠️ *{w['uz']}* → `{w['eng']}`\n\nRostan o'chirmoqchimisiz?",
        call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "del_cancel")
def cb_del_cancel(call):
    bot.edit_message_text("❌ Bekor qilindi.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def cb_edit(call):
    wid = int(call.data.split("_")[1]); uid = call.message.chat.id
    w = storage.get_word_by_id(uid, wid)
    if not w:
        bot.answer_callback_query(call.id, "⚠️ Topilmadi."); return
    user_state[uid] = {"mode": "editing", "word_id": wid, "uz": w["uz"]}
    bot.answer_callback_query(call.id)
    bot.send_message(uid,
        f"✏️ *{w['uz']}* — tahrirlash\n\n"
        f"📌 Hozirgi tarjima: `{w['eng']}`\n\n"
        f"Yangi tarjimani yozing (sinonimlar vergul bilan):",
        parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: isinstance(user_state.get(m.chat.id), dict)
                                    and user_state[m.chat.id].get("mode") == "editing")
def handle_edit(msg):
    uid = msg.chat.id; st = user_state.pop(uid, {}); new_eng = msg.text.strip().lower()
    if not new_eng:
        bot.send_message(uid, "⚠️ Bo'sh qoldirish mumkin emas.", reply_markup=main_menu()); return
    storage.update_word_eng(uid, st["word_id"], new_eng)
    bot.send_message(uid,
        f"✅ *{st['uz']}* yangilandi!\n\n📌 Yangi tarjima: `{new_eng}`",
        parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid = msg.chat.id; st = user_state.get(uid)
    if not (uid in quiz_state or st == "adding" or st == "searching"
            or (isinstance(st, dict) and st.get("mode") == "editing")):
        bot.send_message(uid, "❓ Menyu tugmalaridan foydalaning.", reply_markup=main_menu())

log.info("🚀 BrainBridge bot ishga tushdi...")

# ── STARTUP MIGRATION: PostgreSQL → JSON (agar kerak bo'lsa) ──────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    migrated = storage.migrate_from_pg(DATABASE_URL)
    if migrated > 0:
        log.info(f"📦 {migrated} ta so'z muvaffaqiyatli ko'chirildi.")
else:
    log.info("ℹ️ DATABASE_URL yo'q — faqat JSON rejimida ishlamoqda.")

backup.start_scheduler()
bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=20)
