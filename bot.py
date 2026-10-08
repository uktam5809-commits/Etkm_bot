import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite
from aiohttp import web

# ----------------- ASOSIY SOZLAMALAR -----------------
BOT_TOKEN = "8882153518:AAHJUWfsAYgPwdaSIDI1FhhxCw1xRcSh020"
SUPER_ADMIN_ID = 6439380297  # Bosh admin
DB_PATH = "bot_data.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ----------------- RENDER UCHUN DUMMY SERVER -----------------
async def dummy_web_server():
    async def handle(request):
        return web.Response(text="Bot is running 24/7!")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ----------------- FSM HOLATLARI -----------------
class UserState(StatesGroup):
    waiting_for_post = State()

class AdminState(StatesGroup):
    waiting_for_user_query = State()
    waiting_for_new_score = State()
    waiting_for_new_channel = State()
    waiting_for_log_chat = State()
    waiting_for_new_admin = State()
    waiting_for_broadcast = State()
    waiting_for_comment = State()
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
                posts_count INTEGER DEFAULT 0
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
            ("comment", "ALTER TABLE posts ADD COLUMN comment TEXT"),
            ("in_channel", "ALTER TABLE posts ADD COLUMN in_channel INTEGER DEFAULT 0")
        ]:
            try:
                await db.execute(query)
            except Exception:
                pass

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
        if member.status in ["left", "kicked"]:
            return False
        return True
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
        [KeyboardButton(text="🛍 Yulduzlar do‘koni")]
    ]
    if user_id == SUPER_ADMIN_ID:
        kb.append([KeyboardButton(text="⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_panel_inline():
    builder = InlineKeyboardBuilder()
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
            "INSERT INTO users (user_id, full_name, username) VALUES (?, ?, ?) "
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
            "SELECT total_score, posts_count FROM users WHERE user_id = ?",
            (message.from_user.id,)
        )
        data = await cursor.fetchone()

    total_score = data[0] if data else 0
    posts_count = data[1] if data else 0

    await message.answer(
        f"👤 <b>Sizning profilingiz:</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"📝 Qabul qilingan postlar: <b>{posts_count} ta</b>\n"
        f"⭐ Jami yulduzlar: <b>{total_score} ball</b>",
        parse_mode="HTML"
    )

@dp.message(F.text == "🏆 Top 10 Reyting")
async def show_leaderboard(message: types.Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT full_name, username, total_score, posts_count FROM users "
            "WHERE total_score > 0 ORDER BY total_score DESC LIMIT 10"
        )
        top_users = await cursor.fetchall()

    if not top_users:
        await message.answer("ℹ️ Hozircha reytingda hech kim yo'q.")
        return

    text = "🏆 <b>TOP-10 ishtirokchilar reytingi:</b>\n\n"
    for idx, (name, uname, score, count) in enumerate(top_users, start=1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        u_tag = f"(@{uname})" if uname else ""
        text += f"{medal} <b>{name}</b> {u_tag} — {score} ⭐ ({count} ta post)\n"

    await message.answer(text, parse_mode="HTML")

# ----------------- YULDUZLAR DO'KONI -----------------
@dp.message(F.text == "🛍 Yulduzlar do‘koni")
async def show_shop(message: types.Message, state: FSMContext):
    await state.clear()
    status = await get_setting("shop_status")

    if status != "active":
        await message.answer(
            "🚧 <b>Yulduzlar do‘koni sozlanmoqda...</b>\n\n"
            "Tez orada to‘plagan yulduzchalaringiz evaziga qiziqarli sovg‘alarni qo‘lga kiritishingiz mumkin bo‘ladi! ✨",
            parse_mode="HTML"
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, title, price FROM shop_items")
        items = await cursor.fetchall()

    if not items:
        await message.answer("🚧 Hozircha do‘konda mahsulotlar tayyorlanmoqda...")
        return

    builder = InlineKeyboardBuilder()
    for item_id, title, price in items:
        builder.button(text=f"{title} — {price} ⭐", callback_data=f"buy_item:{item_id}")
    builder.adjust(1)

    await message.answer(
        "🛍 <b>Yulduzlar do‘koni:</b>\n\n"
        "O‘zingiz to‘plagan yulduzchalar evaziga quyidagi mahsulotlarni tanlashingiz mumkin:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("buy_item:"))
async def process_buy(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT title, price FROM shop_items WHERE id = ?", (item_id,))
        item = await cursor.fetchone()
        u_cur = await db.execute("SELECT total_score FROM users WHERE user_id = ?", (callback.from_user.id,))
        u_row = await u_cur.fetchone()

    if not item:
        await callback.answer("Mahsulot topilmadi!", show_alert=True)
        return

    title, price = item
    score = u_row[0] if u_row else 0

    if score < price:
        await callback.answer(f"⚠️ Yulduzchalar yetarli emas! Sizda: {score} ⭐, kerak: {price} ⭐", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET total_score = total_score - ? WHERE user_id = ?", (price, callback.from_user.id))
        await db.commit()

    await callback.answer("Buyurtmangiz qabul qilindi!", show_alert=True)
    await callback.message.answer(
        f"🎉 <b>Xaridingiz uchun tashakkur!</b>\n\n"
        f"Siz <b>{title}</b> uchun buyurtma berdingiz. Tez orada admin siz bilan bog'lanadi.",
        parse_mode="HTML"
    )

    try:
        await bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=f"🛒 <b>Yangi do‘kon xaridi!</b>\n\n"
                 f"👤 Foydalanuvchi: {callback.from_user.full_name} (@{callback.from_user.username})\n"
                 f"🆔 ID: <code>{callback.from_user.id}</code>\n"
                 f"📦 Mahsulot: <b>{title}</b> ({price} ⭐)",
            parse_mode="HTML"
        )
    except Exception:
        pass

# ----------------- ADMIN PANEL -----------------
@dp.message(F.text == "⚙️ Admin Panel")
async def open_admin_panel(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    await state.clear()
    cur_ch = await get_setting("channel")
    cur_log = await get_setting("log_chat")
    shop_st = "Faol ✅" if (await get_setting("shop_status")) == "active" else "Sozlanmoqda 🚧"

    await message.answer(
        f"🛠 <b>Boshqaruv Paneli</b>\n\n"
        f"📢 Kanal: <b>{cur_ch if cur_ch else 'Oʻchiq'}</b>\n"
        f"📑 Arxiv: <b>{cur_log if cur_log else 'Ulanmagan'}</b>\n"
        f"🛍 Do‘kon: <b>{shop_st}</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=get_admin_panel_inline(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_manage_shop")
async def manage_shop_menu(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return

    st = await get_setting("shop_status")
    status_text = "Faol holatda ✅" if st == "active" else "Sozlanmoqda (o'chiq) 🚧"

    builder = InlineKeyboardBuilder()
    if st == "active":
        builder.button(text="🔒 Do'konni yopish (Sozlanmoqda)", callback_data="shop_toggle:inactive")
    else:
        builder.button(text="🔓 Do'konni ochish (Faollashtirish)", callback_data="shop_toggle:active")

    builder.button(text="➕ Yangi mahsulot qo'shish", callback_data="shop_add_item")
    builder.button(text="🗑 Mahsulotlarni o'chirish", callback_data="shop_delete_list")
    builder.button(text="⬅️ Ortga", callback_data="admin_back_to_panel")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🛍 <b>Yulduzlar do‘koni boshqaruvi:</b>\n\n"
        f"Hozirgi holat: <b>{status_text}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("shop_toggle:"))
async def toggle_shop_status(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    new_st = callback.data.split(":")[1]
    await set_setting("shop_status", new_st)
    await callback.answer("Do‘kon holati yangilandi!")
    await manage_shop_menu(callback)

@dp.callback_query(F.data == "shop_add_item")
async def start_add_item(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_shop_item)
    await callback.message.answer(
        "📦 <b>Yangi mahsulot qo'shish:</b>\n\n"
        "Nomini va narxini quyidagi formatda yuboring:\n"
        "<code>Nomi:Narxi</code>\n\n"
        "Masalan: <b>Futbolka:50</b> yoki <b>Bloknot:20</b>\n"
        "<i>(Bekor qilish uchun '0' deb yozing)</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_shop_item), F.text)
async def save_shop_item(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    text = message.text.strip()
    if text == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    if ":" not in text:
        await message.answer("Iltimos, <code>Nomi:Narxi</code> shaklida yuboring (Masalan: Kitob:30):", parse_mode="HTML")
        return

    title, price_str = text.split(":", 1)
    if not price_str.strip().isdigit():
        await message.answer("Narxi faqat musbat son bo'lishi kerak!")
        return

    title = title.strip()
    price = int(price_str.strip())

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO shop_items (title, price) VALUES (?, ?)", (title, price))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ <b>{title}</b> mahsuloti ({price} ⭐) do‘konga qo‘shildi!", reply_markup=get_main_menu(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "shop_delete_list")
async def list_shop_delete(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        items = await (await db.execute("SELECT id, title, price FROM shop_items")).fetchall()

    if not items:
        await callback.answer("Mahsulotlar yo'q!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for i_id, title, price in items:
        builder.button(text=f"❌ {title} ({price} ⭐)", callback_data=f"del_shop_item:{i_id}")
    builder.button(text="⬅️ Ortga", callback_data="admin_manage_shop")

