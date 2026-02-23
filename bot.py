import asyncio
import logging
import sqlite3
import random
import string
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, InputMediaPhoto
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8625733673:AAHiKNXZnl8NxBb-4B9tr_dUyZybcGHH1jE"  # Вставь свой токен от @BotFather
ADMIN_IDS = [8354775853]  # Вставь свои ID (узнать у @userinfobot)

# Твои реквизиты для оплаты (будут показываться при заказе)
PAYMENT_DETAILS = {
    "card_number": "2200 1536 6698 8895",
    "card_holder": "Роман Соколов",
    "bank_name": "Альфа Банк",
    "comment_note": "Обязательно укажите комментарий к переводу!"
}

# Путь к базе данных
DB_PATH = "shop.db"

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Пользователи
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Товары
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price INTEGER NOT NULL,
            file_id TEXT,
            photo_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Заказы
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            amount INTEGER NOT NULL,
            payment_comment TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'waiting',  -- waiting, paid, completed, cancelled
            screenshot_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    """)
    conn.commit()
    conn.close()

# Вспомогательные функции для работы с БД
def add_user(user_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
        (user_id, username, full_name)
    )
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users

def get_all_products():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price, file_id, photo_id FROM products ORDER BY id DESC")
    products = cur.fetchall()
    conn.close()
    return products

def get_product(product_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price, file_id, photo_id FROM products WHERE id=?", (product_id,))
    product = cur.fetchone()
    conn.close()
    return product

def add_product(name, description, price, file_id=None, photo_id=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name, description, price, file_id, photo_id) VALUES (?, ?, ?, ?, ?)",
        (name, description, price, file_id, photo_id)
    )
    conn.commit()
    product_id = cur.lastrowid
    conn.close()
    return product_id

def delete_product(product_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()

def create_order(user_id, product_id, product_name, amount, payment_comment):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO orders (user_id, product_id, product_name, amount, payment_comment) VALUES (?, ?, ?, ?, ?)",
        (user_id, product_id, product_name, amount, payment_comment)
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id

def get_order(order_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = cur.fetchone()
    conn.close()
    return order

def get_order_by_comment(comment):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE payment_comment=?", (comment,))
    order = cur.fetchone()
    conn.close()
    return order

def update_order_status(order_id, status, screenshot_file_id=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if screenshot_file_id:
        cur.execute("UPDATE orders SET status=?, screenshot_file_id=? WHERE id=?", (status, screenshot_file_id, order_id))
    else:
        cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()

def get_pending_orders():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE status='waiting' ORDER BY created_at DESC")
    orders = cur.fetchall()
    conn.close()
    return orders

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders WHERE status='paid'")
    paid_orders = cur.fetchone()[0]
    cur.execute("SELECT SUM(amount) FROM orders WHERE status='paid'")
    total_income = cur.fetchone()[0] or 0
    conn.close()
    return users_count, paid_orders, total_income

# ==================== FSM СОСТОЯНИЯ ====================
class AddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    file = State()  # опционально

class Broadcast(StatesGroup):
    message = State()
    confirm = State()

# ==================== КЛАВИАТУРЫ ====================
def admin_panel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить товар", callback_data="admin_add_product")
    kb.button(text="📦 Список товаров", callback_data="admin_list_products")
    kb.button(text="⏳ Ожидают оплаты", callback_data="admin_pending_orders")
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="📨 Рассылка", callback_data="admin_broadcast")
    kb.adjust(2)
    return kb.as_markup()

def products_keyboard(products):
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p[1]} — {p[3]} руб.", callback_data=f"product_{p[0]}")
    kb.button(text="🔙 Назад", callback_data="back_to_start")
    kb.adjust(1)
    return kb.as_markup()

def product_detail_keyboard(product_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Купить", callback_data=f"buy_{product_id}")
    kb.button(text="🔙 К товарам", callback_data="catalog")
    return kb.as_markup()

def order_keyboard(order_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я оплатил", callback_data=f"paid_{order_id}")
    kb.button(text="❌ Отменить заказ", callback_data=f"cancel_order_{order_id}")
    return kb.as_markup()

def admin_order_keyboard(order_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_{order_id}")
    kb.button(text="❌ Отклонить", callback_data=f"admin_reject_{order_id}")
    return kb.as_markup()

def back_to_admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 В админку", callback_data="admin_back")
    return kb.as_markup()

# ==================== ОБЩИЕ ФУНКЦИИ ====================
def generate_payment_comment():
    return "ORDER" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    add_user(user.id, user.username, user.full_name)
    
    text = (
        f"👋 <b>Добро пожаловать, {user.first_name}!</b>\n\n"
        f"🛍 Это магазин цифровых товаров. Здесь ты можешь приобрести полезные материалы.\n\n"
        f"📌 Чтобы посмотреть каталог, нажми кнопку ниже."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Каталог товаров", callback_data="catalog")
    if is_admin(user.id):
        kb.button(text="⚙️ Админ-панель", callback_data="admin_panel")
    await message.answer(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "catalog")
async def show_catalog(callback: CallbackQuery):
    products = get_all_products()
    if not products:
        await callback.message.edit_text("📭 Каталог пуст. Загляните позже.")
        await callback.answer()
        return
    
    text = "🛒 <b>Каталог товаров:</b>\n\nВыберите интересующий товар:"
    await callback.message.edit_text(text, reply_markup=products_keyboard(products))
    await callback.answer()

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: CallbackQuery):
    await cmd_start(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = get_product(product_id)
    if not product:
        await callback.answer("Товар не найден")
        return
    
    # product: id, name, description, price, file_id, photo_id
    text = (
        f"<b>{product[1]}</b>\n\n"
        f"{product[2] or 'Нет описания'}\n\n"
        f"💰 Цена: <b>{product[3]} руб.</b>"
    )
    
    if product[5]:  # есть фото
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=product[5],
            caption=text,
            reply_markup=product_detail_keyboard(product_id)
        )
    else:
        await callback.message.edit_text(text, reply_markup=product_detail_keyboard(product_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])
    product = get_product(product_id)
    if not product:
        await callback.answer("Товар не найден")
        return
    
    # Генерируем уникальный комментарий
    payment_comment = generate_payment_comment()
    
    # Создаем заказ
    order_id = create_order(
        user_id=callback.from_user.id,
        product_id=product_id,
        product_name=product[1],
        amount=product[3],
        payment_comment=payment_comment
    )
    
    text = (
        f"🧾 <b>Заказ #{order_id}</b>\n\n"
        f"Товар: {product[1]}\n"
        f"Сумма: {product[3]} руб.\n\n"
        f"<b>💳 Реквизиты для оплаты:</b>\n"
        f"Карта: <code>{PAYMENT_DETAILS['card_number']}</code>\n"
        f"Получатель: {PAYMENT_DETAILS['card_holder']}\n"
        f"Банк: {PAYMENT_DETAILS['bank_name']}\n\n"
        f"📝 <b>Важно!</b> В комментарии к переводу укажите:\n"
        f"<code>{payment_comment}</code>\n\n"
        f"{PAYMENT_DETAILS['comment_note']}\n\n"
        f"✅ После оплаты нажмите кнопку «Я оплатил» и отправьте скриншот."
    )
    
    await callback.message.edit_text(text, reply_markup=order_keyboard(order_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("paid_"))
async def paid_order(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден")
        return
    
    if order[6] != "waiting":  # status
        await callback.answer("Этот заказ уже обработан")
        return
    
    await state.update_data(order_id=order_id)
    await callback.message.edit_text(
        "📎 Пожалуйста, отправьте скриншот подтверждения оплаты (фото).\n"
        "После проверки администратор выдаст товар."
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    if order and order[6] == "waiting":
        update_order_status(order_id, "cancelled")
        await callback.message.edit_text("❌ Заказ отменён.")
    else:
        await callback.answer("Невозможно отменить")
    await callback.answer()

@dp.message(F.photo, F.chat.type == "private")
async def handle_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        return  # не в режиме ожидания скрина
    
    order = get_order(order_id)
    if not order or order[6] != "waiting":
        await message.answer("Ошибка: заказ не найден или уже обработан.")
        await state.clear()
        return
    
    # Сохраняем file_id скриншота и меняем статус? Нет, пока оставляем waiting, просто пересылаем админам
    screenshot_id = message.photo[-1].file_id
    update_order_status(order_id, "waiting", screenshot_id)  # сохраняем скрин, статус не меняем
    
    # Отправляем админам
    caption = (
        f"🔔 <b>Новое подтверждение оплаты!</b>\n\n"
        f"Заказ №{order_id}\n"
        f"Пользователь: @{message.from_user.username} (ID: {message.from_user.id})\n"
        f"Товар: {order[4]}\n"  # product_name
        f"Сумма: {order[5]} руб.\n"
        f"Комментарий: <code>{order[7]}</code>"  # payment_comment
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo=screenshot_id,
                caption=caption,
                reply_markup=admin_order_keyboard(order_id)
            )
        except Exception as e:
            logging.error(f"Не удалось отправить админу {admin_id}: {e}")
    
    await message.answer("✅ Скриншот отправлен администратору. Ожидайте подтверждения.")
    await state.clear()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыберите действие:",
        reply_markup=admin_panel_keyboard()
    )

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    await callback.message.edit_text(
        "⚙️ <b>Панель администратора</b>\n\nВыберите действие:",
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery):
    await admin_panel_callback(callback)

@dp.callback_query(F.data == "admin_add_product")
async def admin_add_product_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    await callback.message.edit_text("Введите <b>название товара</b>:")
    await state.set_state(AddProduct.name)
    await callback.answer()

@dp.message(AddProduct.name)
async def add_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите <b>описание товара</b> (можно отправить пустое сообщение):")
    await state.set_state(AddProduct.description)

@dp.message(AddProduct.description)
async def add_product_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите <b>цену товара</b> (только число, в рублях):")
    await state.set_state(AddProduct.price)

@dp.message(AddProduct.price)
async def add_product_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
        if price <= 0:
            raise ValueError
        await state.update_data(price=price)
        await message.answer(
            "Отправьте <b>фото товара</b> (для красивого отображения в каталоге) или пропустите, отправив «.»",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_photo")]])
        )
        await state.set_state(AddProduct.file)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число (например: 500)")

@dp.callback_query(F.data == "skip_photo", AddProduct.file)
async def skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_id=None)
    await callback.message.edit_text("Теперь отправьте <b>файл товара</b> (документ, видео и т.п.) или пропустите, отправив «.»")
    # Оставляем состояние AddProduct.file для файла
    await callback.answer()

@dp.message(AddProduct.file, F.photo)
async def add_product_photo(message: Message, state: FSMContext):
    # Сохраняем фото
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("Фото сохранено. Теперь отправьте <b>файл товара</b> (документ, видео и т.п.) или пропустите, отправив «.»")

@dp.message(AddProduct.file, F.document | F.video | F.audio)
async def add_product_file(message: Message, state: FSMContext):
    # Определяем file_id
    if message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.audio:
        file_id = message.audio.file_id
    else:
        file_id = None
    
    data = await state.get_data()
    # Если фото не было загружено, но могло быть пропущено
    photo_id = data.get("photo_id")
    
    # Добавляем товар в БД
    product_id = add_product(
        name=data["name"],
        description=data.get("description", ""),
        price=data["price"],
        file_id=file_id,
        photo_id=photo_id
    )
    
    await message.answer(f"✅ Товар <b>{data['name']}</b> успешно добавлен! ID: {product_id}")
    await state.clear()
    # Возвращаемся в админку
    await admin_panel(message)

@dp.message(AddProduct.file, F.text == ".")
async def skip_file(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = add_product(
        name=data["name"],
        description=data.get("description", ""),
        price=data["price"],
        file_id=None,
        photo_id=data.get("photo_id")
    )
    await message.answer(f"✅ Товар <b>{data['name']}</b> успешно добавлен! ID: {product_id}")
    await state.clear()
    await admin_panel(message)

@dp.message(AddProduct.file)
async def add_product_invalid(message: Message):
    await message.answer("Пожалуйста, отправьте файл (документ, фото, видео) или «.» для пропуска.")

@dp.callback_query(F.data == "admin_list_products")
async def admin_list_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    products = get_all_products()
    if not products:
        await callback.message.edit_text("📭 Товаров нет.", reply_markup=back_to_admin_keyboard())
        return
    
    text = "<b>Список товаров:</b>\n\n"
    for p in products:
        text += f"🔹 <b>{p[1]}</b> — {p[3]} руб.\n"
        text += f"   ID: {p[0]} | Файл: {'✅' if p[4] else '❌'} | Фото: {'✅' if p[5] else '❌'}\n\n"
    
    # Кнопка удаления (для упрощения добавим inline кнопки удаления по ID)
    # В реальном проекте лучше сделать отдельный диалог удаления
    await callback.message.edit_text(
        text,
        reply_markup=back_to_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_pending_orders")
async def admin_pending_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    orders = get_pending_orders()
    if not orders:
        await callback.message.edit_text("⏳ Нет заказов, ожидающих оплаты.", reply_markup=back_to_admin_keyboard())
        await callback.answer()
        return
    
    # Показываем список заказов
    text = "⏳ <b>Заказы, ожидающие проверки:</b>\n\n"
    for o in orders:
        text += f"#{o[0]} | {o[4]} | {o[5]} руб. | Комментарий: <code>{o[7]}</code>\n"
    text += "\n<i>Для подтверждения используйте кнопки под скриншотами.</i>"
    await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_confirm_"))
async def admin_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    if not order or order[6] != "waiting":
        await callback.answer("Заказ не найден или уже обработан")
        return
    
    # Обновляем статус
    update_order_status(order_id, "paid")
    
    # Получаем товар, чтобы отправить файл
    product_id = order[3]
    product = get_product(product_id)
    
    # Отправляем пользователю товар
    try:
        if product and product[4]:  # есть file_id
            await bot.send_document(
                chat_id=order[1],
                document=product[4],
                caption=f"✅ Ваш заказ #{order_id} подтверждён!\n\nСпасибо за покупку!\nТовар: {order[4]}"
            )
        else:
            await bot.send_message(
                chat_id=order[1],
                text=f"✅ Ваш заказ #{order_id} подтверждён!\n\nСпасибо за покупку!\nТовар: {order[4]}\n\nСсылка на скачивание будет предоставлена отдельно (если применимо)."
            )
        await callback.message.edit_caption(
            caption=f"✅ Заказ #{order_id} подтверждён. Товар отправлен пользователю."
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке товара: {e}")
        await callback.message.edit_caption(
            caption=f"✅ Заказ #{order_id} подтверждён, но не удалось отправить файл. Проверьте вручную."
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    if not order or order[6] != "waiting":
        await callback.answer("Заказ не найден или уже обработан")
        return
    
    update_order_status(order_id, "cancelled")
    
    # Уведомляем пользователя
    await bot.send_message(
        chat_id=order[1],
        text=f"❌ Ваш заказ #{order_id} отклонён. Возможно, платёж не найден. Попробуйте оформить заказ снова."
    )
    await callback.message.edit_caption(caption=f"❌ Заказ #{order_id} отклонён.")
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    users, paid_orders, income = get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"✅ Оплаченных заказов: {paid_orders}\n"
        f"💰 Общий доход: {income} руб."
    )
    await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    await callback.message.edit_text(
        "📨 <b>Рассылка</b>\n\nОтправьте сообщение, которое хотите разослать всем пользователям.\n"
        "Можно использовать текст, фото, видео, документы и т.д."
    )
    await state.set_state(Broadcast.message)
    await callback.answer()

@dp.message(Broadcast.message, F.content_type.in_({'text', 'photo', 'video', 'document', 'audio', 'animation'}))
async def broadcast_get_message(message: Message, state: FSMContext):
    # Сохраняем информацию о сообщении для рассылки
    await state.update_data(
        content_type=message.content_type,
        text=message.html_text if message.html_text else None,
        caption=message.caption_html if message.caption else None,
        file_id=(
            message.photo[-1].file_id if message.photo else
            message.video.file_id if message.video else
            message.document.file_id if message.document else
            message.audio.file_id if message.audio else
            message.animation.file_id if message.animation else None
        )
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Начать рассылку", callback_data="broadcast_confirm")
    kb.button(text="❌ Отмена", callback_data="broadcast_cancel")
    await message.answer(
        "Сообщение готово. Начать рассылку?",
        reply_markup=kb.as_markup()
    )
    await state.set_state(Broadcast.confirm)

@dp.callback_query(F.data == "broadcast_confirm", Broadcast.confirm)
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    users = get_all_users()
    await callback.message.edit_text(f"⏳ Рассылка начата. Всего пользователей: {len(users)}")
    
    success = 0
    fail = 0
    for uid in users:
        try:
            if data['content_type'] == 'text':
                await bot.send_message(uid, data['text'])
            elif data['content_type'] == 'photo':
                await bot.send_photo(uid, data['file_id'], caption=data['caption'])
            elif data['content_type'] == 'video':
                await bot.send_video(uid, data['file_id'], caption=data['caption'])
            elif data['content_type'] == 'document':
                await bot.send_document(uid, data['file_id'], caption=data['caption'])
            elif data['content_type'] == 'audio':
                await bot.send_audio(uid, data['file_id'], caption=data['caption'])
            elif data['content_type'] == 'animation':
                await bot.send_animation(uid, data['file_id'], caption=data['caption'])
            success += 1
            await asyncio.sleep(0.05)  # небольшая задержка, чтобы не флудить
        except Exception as e:
            fail += 1
            logging.error(f"Ошибка при отправке пользователю {uid}: {e}")
    
    await callback.message.edit_text(
        f"✅ Рассылка завершена.\n"
        f"Успешно: {success}\n"
        f"Ошибок: {fail}"
    )
    await state.clear()

@dp.callback_query(F.data == "broadcast_cancel", Broadcast.confirm)
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    logging.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

