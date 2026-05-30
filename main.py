import telebot, os, random, re, logging
from dotenv import load_dotenv

load_dotenv()  # .env faylidagi muhit o'zgaruvchilarini yuklaydi (BOT_TOKEN, DATABASE_URL)

import storage

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
    kb.row("🔁 Takrorlash",    "📝 Barcha so'zlar")
    kb.row("📊 Statistika",    "🔍 Qidirish")
    kb.row("📋 So'zlarim",     "❌ Tozalash")
    kb.row("⚙️ Sozlamalar")
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
def esc(text) -> str:
    """Telegram 'Markdown' (legacy) maxsus belgilarini ekranlash.
    Foydalanuvchi kiritgan matn (so'z, ism) xabarni buzmasligi uchun."""
    if text is None:
        return ""
    return re.sub(r"([_*`\[])", r"\\\1", str(text))

def bar(done, total, w=10):
    f = int((done/total)*w) if total else 0
    return "█"*f + "░"*(w-f)

def fmt_wait(seconds) -> str:
    """Qolgan vaqtni (soniya) o'qiladigan matnga aylantiradi: 'X kun Y soat' / 'Y soat Z daqiqa'."""
    if seconds is None or seconds <= 0:
        return "hozir"
    total_min = int(seconds // 60)
    days, rem = divmod(total_min, 1440)
    hours, mins = divmod(rem, 60)
    if days > 0:
        return f"{days} kun {hours} soat"
    if hours > 0:
        return f"{hours} soat {mins} daqiqa"
    return f"{mins} daqiqa"

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
            f"{BOX_ICON[min(w['box'],5)]} *{esc(w['uz'])}* → `{esc(w['eng'])}`",
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
    storage.register_user(msg.chat.id, msg.from_user.first_name)
    bot.send_message(msg.chat.id,
        f"👋 Salom, *{esc(msg.from_user.first_name or 'Doʻstim')}*!\n\n"
        "🧠 *BRAINBRIDGE — So'z Yodlash Boti*\n\n"
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

# ── SOZLAMALAR / BILDIRISHNOMA ────────────────────────────────────────────────
def settings_kb(uid):
    on = storage.get_notify(uid)
    kb = telebot.types.InlineKeyboardMarkup()
    if on:
        kb.add(telebot.types.InlineKeyboardButton("🔕 Bildirishnomani o'chirish", callback_data="notify_off"))
    else:
        kb.add(telebot.types.InlineKeyboardButton("🔔 Bildirishnomani yoqish", callback_data="notify_on"))
    return kb

def settings_text(uid):
    on = storage.get_notify(uid)
    holat = "🔔 *Yoqilgan*" if on else "🔕 *O'chirilgan*"
    return (
        "⚙️ *Sozlamalar*\n\n"
        f"📢 Bildirishnoma: {holat}\n\n"
        "💡 Bildirishnoma yoqilganda, takrorlash vaqti kelgan so'zlaringiz "
        "haqida sizga avtomatik eslatma yuboriladi."
    )

@bot.message_handler(func=lambda m: m.text == "⚙️ Sozlamalar")
def cmd_settings(msg):
    uid = msg.chat.id
    storage.register_user(uid, msg.from_user.first_name)
    bot.send_message(uid, settings_text(uid), parse_mode="Markdown", reply_markup=settings_kb(uid))

@bot.callback_query_handler(func=lambda c: c.data in ("notify_on", "notify_off"))
def cb_notify(call):
    uid = call.message.chat.id
    enabled = (call.data == "notify_on")
    storage.set_notify(uid, enabled)
    bot.answer_callback_query(call.id, "🔔 Yoqildi!" if enabled else "🔕 O'chirildi!")
    try:
        bot.edit_message_text(settings_text(uid), uid, call.message.message_id,
            parse_mode="Markdown", reply_markup=settings_kb(uid))
    except Exception:
        pass

# ── SO'Z QO'SHISH ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "➕ So'z qo'shish")
def cmd_add(msg):
    user_state[msg.chat.id] = "adding"
    bot.send_message(msg.chat.id,
        "✏️ *So'z Qo'shish*\n\n"
        "📌 *Format:* `inglizcha-o'zbekcha`\n\n"
        "📝 *Ko'p so'z (har qatorga birdan):*\n"
        "```\nbook-kitob\nhouse-uy\n```\n\n"
        "🔗 *Sinonimlar (vergul bilan):*\n"
        "`allow, permit, let-ruxsat`\n\n"
        "⬇️ So'zlaringizni yuboring:",
        parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "adding")
def handle_add(msg):
    uid = msg.chat.id; added = updated = skipped = 0
    storage.register_user(uid, msg.from_user.first_name)
    for line in msg.text.strip().split("\n"):
        line = line.strip()
        if not line or "-" not in line: continue
        # Format: "inglizcha-o'zbekcha". Oxirgi "-" bo'yicha ajratamiz —
        # shunda inglizcha qismda chiziqcha bo'lishi mumkin (mas: "e-mail-pochta").
        eng, uz = line.rsplit("-", 1)
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

# ── TEST BARCHASI ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📝 Barcha so'zlar")
def cmd_all_test(msg):
    uid = msg.chat.id
    words = storage.get_all_words(uid)
    if not words:
        bot.send_message(uid,
            "📭 *So'zlar ro'yxati bo'sh!*\n\n"
            "💡 *➕ So'z qo'shish* orqali yangi so'zlar qo'shing.",
            parse_mode="Markdown", reply_markup=main_menu()); return
    random.shuffle(words)
    quiz_state[uid] = {"words": [(w["id"], w["uz"], w["eng"]) for w in words],
                       "index": 0, "correct": 0, "wrong": [], "used": [], "answers": [], "mode": "all"}
    bot.send_message(uid, f"✍️ *Barcha So'zlar — Yozma Test*\n\n📚 Jami: *{len(words)} ta* so'z\n📝 _O'zbekchasi beriladi — inglizchasini yozing. Bir nechta sinonim bo'lsa, hammasini kiriting. Xato bo'lsa so'z Quti 1 ga qaytadi._\n💪 Muvaffaqiyat!",
        parse_mode="Markdown")
    ask_q(uid)

# ── TAKRORLASH ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🔁 Takrorlash")
def cmd_rep(msg):
    uid = msg.chat.id
    if not storage.words_due(uid):
        secs = storage.seconds_until_due(uid)
        if secs is not None:
            bot.send_message(uid,
                f"⏳ *Hozircha tayyor so'z yo'q.*\n\n🕐 Keyingi takrorlash: *{fmt_wait(secs)}dan* so'ng",
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
            secs = storage.seconds_until_due_box(uid, box)
            if secs is not None:
                bot.send_message(uid,
                    f"⏳ *Hali vaqt kelmagan.*\n\n🕐 Tayyor bo'ladi: *{fmt_wait(secs)}dan* so'ng",
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
def ask_writing(uid):
    """Yozma rejim savoli: o'zbekcha ko'rsatiladi, user inglizchasini yozadi.
    Bir nechta sinonim bo'lsa — hammasini ketma-ket kiritish kerak."""
    quiz = quiz_state.get(uid)
    if not quiz: return
    if quiz["index"] >= len(quiz["words"]): finish(uid); return

    wid, uz, eng = quiz["words"][quiz["index"]]
    # Shu so'zning sinonimlarini kuzatish uchun holatni tayyorlaymiz
    syns = storage.parse_synonyms(eng)
    quiz["w_remaining"] = [s.casefold() for s in syns]  # hali kiritilmaganlar
    quiz["w_entered"] = []                               # to'g'ri kiritilganlar
    quiz["w_total_syn"] = len(syns)

    total = len(quiz["words"]); cur_i = quiz["index"] + 1
    pct = int(quiz["index"]/total*100)
    syn_hint = f"  ({quiz['w_total_syn']} ta sinonim)" if quiz["w_total_syn"] > 1 else ""
    text = (f"*{cur_i}/{total}*  `[{bar(quiz['index'],total)}]`  {pct}%\n\n"
            f"🇺🇿 *{esc(uz.upper())}*\n\n"
            f"✍️ Inglizcha tarjimasini yozing{syn_hint}:")
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=back_menu())

def handle_writing_answer(msg):
    """Yozma rejimda foydalanuvchi javobini tekshiradi.
    - Barcha sinonimlar kiritilsa → to'g'ri (quti oshadi)
    - Xato javob → so'z Quti 1 ga qaytadi"""
    uid = msg.chat.id
    quiz = quiz_state.get(uid)
    if not quiz: return
    if quiz["index"] >= len(quiz["words"]):
        finish(uid); return

    wid, uz, eng = quiz["words"][quiz["index"]]
    user_ans = " ".join(msg.text.split()).casefold()  # trim + bo'shliq + casefold

    # Agar holat hali tayyorlanmagan bo'lsa (xavfsizlik uchun), tayyorlaymiz
    if "w_remaining" not in quiz:
        syns = storage.parse_synonyms(eng)
        quiz["w_remaining"] = [s.casefold() for s in syns]
        quiz["w_entered"] = []
        quiz["w_total_syn"] = len(syns)

    remaining = quiz["w_remaining"]
    entered = quiz["w_entered"]

    if user_ans in remaining:
        # To'g'ri sinonim kiritildi
        remaining.remove(user_ans)
        entered.append(user_ans)
        if not remaining:
            # Barcha sinonimlar kiritildi → so'z to'g'ri yakunlandi
            quiz["correct"] += 1
            w = storage.get_word_by_id(uid, wid)
            old_box = w["box"] if w else 0
            new_box = min(old_box + 1, 5)
            storage.update_box(uid, wid, new_box)
            box_txt = "🏆 *So'z yakunlandi!* Quti 5 ga yetdi!" if new_box == 5 else f"📦 Quti {old_box} → {new_box}"
            bot.send_message(uid,
                f"✅ *To'g'ri!*\n\n🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n\n{box_txt}",
                parse_mode="Markdown")
            quiz["index"] += 1
            ask_q(uid)
        else:
            # Yana sinonim qoldi — o'sha so'zda qolamiz
            bot.send_message(uid,
                f"✅ To'g'ri! Yana *{len(remaining)} ta* sinonim qoldi.\n"
                f"✍️ Keyingisini kiriting:",
                parse_mode="Markdown")
        return

    if user_ans in entered:
        # Allaqachon kiritilgan sinonim — jarima yo'q, qayta so'raymiz
        bot.send_message(uid,
            f"♻️ Buni allaqachon yozdingiz. Boshqa sinonimni kiriting "
            f"(*{len(remaining)} ta* qoldi):",
            parse_mode="Markdown")
        return

    # Noto'g'ri javob → so'z Quti 1 ga qaytadi
    quiz["wrong"].append((uz, eng))
    storage.update_box(uid, wid, 1)
    bot.send_message(uid,
        f"❌ *Xato!*\n\n"
        f"Siz yozdingiz: _{esc(msg.text.strip())}_\n"
        f"✔️ To'g'ri javob: *{esc(eng)}*\n\n"
        f"🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n"
        f"📦 → Quti 1 ga qaytarildi",
        parse_mode="Markdown")
    quiz["index"] += 1
    ask_q(uid)

def ask_q(uid):
    quiz = quiz_state.get(uid)
    if not quiz: return
    if quiz["index"] >= len(quiz["words"]): finish(uid); return

    # "Barcha so'zlar" — yozma (writing) rejim; qolganlari variantli (choice)
    if quiz.get("mode") == "all":
        ask_writing(uid); return

    wid, uz, eng = quiz["words"][quiz["index"]]
    
    # 1. To'g'ri javob
    correct_ans = eng.split(",")[0].strip()  # Birinchi sinonimni olamiz
    
    # 2. Noto'g'ri javoblar uchun "pool" ni test boshida bir marta keshlaymiz
    #    (har savolda DB ga murojaat qilmaslik uchun).
    pool = quiz.get("distractor_pool")
    if pool is None:
        all_words = storage.get_all_words(uid)
        seen, pool = set(), []
        for w in all_words:
            ans = w["eng"].split(",")[0].strip()
            key = ans.lower()
            if ans and key not in seen:
                seen.add(key)
                pool.append(ans)
        quiz["distractor_pool"] = pool
    
    correct_synonyms = {s.strip().lower() for s in eng.split(",")}
    available_wrong = [a for a in pool if a.lower() not in correct_synonyms]
    
    # Agar lug'atda yetarli so'z bo'lmasa, sun'iy noto'g'ri javoblar qo'shamiz (fallback)
    if len(available_wrong) < 3:
        fallbacks = ["apple", "book", "car", "house", "computer", "water", "friend", "money", "time", "day"]
        existing = {a.lower() for a in available_wrong}
        for f in fallbacks:
            if f.lower() not in correct_synonyms and f.lower() not in existing:
                available_wrong.append(f)
                existing.add(f.lower())
                
    # 3 tasini tasodifiy tanlab olamiz
    random.shuffle(available_wrong)
    wrong_answers = available_wrong[:3]
    
    # 3. To'g'ri va noto'g'ri javoblarni birlashtiramiz va aralashtiramiz
    options = wrong_answers + [correct_ans]
    random.shuffle(options)
    
    # To'g'ri javob indeksini topamiz
    correct_idx = options.index(correct_ans)
    
    # State ga saqlaymiz
    quiz["options"] = options
    quiz["correct_idx"] = correct_idx
    
    q_idx = quiz["index"]  # Shu savolning indeksi (stale-click tekshiruvi uchun)
    total = len(quiz["words"]); cur_i = q_idx + 1
    pct = int(q_idx/total*100)
    
    # Progress matni
    text = (f"*{cur_i}/{total}*  `[{bar(q_idx,total)}]`  {pct}%\n\n"
            f"🇺🇿 Tarjima qiling: *{esc(uz.upper())}*")
            
    # Variantlarni klaviatura (inline button) orqali ko'rsatamiz
    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    
    for i, opt in enumerate(options):
        # callback_data: quiz_<savol_indeksi>_<variant_indeksi>
        btn = telebot.types.InlineKeyboardButton(f"{opt}", callback_data=f"quiz_{q_idx}_{i}")
        kb.add(btn)
        
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("quiz_"))
def cb_quiz_ans(call):
    uid = call.message.chat.id
    quiz = quiz_state.get(uid)
    if not quiz:
        bot.answer_callback_query(call.id, "⚠️ Test yakunlangan yoki bekor qilingan.")
        return

    # Call datadan javob indeksini olish ("quiz_<q_idx>_<variant_idx>")
    parts = call.data.split("_")
    if len(parts) < 3:
        bot.answer_callback_query(call.id); return
    q_idx = int(parts[1]); selected_idx = int(parts[2])

    # Stale-click himoyasi: eski/takror bosilgan savol joriy savol bilan mos kelmasa,
    # noto'g'ri so'zni baholab qo'ymaslik uchun e'tiborsiz qoldiramiz.
    if q_idx != quiz["index"]:
        bot.answer_callback_query(call.id, "⏭ Bu savol allaqachon javoblangan.")
        try:
            bot.edit_message_reply_markup(chat_id=uid, message_id=call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    wid, uz, eng = quiz["words"][quiz["index"]]
    correct_idx = quiz.get("correct_idx", -1)

    # Foydalanuvchi to'g'ri yoki noto'g'ri ekanligini tekshirish
    is_correct = (selected_idx == correct_idx)

    bot.answer_callback_query(call.id)
    
    # Xabarni o'zgartirib tugmalarni olib tashlash
    try:
        bot.edit_message_reply_markup(chat_id=uid, message_id=call.message.message_id, reply_markup=None)
    except Exception:
        pass

    # "Barcha so'zlar" — bu MASHQ rejimi: Leitner jadvaliga (box/next_review) tegmaydi.
    # Faqat "new" va "box_N" rejimlari qutilarni o'zgartiradi.
    practice = (quiz.get("mode") == "all")

    if is_correct:
        quiz["correct"] += 1
        w = storage.get_word_by_id(uid, wid)
        if w:
            old_box = w["box"]
            if practice:
                txt = f"✅ *To'g'ri!*\n\n🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n\n📝 _Mashq rejimi — quti o'zgarmaydi_"
            else:
                new_box = min(old_box + 1, 5)
                storage.update_box(uid, wid, new_box)
                txt = f"✅ *To'g'ri!*\n\n🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n\n🏆 *So'z yakunlandi!* Quti 5 ga yetdi!" if new_box == 5 else f"✅ *To'g'ri!*\n\n🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n\n📦 Quti {old_box} → {new_box}"
            bot.send_message(uid, txt, parse_mode="Markdown")
    else:
        quiz["wrong"].append((uz, eng))
        if not practice:
            storage.update_box(uid, wid, 1)

        # Foydalanuvchi tanlagan noto'g'ri javob matnini topish
        selected_text = "Noma'lum"
        if "options" in quiz and 0 <= selected_idx < len(quiz["options"]):
            selected_text = quiz["options"][selected_idx]

        footer = "📝 _Mashq rejimi — quti o'zgarmaydi_" if practice else "📦 → Quti 1 ga qaytarildi"
        bot.send_message(uid,
            f"❌ *Xato!*\n\n"
            f"Siz tanladingiz: _{esc(selected_text)}_\n"
            f"✔️ To'g'ri javob: *{esc(eng)}*\n\n"
            f"🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n"
            f"{footer}",
            parse_mode="Markdown")

    quiz["index"] += 1
    ask_q(uid)

def finish(uid):
    quiz = quiz_state.pop(uid, None)
    if not quiz: return
    correct = quiz["correct"]; wrong = quiz["wrong"]
    total = correct + len(wrong); pct = 0 if total == 0 else int(correct/total*100)
    rating = ("🏆 Mukammal natija!" if pct == 100 else "🌟 A'lo!" if pct >= 80
              else "👍 Yaxshi!" if pct >= 60 else "📚 O'rtacha" if pct >= 40 else "💪 Davom eting!")
    bot.send_message(uid,
        f"🏁 *Test Yakunlandi!*\n\n"
        f"📊 `[{bar(correct,total)}]` *{pct}%*\n\n"
        f"✅ To'g'ri: *{correct}* ta\n"
        f"❌ Xato:   *{len(wrong)}* ta\n"
        f"📝 Jami:   *{total}* ta\n\n{rating}",
        parse_mode="Markdown", reply_markup=main_menu())
    if wrong:
        lines = "\n".join(f"  • *{esc(u)}* → `{esc(e)}`" for u, e in wrong)
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
        f"📊 *Statistika*\n\n"
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
        "🔍 *Qidirish*\n\nO'zbek yoki ingliz tilida so'z kiriting:",
        parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "searching")
def handle_search(msg):
    uid = msg.chat.id; q = msg.text.strip().lower(); user_state.pop(uid, None)
    words = storage.search_words(uid, q)
    if not words:
        bot.send_message(uid, f"📭 *\"{esc(q)}\"* topilmadi.\n\n💡 Boshqa so'z bilan qidiring.",
            parse_mode="Markdown", reply_markup=main_menu()); return
    send_word_cards(uid, words[:20], header=f"🔍 *\"{esc(q)}\"* — {len(words)} ta natija:")
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
    bot.edit_message_text(f"🗑 *{esc(uz)}* o'chirildi.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
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
    bot.edit_message_text(f"⚠️ *{esc(w['uz'])}* → `{esc(w['eng'])}`\n\nRostan o'chirmoqchimisiz?",
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
        f"✏️ *{esc(w['uz'])}* — tahrirlash\n\n"
        f"📌 Hozirgi tarjima: `{esc(w['eng'])}`\n\n"
        f"Yangi tarjimani yozing (sinonimlar vergul bilan):",
        parse_mode="Markdown", reply_markup=back_menu())

@bot.message_handler(func=lambda m: isinstance(user_state.get(m.chat.id), dict)
                                    and user_state[m.chat.id].get("mode") == "editing")
def handle_edit(msg):
    uid = msg.chat.id; st = user_state.pop(uid, {}); raw = msg.text.strip().lower()
    cleaned_list = storage.parse_synonyms(raw)
    if not cleaned_list:
        bot.send_message(uid, "⚠️ Bo'sh qoldirish mumkin emas.", reply_markup=main_menu()); return
    cleaned = ", ".join(cleaned_list)
    storage.update_word_eng(uid, st["word_id"], cleaned)
    bot.send_message(uid,
        f"✅ *{esc(st['uz'])}* yangilandi!\n\n📌 Yangi tarjima: `{esc(cleaned)}`",
        parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.chat.id in quiz_state
                                    and quiz_state[m.chat.id].get("mode") == "all"
                                    and isinstance(m.text, str))
def handle_writing(msg):
    handle_writing_answer(msg)

@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid = msg.chat.id; st = user_state.get(uid)
    if not (uid in quiz_state or st == "adding" or st == "searching"
            or (isinstance(st, dict) and st.get("mode") == "editing")):
        bot.send_message(uid, "❓ Menyu tugmalaridan foydalaning.", reply_markup=main_menu())

log.info("🚀 BrainBridge bot ishga tushdi...")
import notifier
notifier.start_scheduler(bot)
bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=20)
