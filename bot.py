import asyncio
import logging
import aiosqlite
import os
import aiocron
import random
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from pathlib import Path
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# === Конфигурация ===
load_dotenv()
TOKEN = getenv("BOT_TOKEN")
ADMINS = list(map(int, getenv("ADMINS", "").split(","))) if getenv("ADMINS") else []
DB_PATH = getenv("DB_PATH", "reports.db")
EMPLOYEE_CODE = str(getenv("EMPLOYEE_CODE", "0000"))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Пути к медиафайлам
MEDIA_FILES = {
    "personal_cabinet": "lc.mp4",
    "my_reports": "reports.mp4",
    "reports": "report.mp4",
    "tasks": "tasks.mp4",
    "motivation": "motivation.mp4"
}

# Состояния FSM
class AdminStates(StatesGroup):
    waiting_task_type = State()
    waiting_task_text = State()
    waiting_task_assign = State()
    waiting_report_period = State()
    waiting_custom_period = State()
    waiting_revision_reason = State()

class UserStates(StatesGroup):
    waiting_for_code = State()
    waiting_for_photo_or_text = State()
    waiting_for_text = State()

# === Вспомогательные функции ===
async def send_media(message: types.Message, media_key: str, caption: str = "") -> bool:
    """Отправляет медиафайл из локального хранилища"""
    try:
        current_dir = Path(__file__).parent
        media_filename = MEDIA_FILES.get(media_key)
        
        if not media_filename:
            logger.error(f"Unknown media key: {media_key}")
            return False
        
        media_path = current_dir / media_filename
        if not media_path.exists():
            logger.error(f"Media file not found: {media_path}")
            await message.answer("⚠ Медиафайл временно недоступен")
            return False
        
        media = FSInputFile(path=str(media_path))
        
        if media_path.suffix == ".mp4":
            await message.answer_video(video=media, caption=caption, supports_streaming=True)
        else:
            await message.answer_photo(photo=media, caption=caption)
            
        return True
    
    except Exception as e:
        logger.error(f"Error sending media {media_key}: {str(e)}")
        await message.answer(f"⚠ Не удалось отправить медиафайл. {caption}")
        return False

async def notify_admins(text: str, exclude_id: int = None):
    """Отправляет уведомление всем админам"""
    for admin_id in ADMINS:
        if admin_id != exclude_id:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

async def get_user_name(user_id: int) -> str:
    """Получает имя пользователя из БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else "Неизвестный пользователь"

# === Клавиатуры ===
def get_main_keyboard(is_admin: bool = False):
    """Главное меню"""
    if is_admin:
        buttons = [
            [KeyboardButton(text="📊 Посмотреть Отчеты")],
            [KeyboardButton(text="📌 Отправить Задачи")],
            [KeyboardButton(text="🏆 Рейтинг Сотрудников")],
            [KeyboardButton(text="✅ Проверить Отчеты")]
        ]
    else:
        buttons = [
            [KeyboardButton(text="📝 Отправить Отчет")],
            [KeyboardButton(text="📊 Мои Отчеты"), KeyboardButton(text="👤 Личный Кабинет")],
            [KeyboardButton(text="📌 Мои Задачи"), KeyboardButton(text="💪 Мотивация")]
        ]
    
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_back_keyboard():
    """Клавиатура с кнопкой Назад"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True
    )

