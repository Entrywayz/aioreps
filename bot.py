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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# === Загрузка переменных окружения ===
load_dotenv()
TOKEN = getenv("BOT_TOKEN")
ADMINS = list(map(int, getenv("ADMINS", "").split(","))) if getenv("ADMINS") else []
DB_PATH = getenv("DB_PATH", "reports.db")
EMPLOYEE_CODE = str(getenv("EMPLOYEE_CODE"))  # Убедимся, что это строка

# Логирование для проверки
logging.info(f"Код сотрудника из .env: {EMPLOYEE_CODE}")

# === Настройка логирования ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Инициализация бота ===
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

VIDEO_FILES = {
    "personal_cabinet": "lc.mp4",
    "my_reports": "reports.mp4",
    "reports": "report.mp4",
    "tasks": "tasks.mp4",
    "motivation": "motivation.mp4"
}

async def send_video(message: types.Message, video_key: str, caption: str = "") -> bool:
    """
    Отправляет видео из локального файла
    :param message: Объект сообщения aiogram
    :param video_key: Ключ из словаря VIDEO_FILES
    :param caption: Подпись к видео
    :return: True если отправка успешна, False если возникла ошибка
    """
    try:
        # Получаем путь к текущей директории
        current_dir = Path(__file__).parent
        video_filename = VIDEO_FILES.get(video_key)
        if not video_filename:
            logging.error(f"Неизвестный ключ видео: {video_key}")
            return False
        
        video_path = current_dir / video_filename
        if not video_path.exists():
            logging.error(f"Видео файл не найден: {video_path}")
            await message.answer("⚠ Видео временно недоступно")
            return False
        
        # Используем FSInputFile для локальных файлов
        video = FSInputFile(path=str(video_path))
        
        # Отправляем видео с использованием reply_markup=None
        await message.answer_video(video=video, caption=caption, supports_streaming=True)
        return True
    
    except Exception as e:
        logging.error(f"Ошибка при отправке видео {video_key}: {str(e)}")
        await message.answer(f"⚠ Не удалось отправить видео. {caption}")
        return False


# === Клавиатуры ===
def get_employee_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Отправить Отчет")],
            [KeyboardButton(text="📊 Мои Отчеты")],
            [KeyboardButton(text="👤 Личный Кабинет")],
            [KeyboardButton(text="📌 Мои Задачи")],
            [KeyboardButton(text="💪 Мотивация")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Посмотреть Отчеты")],
            [KeyboardButton(text="📌 Отправить Задачи")],
            [KeyboardButton(text="🏆 Рейтинг Сотрудников")],
            [KeyboardButton(text="✅ Проверить Отчеты")]
        ],
        resize_keyboard=True
    )

