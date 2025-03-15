import asyncio
import logging
import aiosqlite
import aiocron
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
TOKEN = getenv("BOT_TOKEN")
ADMINS = list(map(int, getenv("ADMINS", "").split(","))) if getenv("ADMINS") else []
DB_PATH = getenv("DB_PATH", "reports.db")
EMPLOYEE_CODE = getenv("EMPLOYEE_CODE")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL
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
        await db.commit()

@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    full_name = message.from_user.full_name

    if user_id in ADMINS:
        await message.answer(f"👋 Добро пожаловать, админ {full_name}!\n\nВы можете использовать команду:\n📊 /admin_reports — Просмотр отчётов.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

    if user:
        await message.answer(f"✅ Привет, {user[0]}! Используйте /отчет для отправки отчёта.")
    else:
        await message.answer("🔒 Введите код сотрудника для регистрации:")
        await state.set_state("waiting_for_code")

@dp.message(state="waiting_for_code")
async def process_registration_code(message: types.Message, state: FSMContext):
    if message.text == EMPLOYEE_CODE:
        user_id = message.from_user.id
        full_name = message.from_user.full_name

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO users (user_id, full_name) VALUES (?, ?)", (user_id, full_name))
            await db.commit()

        await message.answer(f"✅ Добро пожаловать, {full_name}!\n\nВы можете использовать команду:\n📝 /отчет — Отправить отчёт")
        await state.clear()
    else:
        await message.answer("❌ Неверный код сотрудника. Попробуйте ещё раз.")

async def is_registered(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

@dp.message(Command("отчет"))
async def start_report(message: types.Message, state: FSMContext):
    if await is_registered(message.from_user.id):
        await message.answer("📸 Отправьте фото задания или просто напишите текст отчёта:")
        await state.set_state("waiting_for_photo_or_text")
    else:
        await message.answer("🚫 Вы не зарегистрированы. Введите /start и пройдите регистрацию.")

@dp.message(state="waiting_for_photo_or_text", F.photo)
async def receive_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("✍ Напишите описание задания (или отправьте без текста):")
    await state.set_state("waiting_for_text")

@dp.message(state="waiting_for_text", F.text)
@dp.message(state="waiting_for_photo_or_text", F.text)
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

    await message.answer("✅ Ваш отчёт сохранён.")
    await state.clear()

@dp.message(Command("admin_reports"))
async def send_reports_now(message: types.Message):
    if message.from_user.id not in ADMINS:
        return

    start_of_week = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name, photo_id, report_text, report_date FROM reports WHERE report_date >= ?", (start_of_week,)
        ) as cursor:
            reports = await cursor.fetchall()

    if not reports:
        await message.answer("📭 Нет отчётов за эту неделю.")
        return

    for report in reports:
        full_name, photo_id, report_text, report_date = report
        caption = f"👤 {full_name}\n📅 {report_date}"
        if report_text:
            caption += f"\n📝 {report_text}"

        if photo_id:
            await bot.send_photo(message.chat.id, photo=photo_id, caption=caption)
        else:
            await message.answer(caption)

@aiocron.crontab("0 0 * * 0")
async def scheduled_reports():
    start_of_week = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%Y")

    for admin_id in ADMINS:
        await bot.send_message(admin_id, f"📊 Еженедельный отчёт: /admin_reports с {start_of_week}")

# === Запуск бота ===
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
