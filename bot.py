import asyncio
import logging
import aiosqlite
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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.enums import ParseMode

# === Загрузка переменных окружения ===
load_dotenv()
TOKEN = getenv("BOT_TOKEN")
ADMINS = list(map(int, getenv("ADMINS", "").split(","))) if getenv("ADMINS") else []
DB_PATH = getenv("DB_PATH", "reports.db")
EMPLOYEE_CODE = str(getenv("EMPLOYEE_CODE"))

# Логирование для проверки
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="bot.log"
)
logger = logging.getLogger(__name__)

# === Инициализация бота ===
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

# Пути к видеофайлам
VIDEO_FILES = {
    "personal_cabinet": "lc.mp4",
    "my_reports": "reports.mp4",
    "reports": "report.mp4",
    "tasks": "tasks.mp4",
    "motivation": "motivation.mp4"
}

# Проверка наличия видеофайлов при старте
for video_key, filename in VIDEO_FILES.items():
    if not Path(filename).exists():
        logger.warning(f"Видеофайл {filename} для ключа {video_key} не найден!")

async def send_video(message: types.Message, video_key: str, caption: str = "") -> bool:
    """Отправляет видео из локального файла"""
    try:
        video_filename = VIDEO_FILES.get(video_key)
        if not video_filename:
            logger.error(f"Неизвестный ключ видео: {video_key}")
            return False
        
        video_path = Path(video_filename)
        if not video_path.exists():
            logger.error(f"Видео файл не найден: {video_path}")
            await message.answer("⚠ Видео временно недоступно")
            return False
        
        video = FSInputFile(path=str(video_path))
        await message.answer_video(
            video=video, 
            caption=caption[:1024],  # Ограничение длины подписи
            supports_streaming=True
        )
        return True
    
    except Exception as e:
        logger.error(f"Ошибка при отправке видео {video_key}: {str(e)}", exc_info=True)
        await message.answer(f"⚠ Не удалось отправить видео. {caption[:1024]}")
        return False
# === Клавиатуры ===
def get_main_keyboard(is_admin: bool = False):
    if is_admin:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 Посмотреть Отчеты")],
                [KeyboardButton(text="📌 Отправить Задачи")],
                [KeyboardButton(text="🏆 Рейтинг Сотрудников")],
                [KeyboardButton(text="✅ Проверить Отчеты")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие..."
        )
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝 Отправить Отчет")],
                [KeyboardButton(text="📊 Мои Отчеты"), KeyboardButton(text="👤 Личный Кабинет")],
                [KeyboardButton(text="📌 Мои Задачи"), KeyboardButton(text="💪 Мотивация")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие..."
        )

def get_back_only_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True,
        input_field_placeholder="..."
    )

def get_report_period_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Текущая Неделя")],
            [KeyboardButton(text="📆 Выбрать Период")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите период..."
    )

def get_task_type_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Основная Задача")],
            [KeyboardButton(text="📋 Дополнительная Задача")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите тип задачи..."
    )

def get_approval_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Принять"), KeyboardButton(text="🔄 Отправить на Доработку")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

# === Инициализация базы данных ===
async def init_db():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")  # Улучшенный режим работы с БД
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    position TEXT NOT NULL DEFAULT 'Сотрудник',
                    registered_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )""")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    task_text TEXT NOT NULL,
                    task_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Новая',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )""")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)")
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}", exc_info=True)
        raise

# === Обработка ошибок ===
async def on_startup():
    logger.info("Бот запускается...")
    await init_db()
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, "🟢 Бот запущен и готов к работе!")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")

async def on_shutdown():
    logger.info("Бот выключается...")
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, "🔴 Бот выключается...")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")

