import telebot, os, random, re, logging, signal, sys, threading
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
import storage

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan!")

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

BOX_ICON = ["🆕", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "🏆"]
PAGE_SIZE = 8

# Thread-safe state with locks
_state_lock = threading.Lock()
user_state: dict = {}
quiz_state: dict = {}



# ── MARKDOWN ESCAPE ───────────────────────────────────────────────────────────
def esc(text: str) -> str:
    """Markdown maxsus belgilarini escape qiladi."""
    if not text:
        return ""
    for ch in ['_', '*', '`', '[']:
        text = text.replace(ch, f'\\{ch}')
    return text


# ── THREAD-SAFE STATE HELPERS ─────────────────────────────────────────────────
def get_user_state(uid: int):
    with _state_lock:
        return user_state.get(uid)


def set_user_state(uid: int, value):
    with _state_lock:
        user_state[uid] = value


def pop_user_state(uid: int):
    with _state_lock:
        return user_state.pop(uid, None)


def get_quiz_state(uid: int):
    with _state_lock:
        return quiz_state.get(uid)


def set_quiz_state(uid: int, value):
    with _state_lock:
        quiz_state[uid] = value


def pop_quiz_state(uid: int):
    with _state_lock:
        return quiz_state.pop(uid, None)



# ── MENUS ─────────────────────────────────────────────────────────────────────
def main_menu():
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ So'z qo'shish", "📝 Test (Yangi)")
    kb.row("🔁 Takrorlash", "📝 Barcha so'zlar")
    kb.row("📊 Statistika", "🔍 Qidirish")
    kb.row("📋 So'zlarim", "❌ Tozalash")
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
    f = int((done / total) * w) if total else 0
    return "█" * f + "░" * (w - f)