def get_report_period_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Текущая Неделя")],
            [KeyboardButton(text="📆 Выбрать Период")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

VIDEO_MESSAGES = {
    "personal_cabinet": "lc.mp4",
    "my_reports": "reports.mp4",
    "reports": "report.mp4",
    "tasks": "tasks.mp4",
    "motivation": "motivation.mp4"
}

def get_task_type_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Основная Задача")],
            [KeyboardButton(text="📋 Дополнительная Задача")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_approval_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Принять")],
            [KeyboardButton(text="🔄 Отправить на Доработку")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

# === Инициализация базы данных ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                position TEXT NOT NULL DEFAULT 'Сотрудник'
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
                status TEXT NOT NULL DEFAULT 'Новая',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")
        await db.commit()

# === Функция получения списка сотрудников ===
async def get_employees():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, full_name, position FROM users") as cursor:
            employees = await cursor.fetchall()
    return employees

# === Команда /start ===
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    full_name = message.from_user.full_name

    logging.info(f"Пользователь {full_name} (ID: {user_id}) нажал /start")

    if user_id in ADMINS:
        await message.answer(f"👋 Добро пожаловать, админ {full_name}!", reply_markup=get_admin_keyboard())
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

    if user:
        await message.answer(f"✅ Привет, {user[0]}!", reply_markup=get_employee_keyboard())
    else:
        await message.answer("🔒 Введите код сотрудника для регистрации:")
        await state.set_state("waiting_for_code")

# === Регистрация сотрудника ===
@dp.message(F.text, StateFilter("waiting_for_code"))
async def process_registration_code(message: types.Message, state: FSMContext):
    user_input = message.text.strip()  # Убираем лишние пробелы
    if user_input == EMPLOYEE_CODE:  # Сравниваем с кодом из .env
        user_id = message.from_user.id
        full_name = message.from_user.full_name

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO users (user_id, full_name) VALUES (?, ?)", (user_id, full_name))
            await db.commit()

        await message.answer(f"✅ Добро пожаловать, {full_name}!", reply_markup=get_employee_keyboard())
        await state.clear()  # Очищаем состояние
    else:
        await message.answer("❌ Неверный код сотрудника. Попробуйте ещё раз.")

# === Отправить Отчет ===
@dp.message(F.text == "📝 Отправить Отчет")
async def send_report(message: types.Message, state: FSMContext):
    res = "📸 Отправьте фото задания или просто напишите текст отчёта:"
    await send_video(message, "reports", res)
    await state.set_state("waiting_for_photo_or_text")

@dp.message(F.photo, StateFilter("waiting_for_photo_or_text"))
async def receive_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("✍ Напишите описание задания (или отправьте без текста):")
    await state.set_state("waiting_for_text")

@dp.message(F.text, StateFilter("waiting_for_text", "waiting_for_photo_or_text"))
async def receive_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = data.get('photo_id')
    report_text = message.text
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    today = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports (user_id, full_name, photo_id, report_text, report_date, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, full_name, photo_id, report_text, today, "На проверке")
        )
        await db.commit()

    await message.answer("✅ Ваш отчёт сохранён и отправлен на проверку.", reply_markup=get_employee_keyboard())
    await state.clear()

    # Уведомление админам о новом отчете
    for admin_id in ADMINS:
        await bot.send_message(admin_id, f"📥 Новый отчёт от {full_name}.\n📅 Дата: {today}")

# === Мои Отчеты ===
@dp.message(F.text == "📊 Мои Отчеты")
async def my_reports(message: types.Message):
    user_id = message.from_user.id
    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT report_date, report_text, status FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ?",
            (user_id, start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()

    if not reports:
        resp = "📭 У вас нет отчётов за текущую неделю."
        await send_video(message, "reports", resp)
        return

    response = "📊 Ваши отчёты за текущую неделю:\n"
    for report_date, report_text, status in reports:
        response += f"📅 {report_date}\n📝 {report_text}\n🔄 Статус: {status}\n\n"

    await send_video(message, "reports", response)

@dp.message(F.text == "👤 Личный Кабинет")
async def personal_cabinet(message: types.Message):
    user_id = message.from_user.id
    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ?",
            (user_id, start_date, end_date)
        ) as cursor:
            submitted = (await cursor.fetchone())[0]

        start = datetime.strptime(start_date, "%d.%m.%Y")
        end = datetime.strptime(end_date, "%d.%m.%Y")
        total_days = (end - start).days + 1
        missed = total_days - submitted

    caption = (
        f"👤 Личный Кабинет\n"
        f"📊 Ваша статистика за текущую неделю:\n"
        f"✅ Сдано отчётов: {submitted}\n"
        f"❌ Пропущено отчётов: {missed}"
    )
    
    # Отправляем видео
    await send_video(message, "personal_cabinet", caption)

# === Мои Задачи ===
@dp.message(F.text == "📌 Мои Задачи")
async def my_tasks(message: types.Message):
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT task_type, task_text, task_date FROM tasks WHERE user_id = ? AND status = 'Новая'",
            (user_id,)
        ) as cursor:
            tasks = await cursor.fetchall()

    if not tasks:
        resp = "📭 У вас нет новых задач."
        await send_video(message, "tasks", resp)
        return

    response = "📌 Ваши задачи:\n"
    for task_type, task_text, task_date in tasks:
        response += f"📅 {task_date}\n📋 {task_type}: {task_text}\n\n"

    
    await send_video(message, "tasks", response)

# === Мотивация ===
@dp.message(F.text == "💪 Мотивация")
async def send_motivation(message: types.Message):
    motivations = [
        "Ты можешь больше, чем думаешь! 💪",
        "Каждый день — это новый шанс стать лучше! 🌟",
        "Не сдавайся! У тебя всё получится! 🚀",
        "Ты — звезда! Сияй ярче! ✨",
        "Маленькие шаги ведут к большим победам! 🏆"
    ]
    motivation = random.choice(motivations)
    await send_video(message, "motivation", motivation)

# === Рейтинг Сотрудников (Админ) ===
@dp.message(F.text == "🏆 Рейтинг Сотрудников")
async def employee_rating(message: types.Message):
    if message.from_user.id not in ADMINS:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name, COUNT(*) as report_count FROM reports GROUP BY user_id ORDER BY report_count DESC"
        ) as cursor:
            rating = await cursor.fetchall()

    if not rating:
        await message.answer("📭 Нет данных для формирования рейтинга.")
        return

    response = "🏆 Рейтинг сотрудников по количеству отчётов:\n"
    for idx, (full_name, report_count) in enumerate(rating, start=1):
        response += f"{idx}. {full_name}: {report_count} отчётов\n"

    await message.answer(response)

