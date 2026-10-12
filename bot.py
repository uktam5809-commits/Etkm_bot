import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

# ----------------- ASOSIY SOZLAMALAR -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8882153518:AAHJUWfsAYgPwdaSIDI1FhhxCw1xRcSh020")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "6439380297"))
DB_PATH = "bot_data.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ----------------- FSM HOLATLARI -----------------
class UserState(StatesGroup):
    waiting_for_post = State()
    waiting_for_search_username = State()

class AdminState(StatesGroup):
    waiting_for_user_query = State()
    waiting_for_new_score = State()
    waiting_for_new_channel = State()
    waiting_for_log_chat = State()
    waiting_for_new_admin = State()
    waiting_for_broadcast = State()
    waiting_for_post_comment = State()
    waiting_for_shop_item = State()

# ----------------- MA'LUMOTLAR BAZASI -----------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                total_score INTEGER DEFAULT 0,
                posts_count INTEGER DEFAULT 0,
                channel_posts_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_id INTEGER,
                score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                comment TEXT,
                in_channel INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                price INTEGER
            )
        """)
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))

        for col, query in [
            ("username", "ALTER TABLE users ADD COLUMN username TEXT"),
            ("channel_posts_count", "ALTER TABLE users ADD COLUMN channel_posts_count INTEGER DEFAULT 0"),
            ("comment", "ALTER TABLE posts ADD COLUMN comment TEXT"),
            ("in_channel", "ALTER TABLE posts ADD COLUMN in_channel INTEGER DEFAULT 0")
        ]:
            try:
                await db.execute(query)
            except Exception:
                pass

        # NULL qiymatlarni 0 ga to'g'irlash (reyting va hisob-kitoblar buzilmasligi uchun)
        await db.execute("UPDATE users SET total_score = 0 WHERE total_score IS NULL")
        await db.execute("UPDATE users SET posts_count = 0 WHERE posts_count IS NULL")
        await db.execute("UPDATE users SET channel_posts_count = 0 WHERE channel_posts_count IS NULL")

        await db.commit()

# ----------------- YORDAMCHI FUNKSIYALAR -----------------
async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row and row[0] else ""

async def set_setting(key: str, val: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, val)
        )
        await db.commit()

async def is_checker_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        return (await cursor.fetchone()) is not None

async def get_all_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM admins")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

async def check_subscription(user_id: int) -> bool:
    channel = await get_setting("channel")
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except Exception as e:
        logging.warning(f"Obunada xatolik: {e}")
        return True

async def get_sub_keyboard():
    channel = await get_setting("channel")
    builder = InlineKeyboardBuilder()
    channel_clean = channel.replace("@", "")
    builder.button(text="📢 Kanalga a'zo bo'lish", url=f"https://t.me/{channel_clean}")
    builder.button(text="✅ Obunani tekshirish", callback_data="check_sub")
    builder.adjust(1)
    return builder.as_markup()

# ----------------- ASOSIY MENYU -----------------
def get_main_menu(user_id: int):
    kb = [
        [KeyboardButton(text="✍️ Post yuborish")],
        [KeyboardButton(text="📊 Profilim"), KeyboardButton(text="🏆 Top 10 Reyting")],
        [KeyboardButton(text="🔍 Foydalanuvchi qidirish"), KeyboardButton(text="🛍 Yulduzlar do‘koni")]
    ]
    if user_id == SUPER_ADMIN_ID:
        kb.append([KeyboardButton(text="⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_panel_inline():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Barcha ishtirokchilar", callback_data="admin_all_users")
    builder.button(text="📢 Majburiy kanalni sozlash", callback_data="admin_set_channel")
    builder.button(text="📑 Arxiv chatini sozlash", callback_data="admin_set_log_chat")
    builder.button(text="🛍 Do‘konni boshqarish", callback_data="admin_manage_shop")
    builder.button(text="➕ Tekshiruvchi qo'shish", callback_data="admin_add_checker")
    builder.button(text="➖ Tekshiruvchini o'chirish", callback_data="admin_remove_checker")
    builder.button(text="✏️ Foydalanuvchi ballini tahrirlash", callback_data="admin_edit_score")
    builder.button(text="📨 Reklama / Xabar tarqatish", callback_data="admin_broadcast")
    builder.button(text="📈 Tizim statistikasi", callback_data="admin_sys_stats")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_post_keyboard(post_id: int, in_channel: int = 0):
    builder = InlineKeyboardBuilder()
    for score in range(1, 6):
        builder.button(text=f"{score} ⭐", callback_data=f"rate:{post_id}:{score}")
    status_ch = "✅ Kanalga chiqariladi" if in_channel == 1 else "📢 Kanalga chiqarish"
    builder.button(text=status_ch, callback_data=f"toggle_channel:{post_id}")
    builder.button(text="❌ Rad etish", callback_data=f"rate:{post_id}:0")
    builder.adjust(5, 1, 1)
    return builder.as_markup()

# ----------------- ASOSIY BUYRUQLAR -----------------
@dp.callback_query(F.data == "check_sub")
async def verify_sub(callback: types.CallbackQuery):
    is_sub = await check_subscription(callback.from_user.id)
    if is_sub:
        await callback.message.delete()
        await callback.message.answer(
            "🎉 <b>Obuna tasdiqlandi!</b>\nBosh menyudan foydalanishingiz mumkin:",
            reply_markup=get_main_menu(callback.from_user.id),
            parse_mode="HTML"
        )
    else:
        await callback.answer("⚠️ Siz hali kanalga a'zo bo'lmadingiz!", show_alert=True)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, full_name, username, total_score, posts_count, channel_posts_count) "
            "VALUES (?, ?, ?, 0, 0, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name, username = excluded.username",
            (user.id, user.full_name, user.username)
        )
        await db.commit()

    if not await check_subscription(user.id):
        await message.answer(
            f"Assalomu alaykum, hurmatli <b>{user.first_name}</b>! 👋\n\n"
            "Botdan to'liq foydalanish uchun rasmiy kanalimizga a'zo bo'ling:",
            reply_markup=await get_sub_keyboard(),
            parse_mode="HTML"
        )
        return

    await message.answer(
        f"Assalomu alaykum, hurmatli <b>{user.first_name}</b>! 👋\n\n"
        "📌 Quyidagi bo'limlardan birini tanlang:",
        reply_markup=get_main_menu(user.id),
        parse_mode="HTML"
    )

# ----------------- FOYDALANUVCHI BO'LIMLARI -----------------
@dp.message(F.text == "✍️ Post yuborish")
async def ask_post(message: types.Message, state: FSMContext):
    if not await check_subscription(message.from_user.id):
        await message.answer("⚠️ Avval kanalga obuna bo'ling:", reply_markup=await get_sub_keyboard())
        return

    await state.set_state(UserState.waiting_for_post)
    await message.answer(
        "✍️ <b>Yangilik, maqola yoki postingizni yuboring:</b>\n\n"
        "📷 Rasm, 🎥 video yoki 📝 matn ko'rinishida jo'natishingiz mumkin.",
        parse_mode="HTML"
    )

@dp.message(StateFilter(UserState.waiting_for_post))
async def handle_user_post(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO posts (user_id, message_id) VALUES (?, ?)",
            (user.id, message.message_id)
        )
        post_id = cursor.lastrowid
        await db.commit()

    await message.answer("✅ <b>Postingiz tekshiruvga yuborildi!</b>\nTez orada baholanadi.", reply_markup=get_main_menu(user.id), parse_mode="HTML")

    log_chat = await get_setting("log_chat")
    admins = await get_all_admins()

    forward_targets = [int(log_chat)] if log_chat else admins
    for chat_id in forward_targets:
        try:
            await message.forward(chat_id=chat_id)
            await bot.send_message(
                chat_id=chat_id,
                text=f"📥 <b>Yangi post #{post_id}</b>\nKimdan: {user.full_name} (@{user.username})\nID: <code>{user.id}</code>",
                reply_markup=get_admin_post_keyboard(post_id, in_channel=0),
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Post forward qilishda xatolik ({chat_id}): {e}")

@dp.message(F.text == "📊 Profilim")
async def show_profile(message: types.Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(total_score, 0), COALESCE(posts_count, 0), COALESCE(channel_posts_count, 0) "
            "FROM users WHERE user_id = ?",
            (message.from_user.id,)
        )
        data = await cursor.fetchone()

    total_score = data[0] if data else 0
    posts_count = data[1] if data else 0
    ch_posts_count = data[2] if data else 0

    await message.answer(
        f"👤 <b>Sizning profilingiz:</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"⭐ Jami yulduzlar: <b>{total_score} ball</b>\n"
        f"📝 Baholangan postlar: <b>{posts_count} ta</b>\n"
        f"📢 Kanalga chiqqan postlar: <b>{ch_posts_count} ta</b>",
        parse_mode="HTML"
    )

# ----------------- TO'G'IRLANGAN TOP 10 REYTING -----------------
@dp.message(F.text == "🏆 Top 10 Reyting")
async def show_leaderboard(message: types.Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        # COALESCE orqali NULL qiymatlarni 0 ga aylantiramiz va to'g'ri saralaymiz
        cursor = await db.execute("""
            SELECT full_name, username, COALESCE(total_score, 0), COALESCE(channel_posts_count, 0)
            FROM users
            ORDER BY COALESCE(total_score, 0) DESC, COALESCE(channel_posts_count, 0) DESC
            LIMIT 10
        """)
        top_users = await cursor.fetchall()

    # Faqat 0 dan katta balli yoki kanal posti borlarni filtrlaymiz
    active_top = [u for u in top_users if u[2] > 0 or u[3] > 0]

    if not active_top:
        await message.answer("ℹ️ Hozircha reytingda ball to'plagan ishtirokchilar mavjud emas.")
        return

    text = "🏆 <b>TOP-10 ishtirokchilar reytingi:</b>\n\n"
    for idx, (name, uname, score, ch_count) in enumerate(active_top, start=1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"<b>{idx}.</b>"
        u_tag = f"(@{uname})" if uname else ""
        text += f"{medal} <b>{name}</b> {u_tag} — ⭐ <b>{score} ball</b> | 📢 Kanalda: <b>{ch_count} ta</b>\n"

    await message.answer(text, parse_mode="HTML")

# ----------------- FOYDALANUVCHILARNI QIDIRISH -----------------
@dp.message(F.text == "🔍 Foydalanuvchi qidirish")
async def ask_search_user(message: types.Message, state: FSMContext):
    await state.set_state(UserState.waiting_for_search_username)
    await message.answer(
        "🔍 Qidirmoqchi bo'lgan foydalanuvchining <b>@username</b> ini yuboring:\n"
        "<i>(Bekor qilish uchun '0' deb yozing)</i>",
        parse_mode="HTML"
    )

@dp.message(StateFilter(UserState.waiting_for_search_username), F.text)
async def process_search_user(message: types.Message, state: FSMContext):
    query = message.text.strip().replace("@", "")
    if query == "0":
        await state.clear()
        await message.answer("Qidiruv bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT full_name, username, COALESCE(total_score, 0), COALESCE(posts_count, 0), COALESCE(channel_posts_count, 0) "
            "FROM users WHERE LOWER(username) = LOWER(?)",
            (query,)
        )
        user_row = await cursor.fetchone()

    await state.clear()
    if not user_row:
        await message.answer(
            f"❌ <b>@{query}</b> foydalanuvchisi topilmadi.",
            reply_markup=get_main_menu(message.from_user.id),
            parse_mode="HTML"
        )
        return

    name, uname, score, p_cnt, ch_cnt = user_row
    await message.answer(
        f"🔍 <b>Foydalanuvchi ma'lumotlari:</b>\n\n"
        f"👤 Ism: <b>{name}</b> (@{uname})\n"
        f"⭐ To'plagan yulduzlari: <b>{score} ball</b>\n"
        f"📝 Baholangan postlari: <b>{p_cnt} ta</b>\n"
        f"📢 Kanalga chiqqan postlari: <b>{ch_cnt} ta</b>",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="HTML"
    )

# ----------------- YULDUZLAR DO'KONI (TEXNIK ISHLAR) -----------------
@dp.message(F.text == "🛍 Yulduzlar do‘koni")
async def show_shop(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛠 <b>Yulduzlar do‘koni:</b>\n\n"
        "Hozirda ushbu bo‘limda <b>texnik profilaktika va sozlash ishlari</b> olib borilmoqda. ⏳\n\n"
        "Tez orada yangi imkoniyatlar bilan ishga tushiriladi. Sabringiz uchun rahmat! ✨",
        parse_mode="HTML"
    )

# ----------------- ADMIN PANEL -----------------
@dp.message(F.text == "⚙️ Admin Panel")
async def open_admin_panel(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    await state.clear()
    cur_ch = await get_setting("channel")
    cur_log = await get_setting("log_chat")
    shop_st = "Sozlanmoqda 🚧"

    await message.answer(
        f"🛠 <b>Boshqaruv Paneli</b>\n\n"
        f"📢 Kanal: <b>{cur_ch if cur_ch else 'Oʻchiq'}</b>\n"
        f"📑 Arxiv: <b>{cur_log if cur_log else 'Ulanmagan'}</b>\n"
        f"🛍 Do‘kon: <b>{shop_st}</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=get_admin_panel_inline(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_all_users")
async def list_all_participants(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT full_name, username, COALESCE(total_score, 0), COALESCE(channel_posts_count, 0)
            FROM users
            ORDER BY COALESCE(total_score, 0) DESC
        """)
        users = await cursor.fetchall()

    if not users:
        await callback.answer("Foydalanuvchilar mavjud emas!", show_alert=True)
        return

    text = "👥 <b>Barcha ishtirokchilar ro'yxati:</b>\n\n"
    for idx, (name, uname, score, ch_cnt) in enumerate(users, start=1):
        u_tag = f"(@{uname})" if uname else "(username yo'q)"
        line = f"{idx}. <b>{name}</b> {u_tag} — ⭐ <b>{score} ball</b> | 📢 <b>{ch_cnt} ta</b> kanal posti\n"
        if len(text + line) > 4000:
            await callback.message.answer(text, parse_mode="HTML")
            text = ""
        text += line

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Ortga", callback_data="admin_back_to_panel")
    await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_manage_shop")
