import sqlite3
import logging
import os
from sqlalchemy import create_engine, Column, Boolean, inspect, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import shutil
import datetime
from models.db_init import Base, SessionLocal
from models.user_models import User
from models.ticket_models import Ticket, Message, Attachment, TicketCategory, DashboardMessage, DashboardAttachment, AuditLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_all_migrations():
    """Run all database migrations in a single function call"""
    logger.info("Starting unified database migrations...")

    # Создаем папку для бэкапов, если она не существует
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        logger.info(f"Created backup directory: {backup_dir}")

    # Backup databases before migrations (optional)
    if os.path.exists('users.db'):
        backup_path = os.path.join(backup_dir, f"users_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db")
        shutil.copy2('users.db', backup_path)
        logger.info(f"Backed up users database to {backup_path}")

    if os.path.exists('tickets.db'):
        backup_path = os.path.join(backup_dir, f"tickets_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db")
        shutil.copy2('tickets.db', backup_path)
        logger.info(f"Backed up tickets database to {backup_path}")

    # Run migrations for User database
    migrate_user_db()

    # Run migrations for Ticket database
    migrate_tickets_db()

    # Run specific migrations
    migrate_dashboard_messages()
    migrate_audit_logs()

    logger.info("All database migrations completed successfully!")

def migrate_user_db():
    """Migrate User database schema"""
    logger.info("Migrating User database schema...")
    user_db = SessionLocal()
    try:
        inspector = inspect(user_db.bind)
        has_users_table = 'users' in inspector.get_table_names()
        if not has_users_table:
            logger.warning("Users table not found, creating it...")
            Base.metadata.create_all(user_db.bind)
            logger.info("Users table created successfully")
        else:
            columns = {c['name']: c for c in inspector.get_columns('users')}
            if 'is_confirmed' not in columns:
                logger.info("Adding 'is_confirmed' column to users table")
                with user_db.bind.connect() as conn:
                    conn.execute("ALTER TABLE users ADD COLUMN is_confirmed BOOLEAN DEFAULT FALSE")
        user_db.commit()
        logger.info("User database schema migrated successfully")
    except Exception as e:
        user_db.rollback()
        logger.error(f"Error during user database migration: {str(e)}")
    finally:
        user_db.close()

def migrate_tickets_db():
    """Migrate Tickets database schema"""
    logger.info("Migrating Tickets database schema...")
    ticket_db = SessionLocal()
    try:
        inspector = inspect(ticket_db.bind)
        tables = inspector.get_table_names()
        if 'tickets' not in tables:
            logger.warning("Tickets table not found, creating it...")
            Base.metadata.create_all(ticket_db.bind)
            logger.info("Tickets table created successfully")
        if 'tickets' in tables:
            columns = {c['name']: c for c in inspector.get_columns('tickets')}
            if 'resolution' not in columns:
                logger.info("Adding 'resolution' column to tickets table")
                with ticket_db.bind.connect() as conn:
                    conn.execute("ALTER TABLE tickets ADD COLUMN resolution TEXT")
        if 'messages' in tables:
            columns = {c['name']: c for c in inspector.get_columns('messages')}
            if 'is_internal' not in columns:
                logger.info("Adding 'is_internal' column to messages table")
                with ticket_db.bind.connect() as conn:
                    conn.execute("ALTER TABLE messages ADD COLUMN is_internal BOOLEAN DEFAULT FALSE")
            if 'is_pinned' not in columns:
                logger.info("Adding 'is_pinned' column to messages table")
                with ticket_db.bind.connect() as conn:
                    conn.execute("ALTER TABLE messages ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE")
        ticket_db.commit()
        logger.info("Tickets database schema migrated successfully")
    except Exception as e:
        ticket_db.rollback()
        logger.error(f"Error during ticket database migration: {str(e)}")
    finally:
        ticket_db.close()

def migrate_dashboard_messages():
    """Create dashboard_messages and dashboard_attachments tables if they don't exist"""
    logger.info("Checking dashboard_messages tables...")
    ticket_db = SessionLocal()
    try:
        inspector = inspect(ticket_db.bind)
        tables = inspector.get_table_names()
        if 'dashboard_messages' not in tables:
            logger.info("Creating dashboard_messages table...")
            Base.metadata.create_all(ticket_db.bind)
            logger.info("dashboard_messages table created successfully")
        if 'dashboard_attachments' not in tables:
            logger.info("Creating dashboard_attachments table...")
            Base.metadata.create_all(ticket_db.bind)
            logger.info("dashboard_attachments table created successfully")
        ticket_db.commit()
        logger.info("Dashboard messages tables migration completed")
    except Exception as e:
        ticket_db.rollback()
        logger.error(f"Error during dashboard_messages migration: {str(e)}")
    finally:
        ticket_db.close()

def migrate_audit_logs():
    """Create and check audit_logs table"""
    logger.info("Checking audit_logs table...")
    ticket_db = SessionLocal()
    try:
        inspector = inspect(ticket_db.bind)
        tables = inspector.get_table_names()
        if 'audit_logs' not in tables:
            logger.info("Creating audit_logs table...")
            Base.metadata.create_all(ticket_db.bind)
            logger.info("audit_logs table created successfully")
        test_log = AuditLog(
            actor_id="system",
            actor_name="System",
            action_type="test",
            description="Testing audit logs table",
            entity_type="system",
            entity_id="0",
            is_pdn_related=False,
            timestamp=datetime.datetime.utcnow()
        )
        ticket_db.add(test_log)
        ticket_db.commit()
        test_query = ticket_db.query(AuditLog).filter(AuditLog.actor_id == "system").first()
        if test_query:
            logger.info("audit_logs table works correctly")
            ticket_db.delete(test_query)
            ticket_db.commit()
        else:
            logger.warning("audit_logs table may not be working correctly")
        logger.info("Audit logs table migration completed")
    except Exception as e:
        ticket_db.rollback()
        logger.error(f"Error during audit_logs migration: {str(e)}")
    finally:
        ticket_db.close()

if __name__ == "__main__":
    # Run all migrations when script is executed directly
    run_all_migrations()