# === Команда /start ===
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    full_name = message.from_user.full_name

    logger.info(f"Пользователь {full_name} (ID: {user_id}) нажал /start")

    if user_id in ADMINS:
        await message.answer(
            f"👋 Добро пожаловать, {hd.bold('админ')} {hd.quote(full_name)}!",
            reply_markup=get_main_keyboard(is_admin=True)
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

    if user:
        await message.answer(
            f"✅ Привет, {hd.quote(user[0])}!",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "🔒 Введите код сотрудника для регистрации:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state("waiting_for_code")

# === Регистрация сотрудника ===
@dp.message(F.text, StateFilter("waiting_for_code"))
async def process_registration_code(message: types.Message, state: FSMContext):
    user_input = message.text.strip()
    if user_input == EMPLOYEE_CODE:
        user_id = message.from_user.id
        full_name = message.from_user.full_name

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO users (user_id, full_name) VALUES (?, ?)",
                    (user_id, full_name)
                )
                await db.commit()

            await message.answer(
                f"✅ Добро пожаловать, {hd.quote(full_name)}!",
                reply_markup=get_main_keyboard()
            )
            await state.clear()
            
            # Уведомление админам
            for admin_id in ADMINS:
                await bot.send_message(
                    admin_id,
                    f"🆕 Новый сотрудник зарегистрирован:\n"
                    f"👤 {full_name}\n"
                    f"🆔 {user_id}"
                )
                
        except Exception as e:
            logger.error(f"Ошибка регистрации пользователя: {e}")
            await message.answer("⚠ Произошла ошибка при регистрации. Попробуйте позже.")
    else:
        await message.answer("❌ Неверный код сотрудника. Попробуйте ещё раз.")

# === Обработка кнопки Назад ===
@dp.message(F.text == "🔙 Назад")
async def back_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    
    if user_id in ADMINS:
        await message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard(is_admin=True)
        )
    else:
        await message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )

# === Отправить Отчет ===
@dp.message(F.text == "📝 Отправить Отчет")
async def send_report(message: types.Message, state: FSMContext):
    # Проверяем, зарегистрирован ли пользователь
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if not await cursor.fetchone():
                await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
                return

    res = "📸 Отправьте фото задания или просто напишите текст отчёта:"
    await send_video(message, "my_reports", res)
    await message.answer(res, reply_markup=get_back_only_keyboard())
    await state.set_state("waiting_for_photo_or_text")

@dp.message(F.photo, StateFilter("waiting_for_photo_or_text"))
async def receive_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer(
        "✍ Напишите описание задания (или отправьте текст 'без описания'):", 
        reply_markup=get_back_only_keyboard()
    )
    await state.set_state("waiting_for_text")