def safe_send(uid, text, **kwargs):
    """Xabar yuborishda xatoliklarni ushlaydi, bloklangan userni belgilaydi."""
    try:
        return bot.send_message(uid, text, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if e.error_code == 403:
            storage.add_blocked_user(uid)
            log.info(f"🚫 User {uid} botni bloklagan — bazaga yozildi.")
        else:
            log.warning(f"⚠️ Xabar yuborib bo'lmadi (user={uid}): {e}")
        return None
    except Exception as e:
        log.warning(f"⚠️ Xabar yuborib bo'lmadi (user={uid}): {e}")
        return None


def send_word_cards(chat_id, words, header=""):
    if header:
        safe_send(chat_id, header, parse_mode="Markdown")
    for w in words:
        kb = telebot.types.InlineKeyboardMarkup()
        kb.row(
            telebot.types.InlineKeyboardButton("✏️", callback_data=f"edit_{w['id']}"),
            telebot.types.InlineKeyboardButton("🗑", callback_data=f"del_{w['id']}")
        )
        safe_send(chat_id,
            f"{BOX_ICON[min(w['box'], 5)]} *{esc(w['uz'])}* → `{esc(w['eng'])}`",
            parse_mode="Markdown", reply_markup=kb)



def send_page(uid, chat_id, page=0):
    words = storage.get_all_words(uid)
    total = len(words)
    if total == 0:
        safe_send(chat_id, "📭 So'zlar ro'yxati bo'sh.", reply_markup=main_menu())
        return
    words.sort(key=lambda w: (-w["box"], w["uz"]))
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, pages - 1))
    send_word_cards(chat_id, words[page * PAGE_SIZE:(page + 1) * PAGE_SIZE],
        header=f"📋 *So'zlarim* — {page + 1}/{pages} sahifa ({total} ta jami)")
    nav = telebot.types.InlineKeyboardMarkup()
    btns = []
    if page > 0:
        btns.append(telebot.types.InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_{page - 1}"))
    if page + 1 < pages:
        btns.append(telebot.types.InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_{page + 1}"))
    if btns:
        nav.row(*btns)
        safe_send(chat_id, "▶️ Navigatsiya:", reply_markup=nav)


# ── START ─────────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.chat.id
    pop_user_state(uid)
    pop_quiz_state(uid)
    # User qayta start bersa, blokdan chiqarish
    storage.remove_blocked_user(uid)
    safe_send(uid,
        f"👋 Salom, *{esc(msg.from_user.first_name or 'Doʻstim')}*!\n\n"
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
    pop_quiz_state(msg.chat.id)
    pop_user_state(msg.chat.id)
    safe_send(msg.chat.id, "🏠 *Bosh menyu*", parse_mode="Markdown", reply_markup=main_menu())


# ── SO'Z QO'SHISH ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "➕ So'z qo'shish")
def cmd_add(msg):
    set_user_state(msg.chat.id, "adding")
    safe_send(msg.chat.id,
        "✏️ *So'z Qo'shish*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *Format:* `o'zbek = ingliz`\n\n"
        "📝 *Ko'p so'z (har qatorga birdan):*\n"
        "```\nkitob = book\nuy = house\n```\n\n"
        "🔗 *Sinonimlar (vergul bilan):*\n"
        "`ruxsat = allow, permit, let`\n\n"
        "⬇️ So'zlaringizni yuboring:",
        parse_mode="Markdown", reply_markup=back_menu())


@bot.message_handler(func=lambda m: get_user_state(m.chat.id) == "adding")
def handle_add(msg):
    uid = msg.chat.id
    added = updated = skipped = 0
    for line in msg.text.strip().split("\n"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        uz, eng = line.split("=", 1)
        uz, eng = uz.strip().lower(), eng.strip().lower()
        if not uz or not eng:
            skipped += 1
            continue
        r = storage.add_word(uid, uz, eng)
        if r == "added":
            added += 1
        elif r == "updated":
            updated += 1
        else:
            skipped += 1
    pop_user_state(uid)
    parts = []
    if added:
        parts.append(f"✅ *{added} ta* yangi so'z saqlandi")
    if updated:
        parts.append(f"♻️ *{updated} ta* so'z yangilandi")
    if skipped:
        parts.append(f"⏭ *{skipped} ta* o'tkazib yuborildi")
    safe_send(uid, "📊 *Natija:*\n" + ("\n".join(parts) or "⚠️ Hech narsa saqlanmadi."),
        parse_mode="Markdown", reply_markup=main_menu())



# ── TEST YANGI ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📝 Test (Yangi)")
def cmd_new_test(msg):
    uid = msg.chat.id
    words = storage.words_new(uid)
    if not words:
        safe_send(uid,
            "📭 *Yangi so'zlar yo'q!*\n\n"
            "💡 *➕ So'z qo'shish* orqali yangi so'zlar qo'shing.",
            parse_mode="Markdown", reply_markup=main_menu())
        return
    random.shuffle(words)
    set_quiz_state(uid, {
        "words": [(w["id"], w["uz"], w["eng"]) for w in words],
        "index": 0, "correct": 0, "wrong": [], "mode": "new"
    })
    safe_send(uid, f"🎯 *Test Boshlandi!*\n\n📚 Jami: *{len(words)} ta* yangi so'z\n💪 Muvaffaqiyat!",
        parse_mode="Markdown")
    ask_q(uid)


# ── TEST BARCHASI ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📝 Barcha so'zlar")
def cmd_all_test(msg):
    uid = msg.chat.id
    words = storage.get_all_words(uid)
    if not words:
        safe_send(uid,
            "📭 *So'zlar ro'yxati bo'sh!*\n\n"
            "💡 *➕ So'z qo'shish* orqali yangi so'zlar qo'shing.",
            parse_mode="Markdown", reply_markup=main_menu())
        return
    random.shuffle(words)
    set_quiz_state(uid, {
        "words": [(w["id"], w["uz"], w["eng"]) for w in words],
        "index": 0, "correct": 0, "wrong": [], "mode": "all"
    })
    safe_send(uid, f"🎯 *Barcha So'zlar Testi!*\n\n📚 Jami: *{len(words)} ta* so'z\n💪 Muvaffaqiyat!",
        parse_mode="Markdown")
    ask_q(uid)



# ── TAKRORLASH ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🔁 Takrorlash")
def cmd_rep(msg):
    uid = msg.chat.id
    due_words = storage.words_due(uid)
    if not due_words:
        nxt_t = storage.next_due_time(uid)
        if nxt_t:
            now = datetime.now(timezone.utc)
            if nxt_t.tzinfo is None:
                nxt_t = nxt_t.replace(tzinfo=timezone.utc)
            diff = nxt_t - now
            h = int(diff.total_seconds() // 3600)
            m = int((diff.total_seconds() % 3600) // 60)
            safe_send(uid,
                f"⏳ *Hozircha tayyor so'z yo'q.*\n\n🕐 Keyingi takrorlash: *{h} soat {m} daqiqadan* so'ng",
                parse_mode="Markdown", reply_markup=main_menu())
        else:
            safe_send(uid,
                "📭 *Takrorlanadigan so'z yo'q.*\n\n"
                "💡 Avval *📝 Test (Yangi)* ni ishlatib so'zlarni qutilariga joylashtiring!",
                parse_mode="Markdown", reply_markup=main_menu())
        return
    safe_send(uid,
        f"🔁 *Takrorlash*\n\n🔴 Tayyor so'zlar: *{len(due_words)} ta*\n\n📦 Qutini tanlang:",
        parse_mode="Markdown", reply_markup=box_menu(uid))


@bot.message_handler(func=lambda m: m.text and "📦 Quti" in m.text)
def cmd_box(msg):
    uid = msg.chat.id
    match = re.search(r"Quti\s+(\d)", msg.text)
    if not match:
        return
    box = int(match.group(1))
    words = storage.words_in_box(uid, box, due_only=True)
    if not words:
        total = storage.count_box(uid, box)
        if total > 0:
            nxt_t = storage.next_due_time_box(uid, box)
            if nxt_t:
                now = datetime.now(timezone.utc)
                if nxt_t.tzinfo is None:
                    nxt_t = nxt_t.replace(tzinfo=timezone.utc)
                diff = nxt_t - now
                h = int(diff.total_seconds() // 3600)
                m = int((diff.total_seconds() % 3600) // 60)
                safe_send(uid,
                    f"⏳ *Hali vaqt kelmagan.*\n\n🕐 Tayyor bo'ladi: *{h} soat {m} daqiqadan* so'ng",
                    parse_mode="Markdown", reply_markup=box_menu(uid))
        else:
            safe_send(uid, f"📭 *Quti {box}* da so'z yo'q.",
                parse_mode="Markdown", reply_markup=box_menu(uid))
        return
    random.shuffle(words)
    set_quiz_state(uid, {
        "words": [(w["id"], w["uz"], w["eng"]) for w in words],
        "index": 0, "correct": 0, "wrong": [],
        "mode": f"box_{box}", "box": box
    })
    safe_send(uid, f"📦 *Quti {box} — Test*\n\n📚 Jami: *{len(words)} ta* so'z\n💪 Davom eting!",
        parse_mode="Markdown")
    ask_q(uid)



# ── SAVOL / JAVOB ─────────────────────────────────────────────────────────────
def ask_q(uid):
    quiz = get_quiz_state(uid)
    if not quiz:
        return
    if quiz["index"] >= len(quiz["words"]):
        finish(uid)
        return

    wid, uz, eng = quiz["words"][quiz["index"]]
    correct_ans = eng.split(",")[0].strip()

    # Samarali: faqat 10 ta random noto'g'ri javob olish (1 query)
    wrong_pool = storage.get_random_eng_words(uid, wid, limit=10)
    correct_synonyms = [s.strip().lower() for s in eng.split(",")]
    available_wrong = [a for a in wrong_pool if a.lower() not in correct_synonyms]

    # Fallback
    if len(available_wrong) < 3:
        fallbacks = ["apple", "book", "car", "house", "computer",
                     "water", "friend", "money", "time", "day"]
        for f in fallbacks:
            if f.lower() not in correct_synonyms and f not in available_wrong:
                available_wrong.append(f)
            if len(available_wrong) >= 3:
                break

    random.shuffle(available_wrong)
    wrong_answers = available_wrong[:3]

    options = wrong_answers + [correct_ans]
    random.shuffle(options)
    correct_idx = options.index(correct_ans)

    # State yangilash
    quiz["options"] = options
    quiz["correct_idx"] = correct_idx
    set_quiz_state(uid, quiz)

    total = len(quiz["words"])
    cur_i = quiz["index"] + 1
    pct = int(quiz["index"] / total * 100)

    text = (f"*{cur_i}/{total}* `[{bar(quiz['index'], total)}]` {pct}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🇺🇿 Tarjima qiling: *{esc(uz.upper())}*")

    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    for i, opt in enumerate(options):
        btn = telebot.types.InlineKeyboardButton(opt, callback_data=f"quiz_{i}")
        kb.add(btn)

    safe_send(uid, text, parse_mode="Markdown", reply_markup=kb)



@bot.callback_query_handler(func=lambda c: c.data.startswith("quiz_"))
def cb_quiz_ans(call):
    uid = call.message.chat.id
    quiz = get_quiz_state(uid)
    if not quiz:
        bot.answer_callback_query(call.id, "⚠️ Test yakunlangan.")
        return

    try:
        selected_idx = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        return

    wid, uz, eng = quiz["words"][quiz["index"]]
    correct_idx = quiz.get("correct_idx", -1)
    is_correct = (selected_idx == correct_idx)

    bot.answer_callback_query(call.id)

    try:
        bot.edit_message_reply_markup(chat_id=uid, message_id=call.message.message_id, reply_markup=None)
    except Exception:
        pass

    if is_correct:
        quiz["correct"] += 1
        w = storage.get_word_by_id(uid, wid)
        if w:
            old_box = w["box"]
            new_box = min(old_box + 1, 5)
            storage.update_box(uid, wid, new_box)
            if new_box == 5:
                txt = f"✅ *To'g'ri!*\n\n🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n\n🏆 *So'z yakunlandi!*"
            else:
                txt = f"✅ *To'g'ri!*\n\n🇺🇿 {esc(uz.upper())} → 🇬🇧 {esc(eng)}\n\n📦 Quti {old_box} → {new_box}"
            safe_send(uid, txt, parse_mode="Markdown")
    else:
        quiz["wrong"].append((uz, eng))
        storage.update_box(uid, wid, 1)
        selected_text = ""
        if "options" in quiz and 0 <= selected_idx < len(quiz["options"]):
            selected_text = quiz["options"][selected_idx]
        safe_send(uid,
            f"❌ *Xato!*\n\n"
            f"Siz tanladingiz: {esc(selected_text)}\n"
            f"✔️ To'g'ri javob: *{esc(eng)}*\n\n"
            f"📦 → Quti 1 ga qaytarildi",
            parse_mode="Markdown")

    quiz["index"] += 1
    set_quiz_state(uid, quiz)
    ask_q(uid)



def finish(uid):
    quiz = pop_quiz_state(uid)
    if not quiz:
        return
    correct = quiz["correct"]
    wrong = quiz["wrong"]
    total = correct + len(wrong)
    pct = 0 if total == 0 else int(correct / total * 100)
    rating = ("🏆 Mukammal!" if pct == 100 else "🌟 A'lo!" if pct >= 80
              else "👍 Yaxshi!" if pct >= 60 else "📚 O'rtacha" if pct >= 40 else "💪 Davom eting!")
    safe_send(uid,
        f"🏁 *Test Yakunlandi!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 `[{bar(correct, total)}]` *{pct}%*\n\n"
        f"✅ To'g'ri: *{correct}* ta\n"
        f"❌ Xato:   *{len(wrong)}* ta\n"
        f"📝 Jami:   *{total}* ta\n\n{rating}",
        parse_mode="Markdown", reply_markup=main_menu())
    if wrong:
        lines = "\n".join(f"  • *{esc(u)}* → `{esc(e)}`" for u, e in wrong)
        safe_send(uid, f"📋 *Xato so'zlar — takrorlang:*\n\n{lines}", parse_mode="Markdown")


# ── STATISTIKA ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def cmd_stats(msg):
    uid = msg.chat.id
    s = storage.stats(uid)
    if s["total"] == 0:
        safe_send(uid, "📭 *Statistika yo'q.*\n\n💡 Avval so'z qo'shing!",
            parse_mode="Markdown", reply_markup=main_menu())
        return
    done_pct = int(s["done"] / s["total"] * 100) if s["total"] else 0
    boxes_text = "".join(
        f"  {'┣' if i < 5 else '┗'} {BOX_ICON[i]} Quti {i}: *{s['boxes'].get(i, 0)}* ta\n"
        for i in range(1, 6))
    safe_send(uid,
        f"📊 *Statistika*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📚 Jami so'zlar:      *{s['total']}* ta\n"
        f"🆕 Yangi (test yo'q): *{s['new']}* ta\n"
        f"🔴 Bugun takrorlash:  *{s['due']}* ta\n"
        f"🏆 Yakunlangan:       *{s['done']}* ta\n\n"
        f"📈 Progress: `[{bar(s['done'], s['total'])}]` *{done_pct}%*\n\n"
        f"📦 *Qutilar:*\n{boxes_text}",
        parse_mode="Markdown", reply_markup=main_menu())



# ── SO'ZLARIM ─────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📋 So'zlarim")
def cmd_words(msg):
    send_page(msg.chat.id, msg.chat.id, page=0)


# ── QIDIRISH ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🔍 Qidirish")
def cmd_search(msg):
    set_user_state(msg.chat.id, "searching")
    safe_send(msg.chat.id,
        "🔍 *Qidirish*\n━━━━━━━━━━━━━━━━━━━━\n\nO'zbek yoki ingliz tilida so'z kiriting:",
        parse_mode="Markdown", reply_markup=back_menu())


@bot.message_handler(func=lambda m: get_user_state(m.chat.id) == "searching")
def handle_search(msg):
    uid = msg.chat.id
    q = msg.text.strip().lower()
    pop_user_state(uid)
    words = storage.search_words(uid, q)
    if not words:
        safe_send(uid, f"📭 *\"{esc(q)}\"* topilmadi.\n\n💡 Boshqa so'z bilan qidiring.",
            parse_mode="Markdown", reply_markup=main_menu())
        return
    send_word_cards(uid, words[:20], header=f"🔍 *\"{esc(q)}\"* — {len(words)} ta natija:")
    safe_send(uid, "🏠 Bosh menyu:", reply_markup=main_menu())


# ── TOZALASH ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "❌ Tozalash")
def cmd_clear(msg):
    uid = msg.chat.id
    s = storage.stats(uid)
    if s["total"] == 0:
        safe_send(uid, "📭 O'chiriladigan so'z yo'q.", reply_markup=main_menu())
        return
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("✅ Ha, o'chir", callback_data="clear_yes"),
        telebot.types.InlineKeyboardButton("❌ Bekor", callback_data="clear_no")
    )
    safe_send(uid,
        f"⚠️ *Diqqat!*\n\n*{s['total']} ta* so'z o'chiriladi.\nBekor qilib bo'lmaydi!\n\nDavom etasizmi?",
        parse_mode="Markdown", reply_markup=kb)



# ── CALLBACKS ─────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data in ("clear_yes", "clear_no"))
def cb_clear(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "clear_yes":
        count = storage.delete_all(uid)
        try:
            bot.edit_message_text(f"🗑 *{count} ta* so'z o'chirildi.",
                uid, call.message.message_id, parse_mode="Markdown")
        except Exception:
            pass
        safe_send(uid, "🏠 Bosh menyu", reply_markup=main_menu())
    else:
        try:
            bot.edit_message_text("❌ Bekor qilindi.", uid, call.message.message_id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("page_"))
def cb_page(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        pg = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        return
    send_page(uid, uid, page=pg)


@bot.callback_query_handler(func=lambda c: c.data.startswith("del_confirm_"))
def cb_del_confirm(call):
    uid = call.message.chat.id
    try:
        wid = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        return
    uz = storage.delete_word(uid, wid)
    if not uz:
        bot.answer_callback_query(call.id, "⚠️ So'z topilmadi.")
        return
    try:
        bot.edit_message_text(f"🗑 *{esc(uz)}* o'chirildi.",
            uid, call.message.message_id, parse_mode="Markdown")
    except Exception:
        pass
    bot.answer_callback_query(call.id, "✅ O'chirildi!")


@bot.callback_query_handler(func=lambda c: c.data.startswith("del_") and not c.data.startswith("del_confirm_"))
def cb_del(call):
    uid = call.message.chat.id
    try:
        wid = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        return
    w = storage.get_word_by_id(uid, wid)
    if not w:
        bot.answer_callback_query(call.id, "⚠️ Topilmadi.")
        return
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data=f"del_confirm_{wid}"),
        telebot.types.InlineKeyboardButton("❌ Bekor", callback_data="del_cancel")
    )
    try:
        bot.edit_message_text(
            f"⚠️ *{esc(w['uz'])}* → `{esc(w['eng'])}`\n\nO'chirmoqchimisiz?",
            uid, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "del_cancel")
def cb_del_cancel(call):
    try:
        bot.edit_message_text("❌ Bekor qilindi.", call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)



@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def cb_edit(call):
    uid = call.message.chat.id
    try:
        wid = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        return
    w = storage.get_word_by_id(uid, wid)
    if not w:
        bot.answer_callback_query(call.id, "⚠️ Topilmadi.")
        return
    set_user_state(uid, {"mode": "editing", "word_id": wid, "uz": w["uz"]})
    bot.answer_callback_query(call.id)
    safe_send(uid,
        f"✏️ *{esc(w['uz'])}* — tahrirlash\n\n"
        f"📌 Hozirgi tarjima: `{esc(w['eng'])}`\n\n"
        f"Yangi tarjimani yozing:",
        parse_mode="Markdown", reply_markup=back_menu())


@bot.message_handler(func=lambda m: isinstance(get_user_state(m.chat.id), dict)
                                    and get_user_state(m.chat.id).get("mode") == "editing")
def handle_edit(msg):
    uid = msg.chat.id
    st = pop_user_state(uid)
    if not st:
        return
    new_eng = msg.text.strip().lower()
    if not new_eng:
        safe_send(uid, "⚠️ Bo'sh qoldirish mumkin emas.", reply_markup=main_menu())
        return
    storage.update_word_eng(uid, st["word_id"], new_eng)
    safe_send(uid,
        f"✅ *{esc(st['uz'])}* yangilandi!\n\n📌 Yangi tarjima: `{esc(new_eng)}`",
        parse_mode="Markdown", reply_markup=main_menu())


@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid = msg.chat.id
    st = get_user_state(uid)
    if not (get_quiz_state(uid) or st == "adding" or st == "searching"
            or (isinstance(st, dict) and st.get("mode") == "editing")):
        safe_send(uid, "❓ Menyu tugmalaridan foydalaning.", reply_markup=main_menu())



# ── ESLATMA (REMINDER) SCHEDULER ──────────────────────────────────────────────
def send_reminders():
    """Takrorlash vaqti yetgan so'zlari bor foydalanuvchilarga eslatma yuboradi."""
    try:
        users_due = storage.get_users_with_due_words()
        for user_id, due_count in users_due:
            # DB-based cooldown tekshirish (1 soat ichida qayta xabar yo'q)
            if storage.is_recently_notified(user_id, cooldown_minutes=60):
                continue
            try:
                bot.send_message(user_id,
                    f"🔔 *Eslatma!*\n\n"
                    f"📚 Sizda *{due_count} ta* so'z takrorlashga tayyor!\n\n"
                    f"🧠 Hozir *🔁 Takrorlash* tugmasini bosing.\n\n"
                    f"💡 _Muntazam takrorlash — mustahkam xotira!_",
                    parse_mode="Markdown", reply_markup=main_menu())
                storage.mark_notified(user_id)
                log.info(f"📨 Eslatma yuborildi: user={user_id}, due={due_count}")
            except telebot.apihelper.ApiTelegramException as e:
                if e.error_code == 403:
                    storage.add_blocked_user(user_id)
                    log.info(f"🚫 User {user_id} botni bloklagan — bazaga yozildi.")
                else:
                    log.warning(f"⚠️ Eslatma xatosi (user={user_id}): {e}")
            except Exception as e:
                log.warning(f"⚠️ Eslatma xatosi (user={user_id}): {e}")
    except Exception as e:
        log.error(f"❌ Reminder job xatosi: {e}")


# ── SCHEDULER & GRACEFUL SHUTDOWN ─────────────────────────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(send_reminders, 'interval', minutes=5, id='reminder_job')
scheduler.start()
log.info("⏰ Eslatma scheduler ishga tushdi (har 5 daqiqada).")


def graceful_shutdown(signum, frame):
    """Bot va schedulerni to'g'ri to'xtatish."""
    log.info("🛑 Bot to'xtatilmoqda...")
    scheduler.shutdown(wait=False)
    bot.stop_polling()
    log.info("✅ Bot to'xtatildi.")
    sys.exit(0)


signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

log.info("🚀 BrainBridge bot ishga tushdi...")
bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=20)
