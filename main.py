import telebot, os, random, re, logging
from psycopg2 import pool as pg_pool
from datetime import datetime, timedelta
import backup

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

TOKEN        = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
if not TOKEN:        raise ValueError("BOT_TOKEN o'rnatilmagan!")
if not DATABASE_URL: raise ValueError("DATABASE_URL o'rnatilmagan!")

bot = telebot.TeleBot(TOKEN, threaded=True)

# ── DB ────────────────────────────────────────────────────────────────────────
_pool = pg_pool.ThreadedConnectionPool(2, 15, DATABASE_URL)

def db(q, p=None, fetch=None):
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(q, p or ())
            conn.commit()
            if fetch == "one": return cur.fetchone()
            if fetch == "all": return cur.fetchall()
    except Exception as e:
        conn.rollback(); log.error(f"DB xato: {e}"); raise
    finally:
        _pool.putconn(conn)

db("""CREATE TABLE IF NOT EXISTS words(
    id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
    uz TEXT NOT NULL, eng TEXT NOT NULL,
    box INTEGER DEFAULT 0,
    next_review TIMESTAMP DEFAULT NOW(),
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, uz))""")
db("CREATE INDEX IF NOT EXISTS idx_u ON words(user_id)")
db("CREATE INDEX IF NOT EXISTS idx_r ON words(user_id,box,next_review)")

# ── STARTUP ───────────────────────────────────────────────────────────────────
backup.restore_if_needed(DATABASE_URL)   # JSON → PG (agar PG bo'sh)
backup.start_scheduler(DATABASE_URL)     # har 6 soatda PG → JSON

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
BOX_DAYS = {0:0,1:1,2:3,3:7,4:14,5:30}
BOX_ICON = ["🆕","1️⃣","2️⃣","3️⃣","4️⃣","🏆"]
PAGE_SIZE = 8
user_state: dict = {}
quiz_state: dict = {}

def nxt(box): return datetime.now()+timedelta(days=BOX_DAYS.get(box,1))

# ── MENUS ─────────────────────────────────────────────────────────────────────
def main_menu():
    kb=telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ So'z qo'shish","📝 Test (Yangi)")
    kb.row("🔁 Takrorlash","📊 Statistika")
    kb.row("🔍 Qidirish","📋 So'zlarim")
    kb.row("❌ Tozalash"); return kb

def back_menu():
    kb=telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔙 Orqaga"); return kb

def box_menu(uid):
    kb=telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    now=datetime.now(); labels=[]
    for i in range(1,6):
        t=db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s",(uid,i),fetch="one")[0]
        d=db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s AND next_review<=%s",(uid,i,now),fetch="one")[0]
        labels.append(f"📦 Quti {i} ({'🔴'+str(d) if d>0 else '✅'}/{t})")
    kb.row(labels[0],labels[1]); kb.row(labels[2],labels[3]); kb.row(labels[4],"🔙 Orqaga"); return kb

# ── HELPERS ───────────────────────────────────────────────────────────────────
def bar(done,total,w=10):
    f=int((done/total)*w) if total else 0; return "█"*f+"░"*(w-f)

def send_words_btns(chat_id, words, header=""):
    if header: bot.send_message(chat_id,header,parse_mode="Markdown")
    for wid,uz,eng,box in words:
        kb=telebot.types.InlineKeyboardMarkup()
        kb.row(telebot.types.InlineKeyboardButton("✏️ Tahrirlash",callback_data=f"edit_{wid}"),
               telebot.types.InlineKeyboardButton("🗑 O'chirish", callback_data=f"del_{wid}"))
        bot.send_message(chat_id,f"{BOX_ICON[min(box,5)]} *{uz}* → {eng}",parse_mode="Markdown",reply_markup=kb)

def send_page(uid,chat_id,page=0):
    total=db("SELECT COUNT(*) FROM words WHERE user_id=%s",(uid,),fetch="one")[0]
    if total==0: bot.send_message(chat_id,"📭 So'zlar yo'q.",reply_markup=main_menu()); return
    pages=(total+PAGE_SIZE-1)//PAGE_SIZE
    words=db("SELECT id,uz,eng,box FROM words WHERE user_id=%s ORDER BY box DESC,uz LIMIT %s OFFSET %s",
             (uid,PAGE_SIZE,page*PAGE_SIZE),fetch="all")
    send_words_btns(chat_id,words,header=f"📋 *So'zlarim* — {page+1}/{pages} sahifa ({total} ta jami)")
    nav=telebot.types.InlineKeyboardMarkup(); btns=[]
    if page>0: btns.append(telebot.types.InlineKeyboardButton("⬅️ Oldingi",callback_data=f"page_{uid}_{page-1}"))
    if page+1<pages: btns.append(telebot.types.InlineKeyboardButton("Keyingi ➡️",callback_data=f"page_{uid}_{page+1}"))
    if btns: nav.row(*btns); bot.send_message(chat_id,"▶️ Navigatsiya:",reply_markup=nav)

