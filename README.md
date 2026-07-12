# BrainBridge — Telegram Bot for Vocabulary Learning (Leitner System)

**BrainBridge** - bu Leitner tizimi (spaced repetition) asosida ingliz tili so'zlarini samarali yodlashga yordam beruvchi Telegram bot. Ushbu loyiha Python dasturlash tilida `pyTelegramBotAPI` va PostgreSQL ma'lumotlar bazasi yordamida yozilgan.

---

## 📌 Xususiyatlari / Features

- **Leitner Tizimi (Spaced Repetition):**
  So'zlar 5 ta qutiga (Box) bo'linadi va har bir quti uchun maxsus takrorlash oralig'i o'rnatilgan:
  - `🆕 Yangi` (Box 0) → Darhol test qilinadi.
  - `1️⃣ Quti 1` → 1 kundan keyin takrorlash.
  - `2️⃣ Quti 2` → 3 kundan keyin takrorlash.
  - `3️⃣ Quti 3` → 7 kundan keyin takrorlash.
  - `4️⃣ Quti 4` → 14 kundan keyin takrorlash.
  - `🏆 Quti 5` → 30 kundan keyin takrorlash.

  *Muvaffaqiyatli (to'g'ri) javob berilganda so'z yuqoriroq qutiga o'tadi (masalan, Quti 1 → Quti 2).*
  *Xato javob berilganda so'z har doim Quti 1 ga qaytariladi.*

- **Ko'p tilli / Sinonimlar qo'llab-quvvatlanishi:**
  Bitta so'z uchun bir nechta sinonimlarni vergul bilan ajratib kiritish mumkin (masalan: `allow, permit, let - ruxsat`).
- **Yozma va Variantli Testlar:**
  - *Yangi so'zlar testi* va *Qutilardagi takrorlash testlari* ko'p variantli (multiple choice) shaklda o'tadi.
  - *Barcha so'zlar testi* esa to'liq yozma shaklda o'tadi (foydalanuvchi barcha sinonimlarni to'g'ri kiritishi kerak).
- **Avtomatik Bildirishnomalar (Notifications):**
  Orqa fonda ishlovchi scheduler (`notifier.py`) foydalanuvchilarning takrorlash muddati kelgan so'zlari bor-yo'qligini tekshiradi va ularga eslatma yuboradi (spam bo'lmasligi uchun 12 soatlik cooldown mavjud).
- **So'zlar va Statistika:**
  Foydalanuvchi o'z so'zlarini qidirishi, tahrirlashi, o'chirishi yoki to'liq tozalashi mumkin. Batafsil statistika menyusi progressni ko'rsatib turadi.

---

## 📁 Loyiha Tuzilishi / Project Structure

- `main.py` — Botning asosiy kirish nuqtasi, menyular, xabarlarni qayta ishlash, test rejimlarining boshqaruvi va buyruqlar handleri.
- `storage.py` — PostgreSQL ulanishlar puli (Connection Pool) va ma'lumotlar bazasi (CRUD, filtrlar, statistikalar) bilan ishlash moduli.
- `notifier.py` — Takrorlash vaqti kelgan foydalanuvchilarga fonda avtomatik eslatma (notification) yuboruvchi scheduler thread moduli.
- `requirements.txt` — Loyiha ishlashi uchun zarur bo'lgan Python kutubxonalari ro'yxati.

---

## 💾 Ma'lumotlar Bazasi Sxemasi / Database Schema

### 1. `users` jadvali
| Ustun | Turi | Tavsif |
| --- | --- | --- |
| `user_id` | `BIGINT` (Primary Key) | Telegram foydalanuvchi IDsi |
| `first_name` | `TEXT` | Foydalanuvchining ismi |
| `notify` | `BOOLEAN` (Default: `TRUE`) | Bildirishnomalar yoqilganligi |
| `last_notified` | `TIMESTAMP` | Oxirgi marta bildirishnoma yuborilgan vaqt |
| `created_at` | `TIMESTAMP` (Default: `NOW()`) | Yaratilgan vaqt |

### 2. `words` jadvali
| Ustun | Turi | Tavsif |
| --- | --- | --- |
| `id` | `SERIAL` (Primary Key) | So'z IDsi |
| `user_id` | `BIGINT` | Foydalanuvchi IDsi (FK) |
| `uz` | `TEXT` | O'zbekcha tarjimasi |
| `eng` | `TEXT` | Inglizcha so'z(lar) (sinonimlar vergul bilan saqlanadi) |
| `box` | `INTEGER` (Default: `0`) | Leitner tizimi bo'yicha joriy qutisi |
| `next_review` | `TIMESTAMP` | Keyingi takrorlash vaqti |
| `created_at` | `TIMESTAMP` (Default: `NOW()`) | Qo'shilgan vaqt |

---

## 🚀 Ishga Tushirish / How to Run

1. **Kutubxonalarni o'rnating:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Muhit o'zgaruvchilarini (.env fayli) sozlang:**
   Loyiha ildiz papkasida `.env` faylini yarating va quyidagi o'zgaruvchilarni kiriting:
   ```env
   BOT_TOKEN=your_telegram_bot_token
   DATABASE_URL=postgresql://user:password@host:port/database_name
   ```

3. **Botni ishga tushiring:**
   ```bash
   python main.py
   ```

---

*BrainBridge botingiz bilan so'z yodlashda muvaffaqiyatlar tilaymiz!*