@dp.message(F.text, StateFilter("waiting_for_text", "waiting_for_photo_or_text"))
async def receive_text(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await back_handler(message, state)
        return
    
    data = await state.get_data()
    photo_id = data.get('photo_id')
    report_text = message.text if message.text.lower() != "без описания" else None
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    today = datetime.now().strftime("%d.%m.%Y")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO reports (user_id, full_name, photo_id, report_text, report_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, full_name, photo_id, report_text, today)
            )
            await db.commit()

        await message.answer(
            "✅ Ваш отчёт сохранён и отправлен на проверку.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

        # Уведомление админам
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f"📥 Новый отчёт от {hd.bold(full_name)}.\n"
                    f"📅 Дата: {hd.quote(today)}\n"
                    f"🆔 ID: {user_id}"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка сохранения отчета: {e}")
        await message.answer(
            "⚠ Произошла ошибка при сохранении отчета. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

# === Мои Отчеты ===
@dp.message(F.text == "📊 Мои Отчеты")
async def my_reports(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем, зарегистрирован ли пользователь
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if not await cursor.fetchone():
                await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
                return

    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT report_date, report_text, status FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ? ORDER BY report_date DESC",
                (user_id, start_date, end_date)
            ) as cursor:
                reports = await cursor.fetchall()

        if not reports:
            resp = "📭 У вас нет отчётов за текущую неделю."
            await send_video(message, "reports", resp)
            return

        response = "📊 Ваши отчёты за текущую неделю:\n\n"
        for report_date, report_text, status in reports:
            response += f"📅 <b>{report_date}</b>\n"
            if report_text:
                response += f"📝 {report_text}\n"
            response += f"🔄 Статус: <i>{status}</i>\n\n"

        await send_video(message, "reports", response)

    except Exception as e:
        logger.error(f"Ошибка получения отчетов: {e}")
        await message.answer("⚠ Произошла ошибка при получении отчетов. Попробуйте позже.")

# === Личный Кабинет ===
@dp.message(F.text == "👤 Личный Кабинет")
async def personal_cabinet(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем, зарегистрирован ли пользователь
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if not await cursor.fetchone():
                await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
                return

    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Количество сданных отчетов
            async with db.execute(
                "SELECT COUNT(*) FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ?",
                (user_id, start_date, end_date)
            ) as cursor:
                submitted = (await cursor.fetchone())[0]

            # Количество принятых отчетов
            async with db.execute(
                "SELECT COUNT(*) FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ? AND status = 'Принят'",
                (user_id, start_date, end_date)
            ) as cursor:
                approved = (await cursor.fetchone())[0]

            # Количество отчетов на доработке
            async with db.execute(
                "SELECT COUNT(*) FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ? AND status = 'На доработке'",
                (user_id, start_date, end_date)
            ) as cursor:
                in_revision = (await cursor.fetchone())[0]

        start = datetime.strptime(start_date, "%d.%m.%Y")
        end = datetime.strptime(end_date, "%d.%m.%Y")
        total_days = (end - start).days + 1
        missed = total_days - submitted

        caption = (
            f"👤 <b>Личный Кабинет</b>\n\n"
            f"📊 Ваша статистика за текущую неделю:\n"
            f"✅ <b>Сдано отчётов:</b> {submitted}\n"
            f"✔ <b>Принято отчётов:</b> {approved}\n"
            f"✏ <b>На доработке:</b> {in_revision}\n"
            f"❌ <b>Пропущено отчётов:</b> {missed}\n\n"
            f"📅 Рабочих дней: {total_days}"
        )
        
        await send_video(message, "personal_cabinet", caption)

    except Exception as e:
        logger.error(f"Ошибка получения данных личного кабинета: {e}")
        await message.answer("⚠ Произошла ошибка при получении данных. Попробуйте позже.")

# === Мои Задачи ===
@dp.message(F.text == "📌 Мои Задачи")
async def my_tasks(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем, зарегистрирован ли пользователь
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if not await cursor.fetchone():
                await message.answer("❌ Вы не зарегистрированы. Нажмите /start")
                return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT task_type, task_text, task_date FROM tasks WHERE user_id = ? AND status = 'Новая' ORDER BY task_date DESC",
                (user_id,)
            ) as cursor:
                tasks = await cursor.fetchall()

        if not tasks:
            resp = "📭 У вас нет новых задач."
            await send_video(message, "tasks", resp)
            return

        response = "📌 <b>Ваши задачи:</b>\n\n"
        for task_type, task_text, task_date in tasks:
            response += f"📅 <b>{task_date}</b>\n"
            response += f"📋 <i>{task_type}:</i> {task_text}\n\n"

        await send_video(message, "tasks", response)

    except Exception as e:
        logger.error(f"Ошибка получения задач: {e}")
        await message.answer("⚠ Произошла ошибка при получении задач. Попробуйте позже.")

# === Мотивация ===
@dp.message(F.text == "💪 Мотивация")
async def send_motivation(message: types.Message):
    motivations = [
        "Ты можешь больше, чем думаешь! 💪",
        "Каждый день — это новый шанс стать лучше! 🌟",
        "Не сдавайся! У тебя всё получится! 🚀",
        "Ты — звезда! Сияй ярче! ✨",
        "Маленькие шаги ведут к большим победам! 🏆",
        "Успех — это сумма маленьких усилий, повторяемых изо дня в день! 📈",
        "Верь в себя, и всё получится! 💫",
        "Ты на правильном пути! Продолжай в том же духе! 👍"
    ]
    motivation = random.choice(motivations)
    await send_video(message, "motivation", motivation)

# === Админские функции ===
@dp.message(F.text == "🏆 Рейтинг Сотрудников")
async def employee_rating(message: types.Message):
    if message.from_user.id not in ADMINS:
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Получаем рейтинг по количеству отчетов
            async with db.execute(
                """SELECT u.full_name, COUNT(r.id) as report_count 
                FROM users u LEFT JOIN reports r ON u.user_id = r.user_id 
                GROUP BY u.user_id 
                ORDER BY report_count DESC"""
            ) as cursor:
                rating = await cursor.fetchall()

        if not rating:
            await message.answer("📭 Нет данных для формирования рейтинга.")
            return

        response = "🏆 <b>Рейтинг сотрудников по количеству отчётов:</b>\n\n"
        for idx, (full_name, report_count) in enumerate(rating, start=1):
            response += f"{idx}. {full_name}: <b>{report_count}</b> отчётов\n"

        await message.answer(response)

    except Exception as e:
        logger.error(f"Ошибка получения рейтинга сотрудников: {e}")
        await message.answer("⚠ Произошла ошибка при формировании рейтинга. Попробуйте позже.")

@dp.message(F.text == "✅ Проверить Отчеты")
async def check_reports(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT id, full_name, photo_id, report_text, report_date 
                FROM reports 
                WHERE status = 'На проверке' AND report_date BETWEEN ? AND ? 
                ORDER BY report_date, full_name""",
                (start_date, end_date)
            ) as cursor:
                reports = await cursor.fetchall()

        if not reports:
            await message.answer("📭 Нет отчётов на проверку.")
            return

        await state.update_data(reports=reports, current_report=0)
        await show_report(message, state)

    except Exception as e:
        logger.error(f"Ошибка получения отчетов для проверки: {e}")
        await message.answer("⚠ Произошла ошибка при получении отчетов. Попробуйте позже.")

async def show_report(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reports = data.get("reports", [])
    current_report = data.get("current_report", 0)
    
    if current_report >= len(reports):
        await message.answer(
            "✅ Все отчеты проверены.", 
            reply_markup=get_main_keyboard(is_admin=True)
        )
        await state.clear()
        return
    
    report_id, full_name, photo_id, report_text, report_date = reports[current_report]
    
    caption = f"📝 <b>Отчёт от {full_name}</b>\n📅 <i>{report_date}</i>"
    if report_text:
        caption += f"\n\n{report_text}"
    
    try:
        if photo_id:
            await message.answer_photo(
                photo_id, 
                caption=caption,
                reply_markup=get_approval_keyboard()
            )
        else:
            await message.answer(
                caption,
                reply_markup=get_approval_keyboard()
            )
        
        await state.update_data(current_report_id=report_id)
    except Exception as e:
        logger.error(f"Ошибка показа отчета {report_id}: {e}")
        await message.answer(
            "⚠ Не удалось загрузить отчет. Пропускаем...",
            reply_markup=get_approval_keyboard()
        )
        await state.update_data(current_report=current_report + 1)
        await show_report(message, state)

@dp.message(F.text == "✅ Принять")
async def approve_report(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    data = await state.get_data()
    report_id = data.get("current_report_id")
    
    if not report_id:
        await message.answer("⚠ Ошибка: не найден текущий отчет.")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE reports SET status = 'Принят' WHERE id = ?",
                (report_id,)
            )
            await db.commit()

            # Получаем информацию о отчете для уведомления
            async with db.execute(
                "SELECT user_id, full_name, report_date FROM reports WHERE id = ?",
                (report_id,)
            ) as cursor:
                user_id, full_name, report_date = await cursor.fetchone()

        await message.answer("✅ Отчёт принят.")
        
        # Уведомление сотруднику
        try:
            await bot.send_message(
                user_id,
                f"✅ Ваш отчёт за {report_date} принят."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
        # Показываем следующий отчет
        await state.update_data(current_report=data.get("current_report", 0) + 1)
        await show_report(message, state)

    except Exception as e:
        logger.error(f"Ошибка принятия отчета {report_id}: {e}")
        await message.answer("⚠ Произошла ошибка при принятии отчета. Попробуйте позже.")

@dp.message(F.text == "🔄 Отправить на Доработку")
async def send_for_revision(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    await message.answer(
        "📝 Укажите причину для доработки:",
        reply_markup=get_back_only_keyboard()
    )
    await state.set_state("waiting_for_revision_reason")

@dp.message(F.text, StateFilter("waiting_for_revision_reason"))
async def process_revision_reason(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    if message.text == "🔙 Назад":
        await back_handler(message, state)
        return
    
    reason = message.text
    data = await state.get_data()
    report_id = data.get("current_report_id")
    
    if not report_id:
        await message.answer("⚠ Ошибка: не найден текущий отчет.")
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE reports SET status = 'На доработке' WHERE id = ?",
                (report_id,)
            )
            await db.commit()

            # Получаем информацию о отчете для уведомления
            async with db.execute(
                "SELECT user_id, full_name, report_date FROM reports WHERE id = ?",
                (report_id,)
            ) as cursor:
                user_id, full_name, report_date = await cursor.fetchone()

        await message.answer(
            "🔄 Отчёт отправлен на доработку.",
            reply_markup=get_approval_keyboard()
        )
        
        # Уведомление сотруднику
        try:
            await bot.send_message(
                user_id,
                f"🔄 Ваш отчёт за {report_date} отправлен на доработку.\n"
                f"<b>Причина:</b> {reason}"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
        # Показываем следующий отчет
        await state.update_data(current_report=data.get("current_report", 0) + 1)
        await show_report(message, state)

    except Exception as e:
        logger.error(f"Ошибка отправки отчета на доработку {report_id}: {e}")
        await message.answer(
            "⚠ Произошла ошибка при отправке на доработку. Попробуйте позже.",
            reply_markup=get_approval_keyboard()
        )

# === Запуск бота ===
async def main():
    await init_db()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Удаляем вебхук (если был)
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
