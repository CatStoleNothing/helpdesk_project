import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Пути к базам данных
user_db_path = 'users.db'

def create_fresh_users_db():
    """Создает новую базу данных users.db с таблицей users"""
    # Удаляем существующую базу данных, если она существует
    if os.path.exists(user_db_path):
        os.remove(user_db_path)
        logger.info(f"Удалена существующая база данных {user_db_path}")

    try:
        # Создаем новую базу данных
        conn = sqlite3.connect(user_db_path)
        cursor = conn.cursor()

        # Создаем таблицу users
        logger.info("Создание таблицы users...")
        cursor.execute("""
            CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE,
            password_hash VARCHAR(100),
            full_name VARCHAR(100) NOT NULL,
            position VARCHAR(100),
            department VARCHAR(100),
            office VARCHAR(100),
            phone VARCHAR(20),
            email VARCHAR(100),
            privacy_consent BOOLEAN DEFAULT FALSE,
            consent_date TIMESTAMP,
            is_archived BOOLEAN DEFAULT FALSE,
            is_confirmed BOOLEAN DEFAULT FALSE,
            chat_id VARCHAR(50) UNIQUE NOT NULL,
            role VARCHAR(20) DEFAULT 'agent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
            )
        """)

        conn.commit()

        # Проверяем, что таблицы созданы
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        logger.info(f"Созданы таблицы: {[t[0] for t in tables]}")

        conn.close()
        logger.info(f"База данных {user_db_path} успешно создана!")
        return True

    except Exception as e:
        logger.error(f"Ошибка при создании базы данных: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Начало создания новой базы данных пользователей...")
    if create_fresh_users_db():
        print("База данных пользователей успешно создана!")
    else:
        print("Ошибка при создании базы данных пользователей. Проверьте логи.")
