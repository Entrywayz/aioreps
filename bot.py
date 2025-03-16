import asyncio
import logging
import aiosqlite
import aiocron
import random
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
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
            [KeyboardButton(text="🔙 Назад")]
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
    await message.answer("📸 Отправьте фото задания или просто напишите текст отчёта:")
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
            "INSERT INTO reports (user_id, full_name, photo_id, report_text, report_date) VALUES (?, ?, ?, ?, ?)",
            (user_id, full_name, photo_id, report_text, today)
        )
        await db.commit()

    await message.answer("✅ Ваш отчёт сохранён.", reply_markup=get_employee_keyboard())
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
            "SELECT report_date, report_text FROM reports WHERE user_id = ? AND report_date BETWEEN ? AND ?",
            (user_id, start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()

    if not reports:
        await message.answer("📭 У вас нет отчётов за текущую неделю.")
        return

    response = "📊 Ваши отчёты за текущую неделю:\n"
    for report_date, report_text in reports:
        response += f"📅 {report_date}\n📝 {report_text}\n\n"

    await message.answer(response)

# === Личный Кабинет ===
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

    response = (
        f"👤 Личный Кабинет\n"
        f"📊 Ваша статистика за текущую неделю:\n"
        f"✅ Сдано отчётов: {submitted}\n"
        f"❌ Пропущено отчётов: {missed}"
    )
    await message.answer(response)

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
        await message.answer("📭 У вас нет новых задач.")
        return

    response = "📌 Ваши задачи:\n"
    for task_type, task_text, task_date in tasks:
        response += f"📅 {task_date}\n📋 {task_type}: {task_text}\n\n"

    await message.answer(response)

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
    await message.answer(motivation)

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

# === Кнопка "Назад" ===
@dp.message(F.text == "🔙 Назад")
async def back_button(message: types.Message):
    user_id = message.from_user.id

    if user_id in ADMINS:
        await message.answer("Возвращаемся в главное меню.", reply_markup=get_admin_keyboard())
    else:
        await message.answer("Возвращаемся в главное меню.", reply_markup=get_employee_keyboard())

# === Запуск бота ===
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
