import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Пути к базам данных
ticket_db_path = 'tickets.db'

def create_fresh_tickets_db():
    """Создает новую базу данных tickets.db с таблицей audit_logs"""
    # Удаляем существующую базу данных, если она существует
    if os.path.exists(ticket_db_path):
        os.remove(ticket_db_path)
        logger.info(f"Удалена существующая база данных {ticket_db_path}")

    try:
        # Создаем новую базу данных
        conn = sqlite3.connect(ticket_db_path)
        cursor = conn.cursor()

        # Создаем таблицу audit_logs
        logger.info("Создание таблицы audit_logs...")
        cursor.execute("""
            CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id VARCHAR(50) NOT NULL,
            actor_name VARCHAR(100),
            action_type VARCHAR(50) NOT NULL,
            description TEXT NOT NULL,
            entity_type VARCHAR(50),
            entity_id VARCHAR(50),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_pdn_related BOOLEAN DEFAULT 0,
            ip_address VARCHAR(50),
            details TEXT
            )
        """)

        # Создаем таблицу tickets
        logger.info("Создание таблицы tickets...")
        cursor.execute("""
            CREATE TABLE tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title VARCHAR(100) NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'new',
            creator_chat_id VARCHAR(50) NOT NULL,
            assigned_to VARCHAR(50),
            resolution TEXT,
            category_id INTEGER,
            priority VARCHAR(20) DEFAULT 'normal'
            )
        """)

        # Создаем таблицу attachments
        logger.info("Создание таблицы attachments...")
        cursor.execute("""
            CREATE TABLE attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            file_path VARCHAR(255) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_type VARCHAR(50),
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id)
            )
        """)

        # Создаем таблицу messages
        logger.info("Создание таблицы messages...")
        cursor.execute("""
            CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_id VARCHAR(50) NOT NULL,
            sender_name VARCHAR(100) NOT NULL,
            content TEXT NOT NULL,
            is_from_user BOOLEAN DEFAULT 0,
            is_internal BOOLEAN DEFAULT 0,
            is_pinned BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id)
            )
        """)

        # Создаем таблицу ticket_categories
        logger.info("Создание таблицы ticket_categories...")
        cursor.execute("""
            CREATE TABLE ticket_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
            )
        """)

        # Создаем таблицу dashboard_messages
        logger.info("Создание таблицы dashboard_messages...")
        cursor.execute("""
            CREATE TABLE dashboard_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id VARCHAR(50) NOT NULL,
            sender_name VARCHAR(100) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_pinned BOOLEAN DEFAULT 0
            )
        """)

        # Создаем таблицу dashboard_attachments
        logger.info("Создание таблицы dashboard_attachments...")
        cursor.execute("""
            CREATE TABLE dashboard_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            file_path VARCHAR(255) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_type VARCHAR(50),
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES dashboard_messages (id)
            )
        """)

        conn.commit()

        # Проверяем, что таблицы созданы
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        logger.info(f"Созданы таблицы: {[t[0] for t in tables]}")

        conn.close()
        logger.info(f"База данных {ticket_db_path} успешно создана!")
        return True

    except Exception as e:
        logger.error(f"Ошибка при создании базы данных: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Начало создания новой базы данных...")
    if create_fresh_tickets_db():
        print("База данных успешно создана с таблицей audit_logs!")
    else:
        print("Ошибка при создании базы данных. Проверьте логи.")