async def manage_shop_menu(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Ortga", callback_data="admin_back_to_panel")
    await callback.message.edit_text(
        "🛍 <b>Yulduzlar do‘koni:</b>\nHozirda ushbu bo‘limda texnik ishlar olib borilmoqda.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_back_to_panel")
async def back_to_admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    cur_ch = await get_setting("channel")
    cur_log = await get_setting("log_chat")
    shop_st = "Sozlanmoqda 🚧"

    await callback.message.edit_text(
        f"🛠 <b>Boshqaruv Paneli</b>\n\n"
        f"📢 Kanal: <b>{cur_ch if cur_ch else 'Oʻchiq'}</b>\n"
        f"📑 Arxiv: <b>{cur_log if cur_log else 'Ulanmagan'}</b>\n"
        f"🛍 Do‘kon: <b>{shop_st}</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=get_admin_panel_inline(),
        parse_mode="HTML"
    )
    await callback.answer()

# ----------------- KANAL VA ARXIV SOZLASH -----------------
@dp.callback_query(F.data == "admin_set_channel")
async def ask_channel(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_new_channel)
    await callback.message.answer("📢 Kanalning @username yoki ID sini yuboring (O'chirish uchun 0 deb yozing):")
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_new_channel), F.text)
async def save_channel(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    ch = message.text.strip()
    await set_setting("channel", "" if ch == "0" else ch)
    await state.clear()
    await message.answer("✅ Kanal muvaffaqiyatli yangilandi!", reply_markup=get_main_menu(message.from_user.id))

@dp.callback_query(F.data == "admin_set_log_chat")
async def ask_log_chat(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_log_chat)
    await callback.message.answer("📑 Arxiv chat (guruh/kanal) ID sini yuboring (O'chirish uchun 0 deb yozing):")
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_log_chat), F.text)
async def save_log_chat(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    lg = message.text.strip()
    await set_setting("log_chat", "" if lg == "0" else lg)
    await state.clear()
    await message.answer("✅ Arxiv guruhi yangilandi!", reply_markup=get_main_menu(message.from_user.id))

# ----------------- TEKSHIRUVCHILARNI BOSHQARISH -----------------
@dp.callback_query(F.data == "admin_add_checker")
async def start_add_checker(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_new_admin)
    await callback.message.answer("➕ Yangi tekshiruvchining Telegram ID sini yuboring (Bekor qilish uchun 0):")
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_new_admin), F.text)
async def save_checker(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    val = message.text.strip()
    if val == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    if not val.isdigit():
        await message.answer("ID faqat sonlardan iborat bo'lishi kerak!")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(val),))
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Tekshiruvchi (ID: {val}) qo'shildi!", reply_markup=get_main_menu(message.from_user.id))

