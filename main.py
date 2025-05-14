import threading
import os
import sys
import logging
import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

try:
    from app import app
    from bot.bot import run_bot
    from models.db_init import init_db, SessionLocal
    from models.user_models import User
    from dotenv import load_dotenv
    from db_migrations import run_all_migrations
    from init_categories import init_categories

    load_dotenv()

    _DEPENDENCIES_LOADED = True
except ImportError as e:
    logger.error(f"Failed to import dependencies: {str(e)}")
    _DEPENDENCIES_LOADED = False

def run_web_app():
    """Run the web application"""
    debug_mode = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)

def main():
    """Main application entry point"""
    if not _DEPENDENCIES_LOADED:
        logger.error("Dependencies not loaded. Cannot start application.")
        return

    try:
        # Initialize database
        init_db()

        # Проверяем и создаем директорию для бэкапов
        backup_dir = "backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            logger.info(f"Создана директория для бэкапов: {backup_dir}")

        # Запускаем миграцию базы данных только при первом запуске или явной ошибке
        try:
            # Выполняем проверку необходимых таблиц и структур БД
            from app import check_required_tables
            db_check_result = check_required_tables()

            if not db_check_result:
                # Если проверка не прошла, запускаем миграцию
                logger.warning("Проблемы с базой данных. Запускаем миграцию...")
                run_all_migrations()
        except Exception as db_error:
            # Если произошла ошибка при работе с БД, запускаем миграцию
            logger.error(f"Ошибка при проверке базы данных: {str(db_error)}")
            logger.warning("Запускаем миграцию для исправления ошибок...")
            run_all_migrations()

        # Инициализируем категории билетов
        logger.info("Инициализируем категории билетов...")
        init_categories()

        # Ensure uploads directory exists
        if not os.path.exists('uploads'):
            os.makedirs('uploads')

        # Start web app in a separate thread
        logger.info("Starting Flask app...")
        flask_thread = threading.Thread(target=run_web_app)
        flask_thread.daemon = True
        flask_thread.start()

        # Start Telegram bot in main thread
        logger.info("Starting Telegram bot...")
        run_bot()

    except Exception as e:
        logger.error(f"Error starting application: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
