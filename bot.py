import asyncio
import logging
import aiosqlite
import aiocron
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
            [KeyboardButton(text="📌 Мои Задачи")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Посмотреть Отчеты")],
            [KeyboardButton(text="📌 Отправить Задачи")]
        ],
        resize_keyboard=True
    )

def get_report_period_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Текущая Неделя")],
            [KeyboardButton(text="📆 Выбрать Период")]
        ],
        resize_keyboard=True
    )

def get_task_type_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Основная Задача")],
            [KeyboardButton(text="📋 Дополнительная Задача")]
        ],
        resize_keyboard=True
    )

def get_approval_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Принять")],
            [KeyboardButton(text="🔄 Отправить на Доработку")]
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

# === Посмотреть Отчеты (Админ) ===
@dp.message(F.text == "📊 Посмотреть Отчеты")
async def view_reports(message: types.Message):
    if message.from_user.id not in ADMINS:
        return

    await message.answer("📊 Выберите период:", reply_markup=get_report_period_keyboard())

@dp.message(F.text == "📅 Текущая Неделя")
async def current_week_reports(message: types.Message):
    if message.from_user.id not in ADMINS:
        return

    start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")
    end_date = datetime.now().strftime("%d.%m.%Y")

    await send_reports(message, start_date, end_date)

@dp.message(F.text == "📆 Выбрать Период")
async def select_period_reports(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    await message.answer("📆 Введите период в формате: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ")
    await state.set_state("waiting_for_period")

@dp.message(F.text, StateFilter("waiting_for_period"))
async def process_period(message: types.Message, state: FSMContext):
    try:
        start_date, end_date = message.text.split(" - ")
        await send_reports(message, start_date, end_date)
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ")

async def send_reports(message: types.Message, start_date: str, end_date: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name, photo_id, report_text, report_date FROM reports WHERE report_date BETWEEN ? AND ? ORDER BY full_name",
            (start_date, end_date)
        ) as cursor:
            reports = await cursor.fetchall()

    if not reports:
        await message.answer(f"📭 Нет отчётов за период {start_date} - {end_date}.")
        return

    grouped_reports = {}
    for full_name, photo_id, report_text, report_date in reports:
        if full_name not in grouped_reports:
            grouped_reports[full_name] = []
        entry = f"📅 {report_date}"
        if report_text:
            entry += f"\n📝 {report_text}"
        grouped_reports[full_name].append((entry, photo_id))

    for full_name, entries in grouped_reports.items():
        caption = f"👤 {full_name}\n📊 Отчёты за {start_date} - {end_date}:\n"
        for entry, photo_id in entries:
            if photo_id:
                await bot.send_photo(message.chat.id, photo=photo_id, caption=entry)
            else:
                caption += f"\n{entry}\n"
        if caption.strip():
            await message.answer(caption)

# === Отправить Задачи (Админ) ===
@dp.message(F.text == "📌 Отправить Задачи")
async def send_tasks(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    await message.answer("📌 Выберите тип задачи:", reply_markup=get_task_type_keyboard())
    await state.set_state("waiting_for_task_type")

@dp.message(F.text, StateFilter("waiting_for_task_type"))
async def select_task_type(message: types.Message, state: FSMContext):
    task_type = message.text
    await state.update_data(task_type=task_type)
    await message.answer("📝 Введите текст задачи:")
    await state.set_state("waiting_for_task_text")

@dp.message(F.text, StateFilter("waiting_for_task_text"))
async def select_task_text(message: types.Message, state: FSMContext):
    task_text = message.text
    data = await state.get_data()
    task_type = data["task_type"]

    employees = await get_employees()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=full_name)] for _, full_name, _ in employees],
        resize_keyboard=True
    )
    await message.answer("👤 Выберите сотрудника:", reply_markup=keyboard)
    await state.update_data(task_text=task_text, task_type=task_type)
    await state.set_state("waiting_for_employee")

@dp.message(F.text, StateFilter("waiting_for_employee"))
async def assign_task(message: types.Message, state: FSMContext):
    full_name = message.text
    data = await state.get_data()
    task_type = data["task_type"]
    task_text = data["task_text"]

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE full_name = ?", (full_name,)) as cursor:
            user_id = (await cursor.fetchone())[0]

        await db.execute(
            "INSERT INTO tasks (user_id, task_type, task_text, task_date) VALUES (?, ?, ?, ?)",
            (user_id, task_type, task_text, datetime.now().strftime("%d.%m.%Y"))
        )
        await db.commit()

    await message.answer(f"✅ Задача успешно назначена сотруднику {full_name}.", reply_markup=get_admin_keyboard())
    await state.clear()

# === Запуск бота ===
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
