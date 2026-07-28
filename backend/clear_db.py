"""
Скрипт для полной очистки базы данных — удаляет все таблицы (Game, Finding) и создаёт их заново пустыми.

Использование:
    python3 backend/clear_db.py  (из корневой папки проекта)
  или:
    cd backend && python3 clear_db.py
"""
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import SQLModel
from database import engine, init_db
import models  # Импортируем модели, чтобы SQLModel.metadata знал про таблицы Game и Finding

def clear_database():
    print("⏳ Очистка базы данных...")
    SQLModel.metadata.drop_all(engine)
    init_db()
    print("✅ База данных успешно очищена и готова к работе.")

if __name__ == "__main__":
    clear_database()