@dp.callback_query(F.data == "admin_remove_checker")
async def list_remove_checker(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM admins WHERE user_id != ?", (SUPER_ADMIN_ID,))
        admins = await cur.fetchall()

    if not admins:
        await callback.answer("Tekshiruvchilar yo'q!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for a_id in admins:
        builder.button(text=f"❌ ID: {a_id[0]}", callback_data=f"del_admin:{a_id[0]}")
    builder.button(text="⬅️ Ortga", callback_data="admin_back_to_panel")
    builder.adjust(1)
    await callback.message.edit_text("O'chirmoqchi bo'lgan tekshiruvchingizni tanlang:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("del_admin:"))
async def process_del_admin(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    del_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (del_id,))
        await db.commit()
    await callback.answer("Tekshiruvchi o'chirildi!")
    await list_remove_checker(callback)

# ----------------- BALL TAHRIRLASH -----------------
@dp.callback_query(F.data == "admin_edit_score")
async def start_edit_score(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_user_query)
    await callback.message.answer("✏️ Foydalanuvchining ID raqamini kiriting (Bekor qilish uchun 0):")
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_user_query), F.text)
async def ask_new_score(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    val = message.text.strip()
    if val == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    if not val.isdigit():
        await message.answer("ID faqat son bo'lishi kerak!")
        return

    await state.update_data(target_user=int(val))
    await state.set_state(AdminState.waiting_for_new_score)
    await message.answer("Yangi umumiy ball miqdorini kiriting:")

@dp.message(StateFilter(AdminState.waiting_for_new_score), F.text)
async def save_new_score(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    val = message.text.strip()
    if not val.isdigit():
        await message.answer("Ball faqat son bo'lishi kerak!")
        return
    data = await state.get_data()
    t_id = data.get("target_user")
    new_s = int(val)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET total_score = ? WHERE user_id = ?", (new_s, t_id))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Foydalanuvchi ({t_id}) bali {new_s} ga o'zgartirildi!", reply_markup=get_main_menu(message.from_user.id))

# ----------------- XABAR TARQATISH -----------------
@dp.callback_query(F.data == "admin_broadcast")
async def ask_broadcast_msg(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_broadcast)
    await callback.message.answer("📨 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing (Bekor qilish uchun 0):")
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_broadcast))
async def send_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    if message.text == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("SELECT user_id FROM users")).fetchall()

    count = 0
    for r in rows:
        try:
            await bot.copy_message(chat_id=r[0], from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga yuborildi!", reply_markup=get_main_menu(message.from_user.id))

# ----------------- POSTLARNI BAHOLASH VA TEKSHIRISH -----------------
@dp.callback_query(F.data.startswith("toggle_channel:"))
async def toggle_channel_btn(callback: types.CallbackQuery):
    if not await is_checker_admin(callback.from_user.id):
        await callback.answer("Siz tekshiruvchi emassiz!", show_alert=True)
        return
    post_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT in_channel FROM posts WHERE id = ?", (post_id,))
        row = await cur.fetchone()
        new_val = 0 if row and row[0] == 1 else 1
        await db.execute("UPDATE posts SET in_channel = ? WHERE id = ?", (new_val, post_id))
        await db.commit()
    
    await callback.message.edit_reply_markup(reply_markup=get_admin_post_keyboard(post_id, in_channel=new_val))
    holat_matni = "Kanalga chiqarilishi belgilandi ✅" if new_val == 1 else "Kanalga chiqarish bekor qilindi ❌"
    await callback.answer(holat_matni)

@dp.callback_query(F.data.startswith("rate:"))
async def start_rate_post(callback: types.CallbackQuery, state: FSMContext):
    if not await is_checker_admin(callback.from_user.id):
        await callback.answer("Siz tekshiruvchi emassiz!", show_alert=True)
        return

    _, post_id, score_str = callback.data.split(":")
    post_id = int(post_id)
    score = int(score_str)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, in_channel FROM posts WHERE id = ?", (post_id,))
        post = await cur.fetchone()
        if not post:
            await callback.answer("Post topilmadi!", show_alert=True)
            return
        u_id, in_ch = post

    await state.update_data(
        eval_post_id=post_id,
        eval_user_id=u_id,
        eval_score=score,
        eval_in_channel=in_ch,
        eval_admin_name=callback.from_user.full_name
    )
    await state.set_state(AdminState.waiting_for_post_comment)

    baholash_nomi = f"{score} ⭐" if score > 0 else "Rad etish ❌"
    kanal_matni = " (Kanalga chiqariladi)" if in_ch == 1 else ""

    await callback.message.edit_text(
        f"📝 <b>Post #{post_id} uchun qaror:</b> {baholash_nomi}{kanal_matni}\n\n"
        "💬 <b>Foydalanuvchiga izoh yozasizmi?</b>\n"
        "Izohingizni yozing (yoki izohsiz yuborish uchun <b>0</b> deb yozing):",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_post_comment), F.text)
