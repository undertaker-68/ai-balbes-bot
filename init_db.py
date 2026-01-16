import psycopg2
import os

# Загружаем параметры из .env
from dotenv import load_dotenv
load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# Подключение к базе данных PostgreSQL
conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT
)

# Создание курсора для выполнения SQL-запросов
cursor = conn.cursor()

# Создаём таблицу для хранения сообщений
cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        message_id SERIAL PRIMARY KEY,
        user_id INT NOT NULL,
        text TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")

# Создаём таблицу для пользователей
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INT PRIMARY KEY,
        username TEXT,
        role TEXT
    );
""")

# Создаём таблицу для векторных эмбеддингов
cursor.execute("""
    CREATE TABLE IF NOT EXISTS embeddings (
        message_id INT PRIMARY KEY,
        embedding VECTOR(1536) -- Размер вектора для OpenAI Embeddings
    );
""")

# Сохраняем изменения и закрываем соединение
conn.commit()
cursor.close()
conn.close()

print("Database tables created successfully!")