def get_report_period_keyboard():
    """Клавиатура выбора периода отчетов"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Текущая Неделя")],
            [KeyboardButton(text="📆 Выбрать Период")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_task_type_keyboard():
    """Клавиатура выбора типа задачи"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Основная Задача")],
            [KeyboardButton(text="📋 Дополнительная Задача")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_approval_keyboard():
    """Клавиатура проверки отчетов"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Принять"), KeyboardButton(text="🔄 Доработка")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_users_keyboard(users: list):
    """Инлайн-клавиатура для выбора пользователей"""
    keyboard = []
    for user_id, full_name in users:
        keyboard.append([InlineKeyboardButton(text=full_name, callback_data=f"user_{user_id}")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# === Инициализация базы данных ===
async def init_db():
    """Инициализация таблиц в базе данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                position TEXT NOT NULL DEFAULT 'Сотрудник',
                register_date TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                photo_id TEXT,
                report_text TEXT,
                report_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'На проверке',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                task_text TEXT NOT NULL,
                task_date TEXT NOT NULL,
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'Новая',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")
        
        await db.commit()

# === Команда /start ===
@dp.message(Command("start", "help"))
async def start_command(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    
    logger.info(f"User {full_name} (ID: {user_id}) started the bot")
    
    # Проверка админа
    if user_id in ADMINS:
        await message.answer(
            f"👋 Добро пожаловать, администратор {full_name}!",
            reply_markup=get_main_keyboard(is_admin=True)
        )
        return
    
    # Проверка регистрации пользователя
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_exists = await cursor.fetchone()
    
    if user_exists:
        await message.answer(
            f"✅ Приветствуем, {full_name}!",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "🔒 Для доступа к боту введите код сотрудника:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(UserStates.waiting_for_code)

# === Регистрация пользователя ===
@dp.message(F.text, UserStates.waiting_for_code)
async def process_employee_code(message: types.Message, state: FSMContext):
    """Обработка кода сотрудника"""
    user_input = message.text.strip()
    
    if user_input == EMPLOYEE_CODE:
        user_id = message.from_user.id
        full_name = message.from_user.full_name
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO users (user_id, full_name) VALUES (?, ?)",
                (user_id, full_name)
            )
            await db.commit()
        
        await message.answer(
            f"✅ Регистрация успешна! Добро пожаловать, {full_name}!",
            reply_markup=get_main_keyboard()
        )
        await state.clear()
        
        # Уведомление админам
        await notify_admins(f"🆕 Новый сотрудник: {full_name} (ID: {user_id})")
    else:
        await message.answer("❌ Неверный код сотрудника. Попробуйте ещё раз.")

# === Обработка кнопки Назад ===
@dp.message(F.text == "🔙 Назад")
async def back_handler(message: types.Message, state: FSMContext):
    """Обработчик кнопки Назад"""
    user_id = message.from_user.id
    await state.clear()
    
    if user_id in ADMINS:
        await message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard(is_admin=True)
    else:
        await message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard())

# === Отправка отчета ===
@dp.message(F.text == "📝 Отправить Отчет")
async def start_report(message: types.Message, state: FSMContext):
    """Начало процесса отправки отчета"""
    caption = "📸 Отправьте фото выполненного задания или просто напишите текст отчёта:"
    await send_media(message, "my_reports", caption)
    await message.answer(caption, reply_markup=get_back_keyboard())
    await state.set_state(UserStates.waiting_for_photo_or_text)

@dp.message(F.photo, UserStates.waiting_for_photo_or_text)
async def receive_report_photo(message: types.Message, state: FSMContext):
    """Получение фото отчета"""
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer(
        "✍ Напишите описание задания (или отправьте текст 'без описания'):",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(UserStates.waiting_for_text)

@dp.message(F.text, UserStates.waiting_for_text)
async def receive_report_text(message: types.Message, state: FSMContext):
    """Получение текста отчета"""
    if message.text == "🔙 Назад":
        await back_handler(message, state)
        return
    
    data = await state.get_data()
    photo_id = data.get('photo_id')
    report_text = message.text if message.text.lower() != "без описания" else None
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    today = datetime.now().strftime("%d.%m.%Y")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO reports 
            (user_id, full_name, photo_id, report_text, report_date, status) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, full_name, photo_id, report_text, today, "На проверке")
        )
        await db.commit()
    
    await message.answer(
        "✅ Ваш отчёт сохранён и отправлен на проверку.",
        reply_markup=get_main_keyboard()
    )
    await state.clear()
    
    # Уведомление админам
    await notify_admins(f"📥 Новый отчёт от {full_name}\n📅 Дата: {today}")

