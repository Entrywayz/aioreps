import asyncio
import logging
import aiosqlite
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# === Загрузка переменных окружения ===
load_dotenv()
TOKEN = getenv("BOT_TOKEN")
ADMINS = list(map(int, getenv("ADMINS", "").split(","))) if getenv("ADMINS") else []
DB_PATH = getenv("DB_PATH", "reports.db")
EMPLOYEE_CODE = str(getenv("EMPLOYEE_CODE"))

# Словарь с video file_id
VIDEO_MESSAGES = {
    "personal_cabinet": "lc.mp4",
    "my_reports": "reports.mp4",
    "reports": "report.mp4",
    "tasks": "tasks.mp4",
    "motivation": "motivation.mp4"
}

# === Инициализация бота ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

# === Клавиатуры ===
def get_employee_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Отправить Отчет")],
            [KeyboardButton(text="📊 Мои Отчеты")],
            [KeyboardButton(text="👤 Личный Кабинет")],
            [KeyboardButton(text="📌 Мои Задачи")],
            [KeyboardButton(text="💪 Мотивация")]
        ],
        resize_keyboard=True
    )

# === Команда /start ===
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    
    if user_id in ADMINS:
        await message.answer(f"👋 Добро пожаловать, админ {full_name}!")
        return
        
    await message.answer(f"✅ Привет, {full_name}!", reply_markup=get_employee_keyboard())

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
        
        total_days = (datetime.strptime(end_date, "%d.%m.%Y") - 
                      datetime.strptime(start_date, "%d.%m.%Y")).days + 1
        missed = total_days - submitted
    
    caption = (
        f"👤 Личный Кабинет\n\n"
        f"📊 Ваша статистика за текущую неделю:\n\n"
        f"✅ Сдано отчётов: {submitted}\n\n"
        f"❌ Пропущено отчётов: {missed}"
    )
    await message.answer_video(video=VIDEO_MESSAGES["personal_cabinet"], caption=caption)

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
        caption = "📭 У вас нет отчётов за текущую неделю."
    else:
        caption = "📊 Ваши отчёты за текущую неделю:\n"
        for report_date, report_text, status in reports:
            caption += f"📅 {report_date}\n📝 {report_text}\n🔄 Статус: {status}\n\n"
    
    await message.answer_video(video=VIDEO_MESSAGES["my_reports"], caption=caption)

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
        caption = "📭 У вас нет новых задач."
    else:
        caption = "📌 Ваши задачи:\n"
        for task_type, task_text, task_date in tasks:
            caption += f"📅 {task_date}\n📋 {task_type}: {task_text}\n\n"
    
    await message.answer_video(video=VIDEO_MESSAGES["tasks"], caption=caption)

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
    
    await message.answer_video(video=VIDEO_MESSAGES["motivation"], caption=motivation)

# === Запуск бота ===
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