# === Проверить Отчеты (Админ) ===
@dp.message(F.text == "✅ Проверить Отчеты")
async def check_reports(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, full_name, photo_id, report_text, report_date FROM reports WHERE status = 'На проверке' AND report_date BETWEEN ? AND ? ORDER BY full_name",
            (start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()

    if not reports:
        await message.answer("📭 Нет отчётов на проверку.")
        return

    # Сохраняем отчеты в состояние для дальнейшей обработки
    await state.update_data(reports=reports)
    await message.answer("📊 Отчёты на проверку:", reply_markup=get_approval_keyboard())

# === Обработка кнопок "Принять" и "Отправить на доработку" ===
@dp.message(F.text == "✅ Принять")
async def approve_report(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reports = data.get("reports", [])

    if not reports:
        await message.answer("📭 Нет отчётов на проверку.")
        return

    report_id, full_name, photo_id, report_text, report_date = reports[0]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE reports SET status = 'Принят' WHERE id = ?",
            (report_id,)
        )
        await db.commit()

    await message.answer(f"✅ Отчёт от {full_name} за {report_date} принят.")
    await state.clear()

    # Уведомление сотруднику
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM reports WHERE id = ?", (report_id,)) as cursor:
            user_id = (await cursor.fetchone())[0]

    await bot.send_message(user_id, f"✅ Ваш отчёт за {report_date} принят.")

@dp.message(F.text == "🔄 Отправить на Доработку")
async def send_for_revision(message: types.Message, state: FSMContext):
    await message.answer("📝 Укажите причину для доработки:")
    await state.set_state("waiting_for_revision_reason")

@dp.message(F.text, StateFilter("waiting_for_revision_reason"))
async def process_revision_reason(message: types.Message, state: FSMContext):
    reason = message.text
    data = await state.get_data()
    reports = data.get("reports", [])

    if not reports:
        await message.answer("📭 Нет отчётов на проверку.")
        return

    report_id, full_name, photo_id, report_text, report_date = reports[0]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE reports SET status = 'На доработке' WHERE id = ?",
            (report_id,)
        )
        await db.commit()

    await message.answer(f"🔄 Отчёт от {full_name} за {report_date} отправлен на доработку.")
    await state.clear()

    # Уведомление сотруднику
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM reports WHERE id = ?", (report_id,)) as cursor:
            user_id = (await cursor.fetchone())[0]

    await bot.send_message(user_id, f"🔄 Ваш отчёт за {report_date} отправлен на доработку. Причина: {reason}")

# === Запуск бота ===
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
