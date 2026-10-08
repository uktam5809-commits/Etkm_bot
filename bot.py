import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

# ----------------- ASOSIY SOZLAMALAR -----------------
BOT_TOKEN = "8882153518:AAHJUWfsAYgPwdaSIDI1FhhxCw1xRcSh020"
SUPER_ADMIN_ID = 6439380297  # Bosh admin
DB_PATH = "bot_data.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

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

# 1. Do'kon boshqaruvi
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
    builder.adjust(1)

    await callback.message.edit_text("O'chirmoqchi bo'lgan mahsulotingizni tanlang:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("del_shop_item:"))
async def process_del_shop_item(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    item_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM shop_items WHERE id = ?", (item_id,))
        await db.commit()
    await callback.answer("Mahsulot o'chirildi!")
    await list_shop_delete(callback)

@dp.callback_query(F.data == "admin_back_to_panel")
async def back_to_admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    cur_ch = await get_setting("channel")
    cur_log = await get_setting("log_chat")
    shop_st = "Faol ✅" if (await get_setting("shop_status")) == "active" else "Sozlanmoqda 🚧"

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

# 2. Kanal sozlash
@dp.callback_query(F.data == "admin_set_channel")
async def start_set_channel(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_new_channel)
    await callback.message.answer(
        "📢 Majburiy obuna kanali username'ini yuboring (masalan: <b>@kanalim</b>):\n"
        "<i>(O'chirish uchun '0' deb yozing)</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_new_channel), F.text)
async def save_new_channel(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    val = message.text.strip()
    if val == "0":
        await set_setting("channel", "")
        await message.answer("✅ Majburiy obuna o'chirildi.", reply_markup=get_main_menu(message.from_user.id))
    else:
        if not (val.startswith("@") or val.startswith("-100")):
            val = "@" + val
        await set_setting("channel", val)
        await message.answer(f"✅ Kanal saqlandi: <b>{val}</b>", parse_mode="HTML", reply_markup=get_main_menu(message.from_user.id))
    await state.clear()

# 3. Arxiv chat sozlash
@dp.callback_query(F.data == "admin_set_log_chat")
async def start_set_log_chat(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_log_chat)
    await callback.message.answer(
        "📑 <b>Arxiv (post va ballar) guruhi/kanali:</b>\n\n"
        "Username yoki ID raqamini (masalan: <code>-100...</code>) yuboring:\n"
        "<i>(O'chirish uchun '0' deb yozing)</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_log_chat), F.text)
async def save_new_log_chat(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    val = message.text.strip()
    if val == "0":
        await set_setting("log_chat", "")
        await message.answer("✅ Arxiv guruhi o'chirildi.", reply_markup=get_main_menu(message.from_user.id))
    else:
        await set_setting("log_chat", val)
        await message.answer(f"✅ Arxiv guruhi saqlandi: <b>{val}</b>", parse_mode="HTML", reply_markup=get_main_menu(message.from_user.id))
    await state.clear()

# 4. Tekshiruvchi qo'shish
@dp.callback_query(F.data == "admin_add_checker")
async def start_add_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_new_admin)
    await callback.message.answer(
        "➕ <b>Yangi tekshiruvchi qo'shish:</b>\nUning <b>@username</b> yoki <b>ID</b> sini kiriting:\n(Bekor qilish uchun '0'):",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_new_admin), F.text)
async def save_new_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    query = message.text.strip()
    if query == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    async with aiosqlite.connect(DB_PATH) as db:
        if query.isdigit():
            user_id = int(query)
        else:
            uname = query.replace("@", "")
            cursor = await db.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (uname,))
            row = await cursor.fetchone()
            user_id = row[0] if row else None

        if not user_id:
            await message.answer("❌ Foydalanuvchi topilmadi. U avval botga kirib /start bosgan bo'lishi kerak!")
            return

        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Tekshiruvchi admin qo'shildi (ID: <code>{user_id}</code>)!", reply_markup=get_main_menu(message.from_user.id), parse_mode="HTML")

# 5. Tekshiruvchini o'chirish
@dp.callback_query(F.data == "admin_remove_checker")
async def start_remove_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM admins WHERE user_id != ?", (SUPER_ADMIN_ID,))
        rows = await cursor.fetchall()

    if not rows:
        await callback.answer("Qo'shimcha tekshiruvchilar yo'q!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for (aid,) in rows:
        builder.button(text=f"❌ O'chirish: {aid}", callback_data=f"del_admin:{aid}")
    builder.adjust(1)
    await callback.message.answer("O'chirmoqchi bo'lgan tekshiruvchini tanlang:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("del_admin:"))
async def process_del_admin(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    del_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (del_id,))
        await db.commit()
    await callback.message.edit_text(f"✅ Tekshiruvchi (ID: {del_id}) o'chirildi!")
    await callback.answer()

# 6. Reklama yuborish
@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_broadcast)
    await callback.message.answer(
        "📨 <b>Reklama xabari:</b>\n\nBarcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring:\n<i>(Bekor qilish uchun '0' deb yozing)</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_broadcast))
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    if message.text and message.text.strip() == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    async with aiosqlite.connect(DB_PATH) as db:
        users = await (await db.execute("SELECT user_id FROM users")).fetchall()

    await message.answer("🚀 Xabar yuborilmoqda...")
    sent, failed = 0, 0
    for (uid,) in users:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await state.clear()
    await message.answer(f"📊 <b>Natija:</b>\n\n✅ Yetkazildi: {sent} ta\n❌ Bloklagan: {failed} ta", reply_markup=get_main_menu(message.from_user.id), parse_mode="HTML")

# 7. Ballni tahrirlash
@dp.callback_query(F.data == "admin_edit_score")
async def ask_target_user(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_user_query)
    await callback.message.answer(
        "👤 Ballini o'zgartirmoqchi bo'lgan foydalanuvchining <b>@username</b> yoki <b>ID</b> sini kiriting:\n(Bekor qilish uchun '0'):",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(AdminState.waiting_for_user_query), F.text)
async def process_target_user(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    query = message.text.strip()
    if query == "0":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    async with aiosqlite.connect(DB_PATH) as db:
        if query.isdigit():
            cursor = await db.execute("SELECT user_id, full_name, total_score FROM users WHERE user_id = ?", (int(query),))
        else:
            uname = query.replace("@", "")
            cursor = await db.execute("SELECT user_id, full_name, total_score FROM users WHERE LOWER(username) = LOWER(?)", (uname,))
        user = await cursor.fetchone()

    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi. Qaytadan tekshiring:")
        return

    uid, name, cur_score = user
    await state.update_data(target_id=uid, target_name=name)
    await state.set_state(AdminState.waiting_for_new_score)

    await message.answer(
        f"👤 {name} (ID: <code>{uid}</code>)\n⭐ Hozirgi ball: <b>{cur_score}</b>\n\nYangi ballni kiriting:",
        parse_mode="HTML"
    )

@dp.message(StateFilter(AdminState.waiting_for_new_score), F.text)
async def set_new_score(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    text = message.text.strip()
    if not (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
        await message.answer("Iltimos, son kiriting:")
        return

    new_score = int(text)
    data = await state.get_data()
    target_id, target_name = data["target_id"], data["target_name"]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET total_score = ? WHERE user_id = ?", (new_score, target_id))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Ball yangilandi!\n{target_name} — <b>{new_score} ⭐</b>", reply_markup=get_main_menu(message.from_user.id), parse_mode="HTML")

# 8. Statistika
@dp.callback_query(F.data == "admin_sys_stats")
async def show_system_stats(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        u_count = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        p_count = (await (await db.execute("SELECT COUNT(*) FROM posts WHERE status = 'approved'")).fetchone())[0]
        a_count = (await (await db.execute("SELECT COUNT(*) FROM admins")).fetchone())[0]

    cur_ch = await get_setting("channel")
    cur_log = await get_setting("log_chat")
    await callback.message.edit_text(
        f"📈 <b>Bot umumiy statistikasi:</b>\n\n"
        f"📢 Majburiy kanal: <b>{cur_ch if cur_ch else 'Oʻchiq'}</b>\n"
        f"📑 Arxiv guruhi: <b>{cur_log if cur_log else 'Ulanmagan'}</b>\n"
        f"👨‍⚖️ Tekshiruvchilar: <b>{a_count} nafar</b>\n"
        f"👥 Foydalanuvchilar: <b>{u_count} kishi</b>\n"
        f"✅ Tasdiqlangan postlar: <b>{p_count} ta</b>",
        reply_markup=get_admin_panel_inline(),
        parse_mode="HTML"
    )
    await callback.answer()

# ----------------- FOYDALANUVCHIDAN POST QABUL QILISH -----------------
@dp.message(StateFilter(UserState.waiting_for_post), F.text | F.photo | F.video)
async def process_user_post(message: types.Message, state: FSMContext):
    user = message.from_user

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO posts (user_id, message_id) VALUES (?, ?)", (user.id, message.message_id))
        post_id = cursor.lastrowid
        await db.commit()

    await state.clear()
    await message.answer("✅ <b>Postingiz qabul qilindi va ko'rib chiqishga yuborildi!</b>", reply_markup=get_main_menu(user.id), parse_mode="HTML")

    username_str = f"@{user.username}" if user.username else "Mavjud emas"
    admin_card = (
        f"📩 <b>Yangi post keldi! (ID: #{post_id})</b>\n\n"
        f"👤 <b>Muallif:</b> {user.full_name}\n"
        f"🔗 <b>Username:</b> {username_str}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n\n"
        f"⭐ <b>Postni baholang:</b>"
    )

    for admin_id in await get_all_admins():
        try:
            await bot.copy_message(chat_id=admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
            await bot.send_message(chat_id=admin_id, text=admin_card, reply_markup=get_admin_post_keyboard(post_id, in_channel=0), parse_mode="HTML")
        except Exception:
            pass

    log_chat = await get_setting("log_chat")
    if log_chat:
        try:
            await bot.copy_message(chat_id=log_chat, from_chat_id=message.chat.id, message_id=message.message_id)
            await bot.send_message(chat_id=log_chat, text=f"📥 <b>Yangi post qabul qilindi:</b>\nMuallif: {user.full_name} ({username_str})", parse_mode="HTML")
        except Exception as e:
            logging.warning(f"Arxivga yuborishda xatolik: {e}")

# ----------------- KANALGA CHIQARILADI (STATUS) -----------------
@dp.callback_query(F.data.startswith("toggle_channel:"))
async def toggle_channel_status(callback: types.CallbackQuery):
    if not await is_checker_admin(callback.from_user.id):
        await callback.answer("Faqat tekshiruvchilar bosa oladi!", show_alert=True)
        return

    post_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT in_channel FROM posts WHERE id = ?", (post_id,))
        row = await cursor.fetchone()
        if not row:
            return
        new_val = 0 if row[0] == 1 else 1
        await db.execute("UPDATE posts SET in_channel = ? WHERE id = ?", (new_val, post_id))
        await db.commit()

    await callback.answer("✅ Kanalga chiqariladi deb belgilandi!" if new_val == 1 else "Bekor qilindi!", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=get_admin_post_keyboard(post_id, in_channel=new_val))

# ----------------- TEKSHIRUVCHILAR BAHOLASHI VA HISOBOT -----------------
@dp.callback_query(F.data.startswith("rate:"))
async def process_rating(callback: types.CallbackQuery, state: FSMContext):
    if not await is_checker_admin(callback.from_user.id):
        await callback.answer("Faqat tekshiruvchilar baholay oladi!", show_alert=True)
        return

    _, post_id_str, score_str = callback.data.split(":")
    post_id, score = int(post_id_str), int(score_str)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT status FROM posts WHERE id = ?", (post_id,))
        post = await cursor.fetchone()
        if not post or post[0] != "pending":
            await callback.answer("Bu post allaqachon baholangan!", show_alert=True)
            return

    await state.set_state(AdminState.waiting_for_comment)
    await state.update_data(post_id=post_id, score=score, admin_msg_id=callback.message.message_id, orig_text=callback.message.text)
    await callback.answer()
    await callback.message.answer(
        f"📝 <b>Baho: {score} ⭐</b>\n\nMuallifga izoh yuboring (Izohsiz bo'lsa '0' deb yozing):",
        parse_mode="HTML"
    )

@dp.message(StateFilter(AdminState.waiting_for_comment), F.text)
async def process_admin_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post_id, score, admin_msg_id, admin_name = data["post_id"], data["score"], data["admin_msg_id"], message.from_user.full_name
    comment_text = message.text
    has_comment = comment_text.lower() not in ["0", "yo'q", "yoq", "none", "-"]

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, in_channel FROM posts WHERE id = ?", (post_id,))
        post = await cursor.fetchone()
        if not post:
            await state.clear()
            return
        author_id, in_channel = post

        u_cursor = await db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (author_id,))
        user_info = await u_cursor.fetchone()
        u_name = user_info[0] if user_info else "Noma'lum"
        u_uname = f"@{user_info[1]}" if (user_info and user_info[1]) else "Mavjud emas"

        if score > 0:
            await db.execute("UPDATE posts SET score = ?, status = 'approved', comment = ? WHERE id = ?", (score, comment_text if has_comment else None, post_id))
            await db.execute("UPDATE users SET total_score = total_score + ?, posts_count = posts_count + 1 WHERE user_id = ?", (score, author_id))
            user_msg = f"🎉 <b>Postingiz qabul qilindi!</b>\n\n⭐ <b>Baholandi:</b> {score} ball\n👨‍⚖️ <b>Hakam:</b> {admin_name}"
            status_text = f"📌 <b>Baho:</b> {score} ⭐ (Hakam: {admin_name})"
        else:
            await db.execute("UPDATE posts SET status = 'rejected', comment = ? WHERE id = ?", (comment_text if has_comment else None, post_id))
            user_msg = f"❌ <b>Postingiz qabul qilinmadi.</b>\n\n👨‍⚖️ <b>Hakam:</b> {admin_name}"
            status_text = f"📌 <b>Baho:</b> Rad etildi ❌ (Hakam: {admin_name})"

        if in_channel == 1:
            status_text += "\n📢 <b>Kanal:</b> Kanalga chiqariladi ✅"
            user_msg += "\n📢 <i>Postingiz kanalga chiqarish uchun tavsiya etildi!</i>"

        await db.commit()

    if has_comment:
        user_msg += f"\n💬 <b>Izoh:</b> <i>{comment_text}</i>"
        status_text += f"\n💬 <b>Izoh:</b> {comment_text}"

    try:
        await bot.send_message(chat_id=author_id, text=user_msg, parse_mode="HTML")
    except Exception:
        pass

    try:
        await bot.edit_message_text(chat_id=message.chat.id, message_id=admin_msg_id, text=f"{data['orig_text']}\n\n{status_text}", parse_mode="HTML")
    except Exception:
        pass

    log_chat = await get_setting("log_chat")
    if log_chat:
        try:
            log_report = (
                f"📊 <b>Post baholandi (Post #{post_id})</b>\n\n"
                f"👤 <b>Muallif:</b> {u_name} ({u_uname})\n"
                f"👨‍⚖️ <b>Hakam:</b> {admin_name}\n"
                f"⭐ <b>Qo'yilgan ball:</b> {score} ⭐\n"
                f"📢 <b>Kanalga tavsiya:</b> {'Ha ✅' if in_channel == 1 else 'Yo‘q'}\n"
                f"💬 <b>Izoh:</b> {comment_text if has_comment else 'Izohsiz'}"
            )
            await bot.send_message(chat_id=log_chat, text=log_report, parse_mode="HTML")
        except Exception:
            pass

    await message.answer("✅ Natija saqlandi va arxivga yetkazildi!")
    await state.clear()

# ----------------- ISHGA TUSHIRISH -----------------
async def main():
    await init_db()
    print("Bot muvaffaqiyatli ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