async def finish_evaluation_with_comment(message: types.Message, state: FSMContext):
    if not await is_checker_admin(message.from_user.id):
        return

    data = await state.get_data()
    post_id = data.get("eval_post_id")
    u_id = data.get("eval_user_id")
    score = data.get("eval_score")
    in_ch = data.get("eval_in_channel")

    comment_text = message.text.strip()
    has_comment = comment_text != "0"

    async with aiosqlite.connect(DB_PATH) as db:
        if score > 0:
            ch_add = 1 if in_ch == 1 else 0
            await db.execute(
                "UPDATE users SET total_score = COALESCE(total_score, 0) + ?, "
                "posts_count = COALESCE(posts_count, 0) + 1, "
                "channel_posts_count = COALESCE(channel_posts_count, 0) + ? WHERE user_id = ?",
                (score, ch_add, u_id)
            )
            await db.execute(
                "UPDATE posts SET score = ?, status = 'accepted', comment = ? WHERE id = ?",
                (score, comment_text if has_comment else None, post_id)
            )
        else:
            await db.execute(
                "UPDATE posts SET score = 0, status = 'rejected', comment = ? WHERE id = ?",
                (comment_text if has_comment else None, post_id)
            )
        await db.commit()

    user_msg = ""
    if score > 0:
        user_msg += f"🎉 <b>Postingiz tekshiruvdan o'tdi va qabul qilindi!</b>\n"
        user_msg += f"⭐ Sizga berilgan baho: <b>{score} ⭐</b>\n"
        if in_ch == 1:
            user_msg += f"📢 <b>Postingiz rasmiy kanalga chiqarilishi ma'qullandi!</b>\n"
    else:
        user_msg += f"⚠️ <b>Afsuski, postingiz qabul qilinmadi.</b>\n"

    if has_comment:
        user_msg += f"\n💬 <b>Tekshiruvchi izohi:</b>\n<i>{comment_text}</i>"

    try:
        await bot.send_message(chat_id=u_id, text=user_msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Foydalanuvchiga yuborishda xatolik: {e}")

    await message.answer(
        f"✅ <b>Post #{post_id} baholandi va natija foydalanuvchiga yetkazildi!</b>\n"
        f"Baho: {score} ⭐ | Kanal: {'Ha' if in_ch == 1 else 'Yo‘q'}",
        parse_mode="HTML"
    )
    await state.clear()

# ----------------- TIZIM STATISTIKASI -----------------
@dp.callback_query(F.data == "admin_sys_stats")
async def show_stats(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        u_count = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        p_count = (await (await db.execute("SELECT COUNT(*) FROM posts")).fetchone())[0]

    await callback.message.edit_text(
        f"📊 <b>Tizim Statistikasi:</b>\n\n"
        f"👥 Foydalanuvchilar soni: <b>{u_count} ta</b>\n"
        f"📝 Jami postlar soni: <b>{p_count} ta</b>",
        reply_markup=get_admin_panel_inline(),
        parse_mode="HTML"
    )
    await callback.answer()

# ----------------- ISHGA TUSHIRISH (PORT VA WEB SERVIS) -----------------
async def start_bot_background(app):
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    app["bot_task"] = asyncio.create_task(dp.start_polling(bot))

async def stop_bot_background(app):
    if "bot_task" in app:
        app["bot_task"].cancel()
        try:
            await app["bot_task"]
        except asyncio.CancelledError:
            pass
    await bot.session.close()

async def handle_ping(request):
    return web.Response(text="Bot faol ishlamoqda!")

def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.on_startup.append(start_bot_background)
    app.on_cleanup.append(stop_bot_background)
    port = int(os.environ.get("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