# === Просмотр отчетов пользователя ===
@dp.message(F.text == "📊 Мои Отчеты")
async def show_user_reports(message: types.Message):
    """Показывает отчеты пользователя за текущую неделю"""
    user_id = message.from_user.id
    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT report_date, report_text, status 
            FROM reports 
            WHERE user_id = ? AND report_date BETWEEN ? AND ?
            ORDER BY report_date DESC""",
            (user_id, start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()
    
    if not reports:
        caption = "📭 У вас нет отчётов за текущую неделю."
        await send_media(message, "reports", caption)
        return
    
    response = "📊 Ваши отчёты за текущую неделю:\n\n"
    for report_date, report_text, status in reports:
        response += f"📅 <b>{report_date}</b>\n"
        if report_text:
            response += f"📝 {report_text}\n"
        response += f"🔄 Статус: {status}\n\n"
    
    await send_media(message, "reports", response)

# === Личный кабинет ===
@dp.message(F.text == "👤 Личный Кабинет")
async def show_personal_cabinet(message: types.Message):
    """Отображает личный кабинет с статистикой"""
    user_id = message.from_user.id
    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем количество отчетов
        async with db.execute(
            "SELECT COUNT(*) FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ?",
            (user_id, start_date, end_date)
        ) as cursor:
            submitted = (await cursor.fetchone())[0]
        
        # Получаем информацию о пользователе
        async with db.execute(
            "SELECT position, register_date FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            user_info = await cursor.fetchone()
    
    position = user_info[0] if user_info else "Сотрудник"
    register_date = user_info[1] if user_info else "неизвестно"
    
    # Рассчитываем пропущенные отчеты
    start = datetime.strptime(start_date, "%d.%m.%Y")
    end = datetime.strptime(end_date, "%d.%m.%Y")
    total_days = (end - start).days + 1
    missed = total_days - submitted
    
    caption = (
        f"👤 <b>Личный Кабинет</b>\n\n"
        f"🧑‍💼 <b>Должность:</b> {position}\n"
        f"📅 <b>Дата регистрации:</b> {register_date}\n\n"
        f"📊 <b>Статистика за текущую неделю:</b>\n"
        f"✅ <b>Сдано отчётов:</b> {submitted}\n"
        f"❌ <b>Пропущено отчётов:</b> {missed}"
    )
    
    await send_media(message, "personal_cabinet", caption)

# === Мои задачи ===
@dp.message(F.text == "📌 Мои Задачи")
async def show_user_tasks(message: types.Message):
    """Показывает задачи пользователя"""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT task_type, task_text, task_date, deadline, status 
            FROM tasks 
            WHERE user_id = ? AND status != 'Завершена'
            ORDER BY task_date DESC""",
            (user_id,)
        ) as cursor:
            tasks = await cursor.fetchall()
    
    if not tasks:
        caption = "📭 У вас нет активных задач."
        await send_media(message, "tasks", caption)
        return
    
    response = "📌 <b>Ваши задачи:</b>\n\n"
    for task_type, task_text, task_date, deadline, status in tasks:
        response += f"📅 <b>{task_date}</b>\n"
        response += f"📋 <b>{task_type}:</b> {task_text}\n"
        if deadline:
            response += f"⏳ <b>Срок:</b> {deadline}\n"
        response += f"🔄 <b>Статус:</b> {status}\n\n"
    
    await send_media(message, "tasks", response)

# === Мотивация ===
@dp.message(F.text == "💪 Мотивация")
async def send_motivation(message: types.Message):
    """Отправляет мотивационное сообщение"""
    motivations = [
        "Ты можешь больше, чем думаешь! 💪",
        "Каждый день — это новый шанс стать лучше! 🌟",
        "Не сдавайся! У тебя всё получится! 🚀",
        "Ты — звезда! Сияй ярче! ✨",
        "Маленькие шаги ведут к большим победам! 🏆"
    ]
    motivation = random.choice(motivations)
    await send_media(message, "motivation", motivation)

# === Админские функции ===

