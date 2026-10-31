"""Тести не ходять у мережу й не пишуть у робочу БД: порожній ключ блокує підхоплення GEMINI_API_KEY з .env
(load_dotenv не перезаписує вже задані змінні), тож seed при імпорті app.main іде на правилах."""
import os

os.environ["GEMINI_API_KEY"] = ""
os.environ["DB_PATH"] = ":memory:"  # тести не чіпають робочу базу data/learnly.db