# ── START ─────────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    user_state.pop(msg.chat.id,None); quiz_state.pop(msg.chat.id,None)
    bot.send_message(msg.chat.id,
        f"👋 Salom, *{msg.from_user.first_name or 'Do\'stim'}*!\n\n"
        "🧠 *MNEMONIKA WORD BOT*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "Ingliz so'zlarini *Leitner (qutilar) tizimi* orqali yodlang.\n\n"
        "📦 *Qutilar:*\n┣ Quti 1 → 1 kun\n┣ Quti 2 → 3 kun\n"
        "┣ Quti 3 → 7 kun\n┣ Quti 4 → 14 kun\n┗ Quti 5 → 30 kun\n\n"
        "✅ To'g'ri → keyingi qutiga | ❌ Xato → Quti 1",
        parse_mode="Markdown",reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text=="🔙 Orqaga")
def cmd_back(msg):
    quiz_state.pop(msg.chat.id,None); user_state.pop(msg.chat.id,None)
    bot.send_message(msg.chat.id,"🏠 Bosh menyu",reply_markup=main_menu())

# ── SO'Z QO'SHISH ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="➕ So'z qo'shish")
def cmd_add(msg):
    user_state[msg.chat.id]="adding"
    bot.send_message(msg.chat.id,
        "✏️ *So'z qo'shish*\n\nFormat: `o'zbek=ingliz`\n\n"
        "Ko'p so'z:\n```\nsalom=hello\nkitob=book\n```\n\n"
        "Sinonimlar: `ruxsat=allow,permit,let`",
        parse_mode="Markdown",reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id)=="adding")
def handle_add(msg):
    uid=msg.chat.id; added=updated=skipped=0
    for line in msg.text.strip().split("\n"):
        line=line.strip()
        if not line or "=" not in line: continue
        uz,eng=line.split("=",1); uz,eng=uz.strip().lower(),eng.strip().lower()
        if not uz or not eng: skipped+=1; continue
        try:
            row=db("SELECT id,eng FROM words WHERE user_id=%s AND uz=%s",(uid,uz),fetch="one")
            if row:
                wid,old=row; old_s=[x.strip() for x in old.split(",")]; new_s=[x.strip() for x in eng.split(",")]
                merged=old_s[:]; any_new=any(s not in merged or merged.append(s) for s in new_s if s not in merged)
                if any_new: db("UPDATE words SET eng=%s,box=0,next_review=NOW() WHERE id=%s",(",".join(merged),wid)); updated+=1
                else: skipped+=1
            else: db("INSERT INTO words(user_id,uz,eng,box,next_review)VALUES(%s,%s,%s,0,NOW())",(uid,uz,eng)); added+=1
        except: skipped+=1
    user_state.pop(uid,None)
    parts=[]
    if added:   parts.append(f"✅ *{added} ta* yangi so'z")
    if updated: parts.append(f"♻️ *{updated} ta* yangilandi")
    if skipped: parts.append(f"⏭ *{skipped} ta* o'tkazib yuborildi")
    bot.send_message(uid,"\n".join(parts) or "⚠️ Hech narsa saqlanmadi.",parse_mode="Markdown",reply_markup=main_menu())

# ── TEST YANGI ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="📝 Test (Yangi)")
def cmd_new_test(msg):
    uid=msg.chat.id
    words=db("SELECT uz,eng FROM words WHERE user_id=%s AND box=0 ORDER BY RANDOM()",(uid,),fetch="all")
    if not words: bot.send_message(uid,"📭 Yangi so'z yo'q.",reply_markup=main_menu()); return
    quiz_state[uid]={"words":list(words),"index":0,"answers":[],"used":[],"correct":0,"wrong":[],"mode":"new"}
    bot.send_message(uid,f"🎯 *Test boshlandi!* {len(words)} ta so'z",parse_mode="Markdown")
    ask_q(uid)

