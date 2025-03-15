import asyncio
import logging
import aiosqlite
import aiocron
from datetime import datetime
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters.state import StateFilter

# Загрузка переменных окружения
load_dotenv()
EMPLOYEE_CODES = getenv("EMPLOYEE_CODES").split(",")  # Коды сотрудников
TOKEN = getenv("BOT_TOKEN")  # Токен бота
ADMINS = list(map(int, getenv("ADMINS", "").split(","))) if getenv("ADMINS") else []  # ID админов
DB_PATH = getenv("DB_PATH", "reports.db")  # Путь к базе данных

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === Инициализация базы данных ===
async def init_db():
    logging.info("Инициализация базы данных...")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")  # Включаем поддержку внешних ключей
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
    logging.info("База данных успешно инициализирована.")


# === Команда /start ===
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

    if user:
        await message.answer(f"✅ Вы уже зарегистрированы как {user[0]}. Используйте /отчет.")
    else:
        await message.answer("🔒 Введите ваш код сотрудника для регистрации:")
        await state.set_state("waiting_for_code")


# === Обработка кода сотрудника ===
@dp.message(StateFilter("waiting_for_code"))
async def process_registration_code(message: types.Message, state: FSMContext):
    if message.text in EMPLOYEE_CODES:
        await message.answer("📝 Введите ваше полное имя для регистрации:")
        await state.set_state("waiting_for_name")
    else:
        await message.answer("❌ Неверный код сотрудника. Попробуйте ещё раз.")


# === Обработка имени пользователя ===
@dp.message(StateFilter("waiting_for_name"))
async def process_registration_name(message: types.Message, state: FSMContext):
    full_name = message.text
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (user_id, full_name) VALUES (?, ?)", 
                         (message.from_user.id, full_name))
        await db.commit()
    await message.answer(f"✅ Регистрация завершена, {full_name}! Используйте /отчет.")
    await state.clear()


# === Проверка регистрации пользователя ===
async def is_registered(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None


# === Состояния для отчетов ===
class ReportState(StatesGroup):
    waiting_for_photo_or_text = State()
    waiting_for_text = State()


# === Команда /отчет ===
@dp.message(Command("отчет"))
async def start_report(message: types.Message, state: FSMContext):
    if await is_registered(message.from_user.id):
        await message.answer("📸 Отправьте фото задания или просто напишите текст отчёта:")
        await state.set_state(ReportState.waiting_for_photo_or_text)
    else:
        await message.answer("🚫 Вы не зарегистрированы. Введите /start и пройдите регистрацию.")


# === Обработка фото в отчете ===
@dp.message(ReportState.waiting_for_photo_or_text, F.photo)
async def receive_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("✍️ Теперь напишите описание задания (или отправьте без текста):")
    await state.set_state(ReportState.waiting_for_text)


# === Обработка текста в отчете ===
@dp.message(ReportState.waiting_for_text, F.text)
@dp.message(ReportState.waiting_for_photo_or_text, F.text)
async def receive_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = data.get('photo_id')
    report_text = message.text
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    full_name = user[0] if user else "Неизвестный пользователь"
    today = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports (user_id, full_name, photo_id, report_text, report_date) VALUES (?, ?, ?, ?, ?)",
            (user_id, full_name, photo_id, report_text, today)
        )
        await db.commit()

    logging.info(f"Пользователь {user_id} отправил отчёт за {today}.")
    await message.answer("✅ Ваш отчёт сохранён.")
    await state.clear()


# === Команда /admin_reports ===
@dp.message(Command("admin_reports"))
async def send_reports_now(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("🚫 У вас нет доступа.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, photo_id, report_text, report_date FROM reports") as cursor:
            reports = await cursor.fetchall()

    if not reports:
        await message.answer("📭 Нет отчётов.")
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


# === Автоматическая отправка отчетов по воскресеньям ===
@aiocron.crontab("0 0 * * 0")  # Каждое воскресенье в 00:00
async def scheduled_reports():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, photo_id, report_text, report_date FROM reports") as cursor:
            reports = await cursor.fetchall()

    if not reports:
        return

    for admin_id in ADMINS:
        for report in reports:
            full_name, photo_id, report_text, report_date = report
            caption = f"👤 {full_name}\n📅 {report_date}"
            if report_text:
                caption += f"\n📝 {report_text}"
            
            try:
                if photo_id:
                    await bot.send_photo(admin_id, photo=photo_id, caption=caption)
                else:
                    await bot.send_message(admin_id, caption)
                await asyncio.sleep(0.5)  # Задержка между сообщениями
            except Exception as e:
                logging.error(f"Ошибка отправки отчета админу {admin_id}: {e}")


# === Запуск бота ===
async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
