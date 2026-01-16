import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode
import openai
import os

# Загружаем конфигурацию из .env
from dotenv import load_dotenv
load_dotenv()

# Инициализируем бота
API_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Настройка OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

# Устанавливаем логирование
logging.basicConfig(level=logging.INFO)

# Команда /start
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer("Привет! Я твой токсичный ИИ-бот.")

# Простой обработчик для текста
@dp.message_handler(content_types=["text"])
async def text_handler(message: types.Message):
    user_id = message.from_user.id

    # Для начала будем проверять, если это тот человек, чьим стилем должен быть бот
    if user_id == int(os.getenv('MASTER_STYLE_ID')):
        # Имитация токсичного стиля
        prompt = f"Ты токсичный человек с ID {user_id}. Ответь жестко, саркастично и оскорбительно. Сообщение: {message.text}"
    else:
        # Ответ от бота в нейтральном стиле
        prompt = f"Ответь на сообщение {message.text} в обычном тоне."

    # Запрос к OpenAI
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt=prompt,
        max_tokens=150
    )

    # Отправляем ответ в чат
    await message.answer(response.choices[0].text.strip())

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp)