# ── TAKRORLASH ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="🔁 Takrorlash")
def cmd_rep(msg):
    uid=msg.chat.id; now=datetime.now()
    due=db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box>0 AND next_review<=%s",(uid,now),fetch="one")[0]
    if due==0:
        nxt_t=db("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box>0",(uid,),fetch="one")[0]
        if nxt_t:
            diff=nxt_t-now; h=int(diff.total_seconds()//3600); m=int((diff.total_seconds()%3600)//60)
            bot.send_message(uid,f"⏳ Tayyor so'z yo'q.\n🕐 Keyingi: *{h} soat {m} daqiqa* ichida",parse_mode="Markdown",reply_markup=main_menu())
        else: bot.send_message(uid,"📭 Takrorlanadigan so'z yo'q.\n\n💡 Avval *📝 Test (Yangi)* ni bosing!",parse_mode="Markdown",reply_markup=main_menu())
        return
    bot.send_message(uid,f"🔁 *Takrorlash*\n🔴 Tayyor: *{due} ta*\n\nQutini tanlang:",parse_mode="Markdown",reply_markup=box_menu(uid))

@bot.message_handler(func=lambda m: m.text and "📦 Quti" in m.text)
def cmd_box(msg):
    uid=msg.chat.id; match=re.search(r"Quti\s+(\d)",msg.text)
    if not match: return
    box=int(match.group(1)); now=datetime.now()
    words=db("SELECT uz,eng FROM words WHERE user_id=%s AND box=%s AND next_review<=%s ORDER BY RANDOM()",(uid,box,now),fetch="all")
    if not words:
        total=db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s",(uid,box),fetch="one")[0]
        if total>0:
            nxt_t=db("SELECT MIN(next_review) FROM words WHERE user_id=%s AND box=%s",(uid,box),fetch="one")[0]
            diff=nxt_t-now; h=int(diff.total_seconds()//3600); m=int((diff.total_seconds()%3600)//60)
            bot.send_message(uid,f"⏳ Hali vaqt kelmagan.\n🕐 Tayyor: *{h} soat {m} daqiqa*",parse_mode="Markdown",reply_markup=box_menu(uid))
        else: bot.send_message(uid,"📭 Bu qutida so'z yo'q.",reply_markup=box_menu(uid))
        return
    quiz_state[uid]={"words":list(words),"index":0,"answers":[],"used":[],"correct":0,"wrong":[],"mode":f"box_{box}","box":box}
    bot.send_message(uid,f"📦 *Quti {box} — Test*\nJami: *{len(words)} ta*",parse_mode="Markdown")
    ask_q(uid)

# ── SAVOL / JAVOB ─────────────────────────────────────────────────────────────
def ask_q(uid):
    quiz=quiz_state.get(uid)
    if not quiz: return
    if quiz["index"]>=len(quiz["words"]): finish(uid); return
    uz,eng=quiz["words"][quiz["index"]]
    answers=[x.strip() for x in eng.split(",")]
    quiz["answers"]=answers; quiz["used"]=[]
    total=len(quiz["words"]); cur_i=quiz["index"]+1
    text=f"*{cur_i}/{total}* `[{bar(quiz['index'],total)}]`\n\n🇺🇿 *{uz.upper()}*  →  🇬🇧 ?"
    if len(answers)>1: text+=f"\n\n💡 _{len(answers)} ta sinonim_"
    bot.send_message(uid,text,parse_mode="Markdown",reply_markup=back_menu())

@bot.message_handler(func=lambda m: m.chat.id in quiz_state)
def handle_ans(msg):
    uid=msg.chat.id; quiz=quiz_state.get(uid)
    if not quiz or msg.text=="🔙 Orqaga": return
    answer=msg.text.strip().lower(); uz,eng=quiz["words"][quiz["index"]]; answers=quiz["answers"]
    if answer in answers and answer not in quiz["used"]:
        quiz["used"].append(answer); rem=[a for a in answers if a not in quiz["used"]]
        if rem: bot.send_message(uid,f"✅ To'g'ri! Yana *{len(rem)} ta* sinonim.",parse_mode="Markdown"); return
        quiz["correct"]+=1
        row=db("SELECT box FROM words WHERE user_id=%s AND uz=%s",(uid,uz),fetch="one")
        if row:
            cb=row[0]; nb=min(cb+1,5)
            db("UPDATE words SET box=%s,next_review=%s WHERE user_id=%s AND uz=%s",(nb,nxt(nb),uid,uz))
            msg_text = "🏆 *Ajoyib!* Quti 5!" if nb==5 else f"✅ *To'g'ri!*  📦 Quti {cb} → {nb}"
            bot.send_message(uid, msg_text, parse_mode="Markdown")
    else:
        quiz["wrong"].append((uz,eng))
        db("UPDATE words SET box=1,next_review=%s WHERE user_id=%s AND uz=%s",(nxt(1),uid,uz))
        bot.send_message(uid,f"❌ *Xato!*\n✔️ To'g'ri: *{eng}*\n📦 → Quti 1",parse_mode="Markdown")
    quiz["index"]+=1; ask_q(uid)

def finish(uid):
    quiz=quiz_state.pop(uid,None)
    if not quiz: return
    total=quiz["correct"]+len(quiz["wrong"]); pct=0 if total==0 else int(quiz["correct"]/total*100)
    rating="🏆 Mukammal!" if pct==100 else "🌟 A'lo!" if pct>=80 else "👍 Yaxshi" if pct>=60 else "📚 O'rtacha" if pct>=40 else "💪 Davom!"
    bot.send_message(uid,
        f"🏁 *Test tugadi!*\n\n📊 `[{bar(quiz['correct'],total)}]` *{pct}%* — {rating}\n\n"
        f"✅ To'g'ri: *{quiz['correct']}*\n❌ Xato: *{len(quiz['wrong'])}*\n📝 Jami: *{total}*",
        parse_mode="Markdown",reply_markup=main_menu())
    if quiz["wrong"]:
        lines="\n".join(f"• *{u}* → {e}" for u,e in quiz["wrong"])
        bot.send_message(uid,f"❌ *Xato so'zlar:*\n\n{lines}",parse_mode="Markdown")
    else: bot.send_message(uid,"🎉 Xatolar yo'q — ajoyib natija!")

# ── STATISTIKA ────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="📊 Statistika")
def cmd_stats(msg):
    uid=msg.chat.id; now=datetime.now()
    total=db("SELECT COUNT(*) FROM words WHERE user_id=%s",(uid,),fetch="one")[0]
    new_w=db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=0",(uid,),fetch="one")[0]
    done =db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box=5",(uid,),fetch="one")[0]
    due  =db("SELECT COUNT(*) FROM words WHERE user_id=%s AND box>0 AND next_review<=%s",(uid,now),fetch="one")[0]
    blines="\n".join(f"  {'┣' if i<5 else '┗'} Quti {i}: *{db('SELECT COUNT(*) FROM words WHERE user_id=%s AND box=%s',(uid,i),fetch='one')[0]}*" for i in range(1,6))
    bot.send_message(uid,
        f"📊 *Statistika*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📚 Jami: *{total}*\n🆕 Yangi: *{new_w}*\n🔴 Bugun: *{due}*\n🏆 Tugatilgan: *{done}*\n\n"
        f"📦 *Qutilar:*\n{blines}",
        parse_mode="Markdown",reply_markup=main_menu())

# ── SO'ZLARIM ─────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="📋 So'zlarim")
def cmd_words(msg): send_page(msg.chat.id,msg.chat.id,page=0)

# ── QIDIRISH ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="🔍 Qidirish")
def cmd_search(msg):
    user_state[msg.chat.id]="searching"
    bot.send_message(msg.chat.id,"🔍 *Qidirish*\n\nSo'z kiriting:",parse_mode="Markdown",reply_markup=back_menu())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id)=="searching")
