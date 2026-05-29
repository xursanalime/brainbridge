"""
notifier.py — muddati kelgan so'zlar uchun avtomatik bildirishnoma moduli.

Fon (background) thread sifatida ishlaydi: belgilangan interval bilan bazani
tekshiradi va takrorlash vaqti kelgan foydalanuvchilarga eslatma yuboradi.

Spamning oldini olish uchun har bir foydalanuvchiga `COOLDOWN_HOURS` ichida
faqat bitta bildirishnoma yuboriladi (storage.users_to_notify shuni ta'minlaydi).
"""
import threading
import time
import logging

import storage

log = logging.getLogger(__name__)

# Sozlamalar
CHECK_INTERVAL_SEC = 30 * 60   # har 30 daqiqada bazani tekshiradi
COOLDOWN_HOURS = 12            # bitta foydalanuvchiga 12 soatda 1 marta eslatma


def _notify_once(bot):
    """Bir marta tekshirish: muddati kelganlarga bildirishnoma yuboradi."""
    try:
        targets = storage.users_to_notify(COOLDOWN_HOURS)
    except Exception as e:
        log.error(f"❌ Bildirishnoma uchun foydalanuvchilarni olishda xato: {e}")
        return

    if not targets:
        return

    log.info(f"🔔 {len(targets)} ta foydalanuvchiga bildirishnoma yuborilmoqda...")
    for uid, first_name, due_count in targets:
        name = first_name or "Doʻstim"
        text = (
            f"🔔 *Eslatma, {name}!*\n\n"
            f"📚 Takrorlash vaqti keldi: *{due_count} ta* so'z tayyor.\n\n"
            f"💡 *🔁 Takrorlash* tugmasini bosib mashq qiling!"
        )
        try:
            bot.send_message(uid, text, parse_mode="Markdown")
            storage.mark_notified(uid)
        except Exception as e:
            # Foydalanuvchi botni bloklagan bo'lishi mumkin — eslatmani o'chiramiz
            msg = str(e).lower()
            if "blocked" in msg or "deactivated" in msg or "chat not found" in msg:
                log.warning(f"⚠️ {uid}: bot bloklangan/topilmadi — bildirishnoma o'chirildi.")
                try:
                    storage.set_notify(uid, False)
                except Exception:
                    pass
            else:
                log.error(f"❌ {uid} ga bildirishnoma yuborishda xato: {e}")


def start_scheduler(bot):
    """Fon thread: har CHECK_INTERVAL_SEC da bir marta tekshiradi."""
    def _run():
        log.info(f"🕐 Bildirishnoma scheduler ishga tushdi "
                 f"(har {CHECK_INTERVAL_SEC // 60} daqiqada, cooldown {COOLDOWN_HOURS} soat).")
        # Startda darrov tekshirmaymiz — bot to'liq ishga tushishini kutamiz
        while True:
            time.sleep(CHECK_INTERVAL_SEC)
            _notify_once(bot)

    t = threading.Thread(target=_run, daemon=True, name="NotifyScheduler")
    t.start()
    log.info("🟢 NotifyScheduler thread ishga tushdi.")
