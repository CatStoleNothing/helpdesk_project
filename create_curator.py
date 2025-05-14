#!/usr/bin/env python3
"""
Скрипт для создания куратора SNA с паролем 123
Можно указать chat_id через аргумент командной строки, например:
python create_curator.py 864823503
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

from models.db_init import init_db, SessionLocal
from models.user_models import User

def create_curator(chat_id=None):
    """Создание куратора SNA с указанным chat_id или значением по умолчанию"""
    # Инициализация БД если еще не инициализирована
    init_db()

    # Если chat_id не передан, используем значение по умолчанию
    if chat_id is None:
        chat_id = "864823503"  # Значение по умолчанию

    user_db = SessionLocal()
    try:
        # Проверяем, существует ли уже пользователь SNA
        existing_user = user_db.query(User).filter(User.username == "SNA").first()

        if existing_user:
            logger.warning("Пользователь SNA уже существует в системе!")

            # Если пользователь существует, но chat_id отличается, предлагаем обновить
            if existing_user.chat_id != chat_id:
                logger.warning(f"У существующего пользователя SNA указан другой chat_id: {existing_user.chat_id}")
                logger.warning(f"Для обновления chat_id на {chat_id}, используйте параметр --force")

                # Если указан флаг --force, обновляем chat_id
                if "--force" in sys.argv:
                    old_chat_id = existing_user.chat_id
                    existing_user.chat_id = chat_id
                    user_db.commit()
                    logger.info(f"Chat ID пользователя SNA обновлен с {old_chat_id} на {chat_id}")

            return False

        # Проверяем, существует ли уже пользователь с таким chat_id
        existing_chat_id = user_db.query(User).filter(User.chat_id == chat_id).first()
        if existing_chat_id:
            logger.warning(f"Пользователь с chat_id {chat_id} уже существует: {existing_chat_id.full_name}")
            logger.warning("Укажите другой chat_id или удалите существующего пользователя.")
            return False

        # Создаем куратора
        curator_password = "123"

        curator = User(
            username="SNA",
            password_hash=User.get_password_hash(curator_password),
            full_name="",
            position="",
            department="",
            office="",
            role="curator",  # Роль куратора
            is_confirmed=True,
            is_active=True,
            chat_id=chat_id
        )

        user_db.add(curator)
        user_db.commit()

        logger.info(f"Куратор SNA успешно создан с логином 'SNA', паролем '{curator_password}' и chat_id '{chat_id}'")
        logger.warning("ВНИМАНИЕ: Рекомендуется изменить стандартный пароль куратора!")
        return True

    except Exception as e:
        user_db.rollback()
        logger.error(f"Ошибка при создании куратора: {str(e)}")
        return False
    finally:
        user_db.close()

if __name__ == "__main__":
    logger.info("Запуск создания куратора...")

    # Если передан аргумент с chat_id, используем его
    chat_id = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            chat_id = arg
            break

    create_curator(chat_id)
    logger.info("Скрипт завершен.")