def handle_search(msg):
    uid=msg.chat.id; q=msg.text.strip().lower(); user_state.pop(uid,None)
    words=db("SELECT id,uz,eng,box FROM words WHERE user_id=%s AND(LOWER(uz) LIKE %s OR LOWER(eng) LIKE %s) ORDER BY uz LIMIT 20",
             (uid,f"%{q}%",f"%{q}%"),fetch="all")
    if not words: bot.send_message(uid,f"📭 *\"{q}\"* topilmadi.",parse_mode="Markdown",reply_markup=main_menu()); return
    send_words_btns(uid,words,header=f"🔍 *\"{q}\"* — {len(words)} ta natija:")
    bot.send_message(uid,"🏠 Bosh menyu:",reply_markup=main_menu())

# ── TOZALASH ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text=="❌ Tozalash")
def cmd_clear(msg):
    uid=msg.chat.id; total=db("SELECT COUNT(*) FROM words WHERE user_id=%s",(uid,),fetch="one")[0]
    if total==0: bot.send_message(uid,"📭 O'chiriladigan so'z yo'q.",reply_markup=main_menu()); return
    kb=telebot.types.InlineKeyboardMarkup()
    kb.row(telebot.types.InlineKeyboardButton("✅ Ha, o'chir",callback_data="clear_yes"),
           telebot.types.InlineKeyboardButton("❌ Yo'q",callback_data="clear_no"))
    bot.send_message(uid,f"⚠️ *Diqqat!* {total} ta so'z o'chiriladi. Rostan?",parse_mode="Markdown",reply_markup=kb)

