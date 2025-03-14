import asyncio
import aiocron
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from config_reader import config

TOKEN = config.bot_token.get_secret_value()
ADMINS = [config.admin_id1.get_secret_value(), config.admin_id2.get_secret_value()]
EMPLOYEE_CODES = config.employee_codes.get_secret_value()
DB_PATH = "reports.db"

bot = Bot(token=config.bot_token.get_secret_value())
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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
                report_text TEXT NOT NULL,
                report_date TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")
        await db.commit()

@dp.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

    if user:
        await message.answer(f"✅ Вы уже зарегистрированы как {user[0]}. Используйте /отчет.")
    else:
        await message.answer("🔒 Введите ваш код сотрудника для регистрации:")
        await state.set_state(RegistrationState.waiting_for_code)

class RegistrationState(StatesGroup):
    waiting_for_code = State()

@dp.message(RegistrationState.waiting_for_code)
async def process_registration_code(message: Message, state: FSMContext):
    if message.text in EMPLOYEE_CODES:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO users (user_id, full_name) VALUES (?, ?)",
                (message.from_user.id, message.from_user.full_name),
            )
            await db.commit()

        await message.answer("✅ Вы успешно зарегистрированы! Теперь вы можете отправлять отчёты с /отчет.")
        await state.clear()
    else:
        await message.answer("❌ Неверный код сотрудника. Попробуйте ещё раз.")

async def is_registered(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

class ReportState(StatesGroup):
    writing = State()

@dp.message(Command("отчет"))
async def start_report(message: Message, state: FSMContext):
    if await is_registered(message.from_user.id):
        await message.answer("📝 Введите ваш отчёт за сегодня:")
        await state.set_state(ReportState.writing)
    else:
        await message.answer("🚫 Вы не зарегистрированы. Введите /start и пройдите регистрацию.")

@dp.message(ReportState.writing)
async def collect_report(message: Message, state: FSMContext):
    today = datetime.now().strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports (user_id, report_text, report_date) VALUES (?, ?, ?)",
            (message.from_user.id, message.text, today),
        )
        await db.commit()

    await message.answer("✅ Ваш отчёт сохранён.")
    await state.clear()

@dp.message(Command("admin_reports"))
async def send_reports_now(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer("🚫 У вас нет доступа.")
        return

    args = message.text.split()
    target_date = datetime.now()

    if len(args) >= 2:
        try:
            target_date = datetime.strptime(args[1], "%Y-%m-%d")
        except ValueError:
            await message.answer("❌ Неверный формат даты. Используйте YYYY-MM-DD.")
            return

    report_text = await format_reports(target_date)
    await message.answer(report_text if report_text else "❌ Нет отчётов за этот период.", parse_mode="HTML")

async def format_reports(date: datetime):
    start_of_week = date - timedelta(days=date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    start_str = start_of_week.strftime("%Y-%m-%d")
    end_str = end_of_week.strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT u.full_name, r.report_text, r.report_date 
               FROM reports r 
               JOIN users u ON r.user_id = u.user_id 
               WHERE r.report_date BETWEEN ? AND ? 
               ORDER BY u.full_name, r.report_date""",
            (start_str, end_str),
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return None

    reports_by_user = {}
    for full_name, report_text, report_date in rows:
        if full_name not in reports_by_user:
            reports_by_user[full_name] = {}
        if report_date not in reports_by_user[full_name]:
            reports_by_user[full_name][report_date] = []
        reports_by_user[full_name][report_date].append(report_text)

    report_lines = []
    for full_name, dates in reports_by_user.items():
        user_lines = [f"👤 <b>{full_name}</b>"]
        for date in sorted(dates.keys()):
            reports = dates[date]
            date_reports = "\n".join([f"  ◦ {report}" for report in reports])
            user_lines.append(f"📅 <i>{date}</i>:\n{date_reports}")
        report_lines.append("\n".join(user_lines))

    return "\n\n".join(report_lines)

async def schedule_cron_jobs():
    @aiocron.crontab("0 0 * * 0")
    async def weekly_report_cron():
        now = datetime.now()
        report_text = await format_reports(now)
        for admin_id in ADMINS:
            await bot.send_message(
                admin_id, 
                report_text if report_text else "Нет отчетов за прошедшую неделю.",
                parse_mode="HTML"
            )

async def main():
    await init_db()
    await schedule_cron_jobs()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