# Рейтинг сотрудников
@dp.message(F.text == "🏆 Рейтинг Сотрудников")
async def show_employee_rating(message: types.Message):
    """Показывает рейтинг сотрудников по количеству отчетов"""
    if message.from_user.id not in ADMINS:
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT full_name, COUNT(*) as report_count 
            FROM reports 
            WHERE report_date BETWEEN date('now', 'weekday 0', '-7 days') AND date('now')
            GROUP BY user_id 
            ORDER BY report_count DESC"""
        ) as cursor:
            rating = await cursor.fetchall()
    
    if not rating:
        await message.answer("📭 Нет данных для формирования рейтинга.")
        return
    
    response = "🏆 <b>Рейтинг сотрудников за текущую неделю:</b>\n\n"
    for idx, (full_name, report_count) in enumerate(rating, start=1):
        response += f"{idx}. {full_name}: <b>{report_count}</b> отчётов\n"
    
    await message.answer(response)

# Проверка отчетов
@dp.message(F.text == "✅ Проверить Отчеты")
async def start_reports_check(message: types.Message, state: FSMContext):
    """Начинает процесс проверки отчетов"""
    if message.from_user.id not in ADMINS:
        return
    
    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, full_name, photo_id, report_text, report_date 
            FROM reports 
            WHERE status = 'На проверке' 
            AND report_date BETWEEN ? AND ?
            ORDER BY report_date""",
            (start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()
    
    if not reports:
        await message.answer("📭 Нет отчётов на проверку.")
        return
    
    await state.update_data(reports=reports, current_report=0)
    await show_next_report(message, state)

async def show_next_report(message: types.Message, state: FSMContext):
    """Показывает следующий отчет для проверки"""
    data = await state.get_data()
    reports = data.get("reports", [])
    current_report = data.get("current_report", 0)
    
    if current_report >= len(reports):
        await message.answer(
            "✅ Все отчеты проверены.",
            reply_markup=get_main_keyboard(is_admin=True)
        await state.clear()
        return
    
    report_id, full_name, photo_id, report_text, report_date = reports[current_report]
    
    caption = f"📝 <b>Отчёт от {full_name}</b>\n📅 <b>Дата:</b> {report_date}"
    if report_text:
        caption += f"\n\n{report_text}"
    
    await state.update_data(current_report_id=report_id)
    
    if photo_id:
        await message.answer_photo(
            photo_id,
            caption=caption,
            reply_markup=get_approval_keyboard())
    else:
        await message.answer(
            caption,
            reply_markup=get_approval_keyboard())

# Принятие отчета
@dp.message(F.text == "✅ Принять")
async def approve_report(message: types.Message, state: FSMContext):
    """Принимает отчет"""
    data = await state.get_data()
    report_id = data.get("current_report_id")
    
    if not report_id:
        await message.answer("❌ Ошибка: не найден текущий отчет.")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Обновляем статус отчета
        await db.execute(
            "UPDATE reports SET status = 'Принят' WHERE id = ?",
            (report_id,)
        )
        
        # Получаем информацию для уведомления
        async with db.execute(
            "SELECT user_id, report_date FROM reports WHERE id = ?",
            (report_id,)
        ) as cursor:
            user_id, report_date = await cursor.fetchone()
        
        await db.commit()
    
    await message.answer("✅ Отчёт принят.")
    
    # Уведомляем сотрудника
    try:
        await bot.send_message(
            user_id,
            f"✅ Ваш отчёт за {report_date} был принят.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    # Показываем следующий отчет
    await state.update_data(current_report=data.get("current_report", 0) + 1)
    await show_next_report(message, state)

# Отправка на доработку
@dp.message(F.text == "🔄 Доработка")
async def request_revision(message: types.Message, state: FSMContext):
    """Запрашивает доработку отчета"""
    await message.answer(
        "📝 Укажите причину для доработки:",
        reply_markup=get_back_keyboard())
    await state.set_state(AdminStates.waiting_revision_reason)

@dp.message(F.text, AdminStates.waiting_revision_reason)
async def process_revision_reason(message: types.Message, state: FSMContext):
    """Обрабатывает причину доработки"""
    if message.text == "🔙 Назад":
        await show_next_report(message, state)
        return
    
    reason = message.text
    data = await state.get_data()
    report_id = data.get("current_report_id")
    
    if not report_id:
        await message.answer("❌ Ошибка: не найден текущий отчет.")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Обновляем статус отчета
        await db.execute(
            "UPDATE reports SET status = 'На доработке' WHERE id = ?",
            (report_id,)
        )
        
        # Получаем информацию для уведомления
        async with db.execute(
            "SELECT user_id, report_date FROM reports WHERE id = ?",
            (report_id,)
        ) as cursor:
            user_id, report_date = await cursor.fetchone()
        
        # Сохраняем уведомление для пользователя
        await db.execute(
            """INSERT INTO notifications (user_id, message)
            VALUES (?, ?)""",
            (user_id, f"Ваш отчёт за {report_date} требует доработки. Причина: {reason}")
        )
        
        await db.commit()
    
    await message.answer(
        "🔄 Отчёт отправлен на доработку.",
        reply_markup=get_approval_keyboard())
    
    # Уведомляем сотрудника
    try:
        await bot.send_message(
            user_id,
            f"🔄 Ваш отчёт за {report_date} требует доработки.\n<b>Причина:</b> {reason}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    # Показываем следующий отчет
    await state.update_data(current_report=data.get("current_report", 0) + 1)
    await show_next_report(message, state)

# Отправка задач
@dp.message(F.text == "📌 Отправить Задачи")
async def start_task_creation(message: types.Message, state: FSMContext):
    """Начинает процесс создания задачи"""
    if message.from_user.id not in ADMINS:
        return
    
    await message.answer(
        "Выберите тип задачи:",
        reply_markup=get_task_type_keyboard())
    await state.set_state(AdminStates.waiting_task_type)

@dp.message(F.text, AdminStates.waiting_task_type)
async def process_task_type(message: types.Message, state: FSMContext):
    """Обрабатывает тип задачи"""
    if message.text == "🔙 Назад":
        await back_handler(message, state)
        return
    
    if message.text not in ["📋 Основная Задача", "📋 Дополнительная Задача"]:
        await message.answer("Пожалуйста, выберите тип задачи из предложенных вариантов.")
        return
    
    await state.update_data(task_type=message.text)
    await message.answer(
        "Введите текст задачи:",
        reply_markup=get_back_keyboard())
    await state.set_state(AdminStates.waiting_task_text)

@dp.message(F.text, AdminStates.waiting_task_text)
async def process_task_text(message: types.Message, state: FSMContext):
    """Обрабатывает текст задачи"""
    if message.text == "🔙 Назад":
        await state.set_state(AdminStates.waiting_task_type)
        await message.answer(
            "Выберите тип задачи:",
            reply_markup=get_task_type_keyboard())
        return
    
    await state.update_data(task_text=message.text)
    
    # Получаем список пользователей для назначения задачи
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, full_name FROM users ORDER BY full_name"
        ) as cursor:
            users = await cursor.fetchall()
    
    if not users:
        await message.answer("❌ Нет пользователей для назначения задачи.")
        await state.clear()
        return
    
    await message.answer(
        "Выберите сотрудника для назначения задачи:",
        reply_markup=get_users_keyboard(users))
    await state.set_state(AdminStates.waiting_task_assign)

@dp.callback_query(F.data.startswith("user_"), AdminStates.waiting_task_assign)
async def assign_task(callback: types.CallbackQuery, state: FSMContext):
    """Назначает задачу выбранному пользователю"""
    if callback.data == "cancel":
        await callback.message.edit_text("❌ Назначение задачи отменено.")
        await state.clear()
        return
    
    user_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    task_type = data.get("task_type")
    task_text = data.get("task_text")
    task_date = datetime.now().strftime("%d.%m.%Y")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO tasks 
            (user_id, task_type, task_text, task_date, status) 
            VALUES (?, ?, ?, ?, ?)""",
            (user_id, task_type, task_text, task_date, "Новая")
        )
        
        # Получаем имя пользователя для уведомления
        async with db.execute(
            "SELECT full_name FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            full_name = (await cursor.fetchone())[0]
        
        await db.commit()
    
    await callback.message.edit_text(
        f"✅ Задача назначена сотруднику {full_name}.")
    
    # Уведомляем сотрудника
    try:
        await bot.send_message(
            user_id,
            f"📌 Вам назначена новая задача:\n\n"
            f"<b>Тип:</b> {task_type}\n"
            f"<b>Описание:</b> {task_text}")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    await state.clear()

# Просмотр отчетов за период
@dp.message(F.text == "📊 Посмотреть Отчеты")
async def start_reports_view(message: types.Message, state: FSMContext):
    """Начинает процесс просмотра отчетов за период"""
    if message.from_user.id not in ADMINS:
        return
    
    await message.answer(
        "Выберите период для просмотра отчетов:",
        reply_markup=get_report_period_keyboard())
    await state.set_state(AdminStates.waiting_report_period)

@dp.message(F.text, AdminStates.waiting_report_period)
async def process_report_period(message: types.Message, state: FSMContext):
    """Обрабатывает выбор периода отчетов"""
    if message.text == "🔙 Назад":
        await back_handler(message, state)
        return
    
    if message.text == "📅 Текущая Неделя":
        start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
        end_date = datetime.now().strftime("%d.%m.%Y")
        await show_reports_for_period(message, start_date, end_date)
        await state.clear()
    elif message.text == "📆 Выбрать Период":
        await message.answer(
            "Введите период в формате ДД.ММ.ГГГГ-ДД.ММ.ГГГГ (например, 01.01.2023-31.01.2023):",
            reply_markup=get_back_keyboard())
        await state.set_state(AdminStates.waiting_custom_period)

@dp.message(F.text, AdminStates.waiting_custom_period)
async def process_custom_period(message: types.Message, state: FSMContext):
    """Обрабатывает пользовательский период"""
    if message.text == "🔙 Назад":
        await state.set_state(AdminStates.waiting_report_period)
        await message.answer(
            "Выберите период для просмотра отчетов:",
            reply_markup=get_report_period_keyboard())
        return
    
    try:
        start_date, end_date = message.text.split("-")
        datetime.strptime(start_date.strip(), "%d.%m.%Y")
        datetime.strptime(end_date.strip(), "%d.%m.%Y")
        await show_reports_for_period(message, start_date.strip(), end_date.strip())
        await state.clear()
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ-ДД.ММ.ГГГГ (например, 01.01.2023-31.01.2023)")

async def show_reports_for_period(message: types.Message, start_date: str, end_date: str):
    """Показывает отчеты за указанный период"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT full_name, report_date, report_text, status 
            FROM reports 
            WHERE report_date BETWEEN ? AND ?
            ORDER BY report_date DESC, full_name""",
            (start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()
    
    if not reports:
        await message.answer(
            f"📭 Нет отчетов за период с {start_date} по {end_date}.")
        return
    
    response = f"📊 <b>Отчеты за период с {start_date} по {end_date}:</b>\n\n"
    
    current_date = None
    for full_name, report_date, report_text, status in reports:
        if report_date != current_date:
            response += f"\n📅 <b>{report_date}</b>\n"
            current_date = report_date
        
        response += f"👤 <b>{full_name}</b>\n"
        if report_text:
            response += f"📝 {report_text}\n"
        response += f"🔄 {status}\n\n"
    
    # Разбиваем сообщение на части, если оно слишком длинное
    if len(response) > 4000:
        parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(response)

# === Запуск бота ===
async def on_startup():
    """Действия при запуске бота"""
    await init_db()
    await notify_admins("🤖 Бот успешно запущен!")
    logger.info("Bot started")

async def on_shutdown():
    """Действия при выключении бота"""
    await notify_admins("⚠ Бот выключается...")
    logger.info("Bot stopped")

async def main():
    """Основная функция запуска бота"""
    await on_startup()
    
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