# ── CALLBACKS ─────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data in ("clear_yes","clear_no"))
def cb_clear(call):
    uid=call.message.chat.id
    if call.data=="clear_yes":
        db("DELETE FROM words WHERE user_id=%s",(uid,))
        bot.edit_message_text("🗑 Barcha so'zlar o'chirildi.",call.message.chat.id,call.message.message_id)
        bot.send_message(uid,"🏠 Bosh menyu",reply_markup=main_menu())
    else: bot.edit_message_text("❌ Bekor qilindi.",call.message.chat.id,call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("page_"))
def cb_page(call):
    _,uid_s,pg_s=call.data.split("_",2); bot.answer_callback_query(call.id)
    send_page(int(uid_s),call.message.chat.id,page=int(pg_s))

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_confirm_"))
def cb_del_confirm(call):
    wid=int(call.data.split("_")[2]); uid=call.message.chat.id
    row=db("SELECT uz FROM words WHERE id=%s AND user_id=%s",(wid,uid),fetch="one")
    if not row: bot.answer_callback_query(call.id,"Topilmadi."); return
    db("DELETE FROM words WHERE id=%s AND user_id=%s",(wid,uid))
    bot.edit_message_text(f"🗑 *{row[0]}* o'chirildi.",call.message.chat.id,call.message.message_id,parse_mode="Markdown")
    bot.answer_callback_query(call.id,"O'chirildi!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_") and not c.data.startswith("del_confirm_"))
def cb_del(call):
    wid=int(call.data.split("_")[1]); uid=call.message.chat.id
    row=db("SELECT uz,eng FROM words WHERE id=%s AND user_id=%s",(wid,uid),fetch="one")
    if not row: bot.answer_callback_query(call.id,"Topilmadi."); return
    uz,eng=row; kb=telebot.types.InlineKeyboardMarkup()
    kb.row(telebot.types.InlineKeyboardButton("✅ Ha, o'chir",callback_data=f"del_confirm_{wid}"),
           telebot.types.InlineKeyboardButton("❌ Bekor",callback_data="del_cancel"))
    bot.edit_message_text(f"⚠️ *{uz}* → {eng}\n\nRostan o'chirmoqchimisiz?",
                          call.message.chat.id,call.message.message_id,parse_mode="Markdown",reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data=="del_cancel")
def cb_del_cancel(call):
    bot.edit_message_text("❌ Bekor qilindi.",call.message.chat.id,call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def cb_edit(call):
    wid=int(call.data.split("_")[1]); uid=call.message.chat.id
    row=db("SELECT uz,eng FROM words WHERE id=%s AND user_id=%s",(wid,uid),fetch="one")
    if not row: bot.answer_callback_query(call.id,"Topilmadi."); return
    uz,eng=row; user_state[uid]={"mode":"editing","word_id":wid,"uz":uz}
    bot.answer_callback_query(call.id)
    bot.send_message(uid,f"✏️ *{uz}* tahrirlash\nHozirgi: `{eng}`\n\nYangi tarjima kiriting:",
                     parse_mode="Markdown",reply_markup=back_menu())

@bot.message_handler(func=lambda m: isinstance(user_state.get(m.chat.id),dict)
                                    and user_state[m.chat.id].get("mode")=="editing")
def handle_edit(msg):
    uid=msg.chat.id; st=user_state.pop(uid,{}); new_eng=msg.text.strip().lower()
    if not new_eng: bot.send_message(uid,"⚠️ Bo'sh qoldirish mumkin emas.",reply_markup=main_menu()); return
    db("UPDATE words SET eng=%s WHERE id=%s AND user_id=%s",(new_eng,st["word_id"],uid))
    bot.send_message(uid,f"✅ *{st['uz']}* yangilandi:\n`{new_eng}`",parse_mode="Markdown",reply_markup=main_menu())

@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid=msg.chat.id; st=user_state.get(uid)
    if not(uid in quiz_state or st=="adding" or st=="searching"
           or(isinstance(st,dict) and st.get("mode")=="editing")):
        bot.send_message(uid,"❓ Menyu tugmalaridan foydalaning.",reply_markup=main_menu())

log.info("BrainBridge bot ishga tushdi...")
bot.infinity_polling(skip_pending=True,timeout=30,long_polling_timeout=20)
