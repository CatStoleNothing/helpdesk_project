from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory, jsonify
from dotenv import load_dotenv
import os
import functools
import jinja2
import asyncio
import threading
import logging
import nest_asyncio
from sqlalchemy.orm import joinedload

from models.db_init import init_db, SessionLocal
from models.user_models import User
from models.ticket_models import (
    Ticket, Attachment, Message, DashboardMessage,
    DashboardAttachment, TicketCategory, AuditLog
)
from sqlalchemy import func, desc
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from db_migrations import run_all_migrations
from models.user_models import User
from models.ticket_models import AuditLog
from sqlalchemy import or_
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-here")
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max upload

# Ensure uploads folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    user = db.query(User).get(int(user_id))
    db.close()
    return user

# Apply asyncio compatibility
nest_asyncio.apply()

# Initialize database
init_db()

# Проверяем наличие необходимых таблиц и при необходимости запускаем миграцию
def check_required_tables():
    ticket_db = SessionLocal()
    try:
        from sqlalchemy import inspect
        inspector = inspect(ticket_db.bind)
        tables = inspector.get_table_names()

        required_tables = [
            'tickets', 'messages', 'attachments', 'audit_logs', 'ticket_categories',
            'dashboard_messages', 'dashboard_attachments'
        ]

        missing_tables = [table for table in required_tables if table not in tables]

        if missing_tables:
            logging.warning(f"ВНИМАНИЕ: Следующие таблицы отсутствуют в базе данных: {', '.join(missing_tables)}")
            logging.warning("Автоматически запускаем миграцию базы данных...")

            # Закрываем текущее соединение перед выполнением миграции
            ticket_db.close()

            # Запускаем миграцию базы данных
            try:
                run_all_migrations()
                logging.info("Миграция базы данных успешно выполнена!")
                return True
            except Exception as e:
                logging.error(f"Ошибка при выполнении миграции базы данных: {str(e)}")
                return False

        return True
    except Exception as e:
        logging.error(f"Ошибка при проверке таблиц: {str(e)}")
        return False
    finally:
        ticket_db.close()

check_result = check_required_tables()
if not check_result:
    logging.error("Не удалось выполнить автоматическую миграцию. Приложение может работать некорректно.")

# Helper function for safely running async code from threads
def run_async_in_thread(coro, *args, **kwargs):
    async def wrapper():
        try:
            return await coro(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error in async thread execution: {str(e)}")
            return False

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(wrapper())
    except Exception as e:
        logging.error(f"Failed to run async code in thread: {str(e)}")
        return False
    finally:
        loop.close()

# Add nl2br filter to Jinja
@app.template_filter('nl2br')
def nl2br(value):
    if value:
        return jinja2.utils.markupsafe.Markup(value.replace('\n', '<br>'))
    return ""

# 404 Error handler
@app.errorhandler(404)
def page_not_found(e):
    if request.path == '/favicon.ico':
        return '', 204  # No content
    return redirect(url_for('index'))

# Универсальный декоратор с поддержкой ролей (всегда использует current_user/Flask-Login)
def login_required_role(role=None):
    def wrapper(fn):
        @functools.wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Пожалуйста, войдите в систему', 'error')
                return redirect(url_for('login', next=request.url))
            if role and getattr(current_user, 'role', None) not in role:
                flash('У вас нет доступа', 'error')
                return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

@app.route('/create_ticket', methods=['GET', 'POST'])
@login_required_role()
def create_ticket():
    ticket_db = SessionLocal()
    import sqlalchemy
    # Определим, админ/куратор ли это
    is_staff = getattr(current_user, 'role', None) in ["admin", "curator"]
    users = None
    if is_staff:
        user_db = SessionLocal()
        users = user_db.query(User).filter(User.is_active == True, User.is_confirmed == True).all()
        user_db.close()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category_id = request.form.get('category_id')
        # добавляем приоритет, если есть
        priority = request.form.get('priority', 'normal')
        status = request.form.get('status', 'new')
        # Новое: выбор или автоматический текущий creator
        if is_staff and request.form.get('creator_id'):
            creator_chat_id = request.form.get('creator_id')
        else:
            creator_chat_id = current_user.chat_id
        new_ticket = Ticket(
            title=title,
            description=description,
            category_id=category_id,
            priority=priority,
            status=status,
            creator_chat_id=creator_chat_id,
            created_at=datetime.utcnow()
        )
        ticket_db.add(new_ticket)
        ticket_db.commit()
        ticket_db.close()
        flash('Заявка успешно создана', 'success')
        return redirect(url_for('tickets'))
    categories = ticket_db.query(TicketCategory).all()
    ticket_db.close()
    return render_template(
        'create_ticket.html',
        categories=categories,
        users=users
    )

@app.route('/registration_approval', methods=['GET', 'POST'])
@login_required_role(role=['curator', 'admin'])
def registration_approval():
    db = SessionLocal()
    ticket_db = SessionLocal()  # Add ticket database session for audit logs
    action = request.args.get('action')
    user_id = request.args.get('id', type=int)

    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id', type=int)
        if user_id and action:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                flash('Пользователь не найден', 'error')
                db.close()
                ticket_db.close()  # Close ticket db session
                return redirect(url_for('registration_approval'))
            # История логирования
            audit_action = ''
            if action == 'approve':
                user.is_confirmed = True
                user.is_active = True
                audit_action = 'approve_registration'
                flash(f'Пользователь {user.full_name} подтвержден', 'success')
            elif action == 'reject':
                user.is_confirmed = False
                user.is_active = False
                audit_action = 'reject_registration'
                flash(f'Пользователь {user.full_name} отклонён и заблокирован', 'info')
            elif action == 'unlock':
                user.is_active = True
                audit_action = 'unlock_user'
                flash(f'Пользователь {user.full_name} разблокирован', 'success')
            elif action == 'reconsider':
                user.is_confirmed = False
                user.is_active = True
                audit_action = 'reconsider_registration'
                flash(f'Заявка {user.full_name} возвращена на рассмотрение', 'info')

            # Use ticket_db for AuditLog, not db
            ticket_db.add(AuditLog(
                actor_id=str(current_user.id),
                actor_name=current_user.full_name,
                action_type=audit_action,
                description=f"{audit_action} для пользователя {user.full_name} (id={user_id})",
                entity_type='user',
                entity_id=str(user_id),
                is_pdn_related=True,
                timestamp=datetime.utcnow()
            ))
            db.commit()
            ticket_db.commit()  # Commit changes to ticket_db
            db.close()
            ticket_db.close()  # Close ticket db session
            return redirect(url_for('registration_approval'))

    # Фильтруем пользователей: только заявки, отклонённые и блокированные; подтверждённых и активных пропускаем
    new_users = db.query(User).filter(User.is_confirmed == False, User.is_active == True).all()
    rejected_users = db.query(User).filter(User.is_active == False).all()
    approved_users = db.query(User).filter(User.is_confirmed == True, User.is_active == True).all()

    # История одобрения/отклонения - use ticket_db for AuditLog
    actions = ticket_db.query(AuditLog).filter(AuditLog.entity_type=='user').order_by(AuditLog.timestamp.desc()).limit(50).all()

    db.close()
    ticket_db.close()  # Close ticket db session
    return render_template('registration_approval.html', new_users=new_users, rejected_users=rejected_users, approved_users=approved_users, actions=actions)

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required_role(['curator'])
def edit_user(user_id):
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        db.close()
        abort(404)
    if request.method == 'POST':
        user.full_name = request.form.get('full_name', user.full_name).strip()
        user.username  = request.form.get('username',  user.username).strip()
        user.position  = request.form.get('position',  user.position).strip()
        user.department= request.form.get('department',user.department).strip()
        user.office    = request.form.get('office',    user.office).strip()
        user.role      = request.form.get('role',      user.role)
        pwd = request.form.get('password','').strip()
        if pwd:
            user.password_hash = User.get_password_hash(pwd)
        db.commit()
        db.close()
        flash('Пользователь обновлён', 'success')
        return redirect(url_for('users'))
    db.close()
    return render_template('edit_user.html', user=user)

@app.route('/edit_category/<int:category_id>', methods=['GET', 'POST'])
@login_required_role(['curator'])
def edit_category(category_id):
    db = SessionLocal()
    category = db.query(TicketCategory).get(category_id)
    if not category:
        db.close()
        abort(404)
    if request.method == 'POST':
        category.name        = request.form.get('name', category.name).strip()
        category.description = request.form.get('description', category.description).strip()
        category.is_active   = 'is_active' in request.form
        db.commit()
        db.close()
        flash('Категория обновлена', 'success')
        return redirect(url_for('categories_page'))
    db.close()
    return render_template('edit_category.html', category=category)

@app.route('/categories')
@login_required_role()
def categories_page():
    ticket_db = SessionLocal()
    categories = ticket_db.query(TicketCategory).all()
    ticket_db.close()
    return render_template('categories.html', categories=categories)

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_db = SessionLocal()
        user = user_db.query(User).filter(User.username == username).first()
        if user and user.verify_password(password):
            if not user.is_confirmed:
                user_db.close()
                flash('Ваша учетная запись ожидает подтверждения администратором', 'error')
                return render_template('login.html')
            login_user(user)
            user_db.close()
            next_page = request.args.get('next', url_for('dashboard'))
            return redirect(next_page)
        user_db.close()
        flash('Неверное имя пользователя или пароль', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required_role()
def dashboard():
    ticket_db = SessionLocal()
    user_db = SessionLocal()

    user = user_db.query(User).filter(User.id == current_user.id).first()

    if not user:
        user_db.close()
        ticket_db.close()
        logout_user()
        flash('Пользовательская сессия недействительна. Пожалуйста, войдите снова.', 'error')
        return redirect(url_for('login'))

    total_tickets = ticket_db.query(func.count(Ticket.id)).scalar()
    new_tickets = ticket_db.query(func.count(Ticket.id)).filter(Ticket.status == 'new').scalar()
    resolved_tickets = ticket_db.query(func.count(Ticket.id)).filter(Ticket.status == 'resolved').scalar()

    assigned_tickets = ticket_db.query(func.count(Ticket.id)).filter(Ticket.assigned_to == str(current_user.id)).scalar()

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    resolved_this_month = ticket_db.query(func.count(Ticket.id)).filter(
        Ticket.assigned_to == str(current_user.id),
        Ticket.status == 'resolved',
        Ticket.updated_at >= thirty_days_ago
    ).scalar()

    twelve_hours_ago = datetime.utcnow() - timedelta(hours=12)
    recent_tickets = ticket_db.query(Ticket).filter(
        Ticket.created_at >= twelve_hours_ago
    ).order_by(desc(Ticket.created_at)).all()

    formatted_tickets = []
    for ticket in recent_tickets:
        creator = user_db.query(User).filter(User.chat_id == ticket.creator_chat_id).first()
        creator_name = creator.full_name if creator else "Неизвестный пользователь"
        description = ticket.description
        if len(description) > 100:
            description = description[:97] + "..."
        formatted_tickets.append({
            'id': ticket.id,
            'title': ticket.title,
            'status': ticket.status,
            'created_at': ticket.created_at,
            'creator_name': creator_name,
            'description': description
        })

    dashboard_messages = ticket_db.query(DashboardMessage).order_by(DashboardMessage.created_at).all()

    for message in dashboard_messages:
        message.attachments = ticket_db.query(DashboardAttachment).filter(DashboardAttachment.message_id == message.id).all()

    pinned_message = ticket_db.query(DashboardMessage).filter(DashboardMessage.is_pinned == True).first()
    if pinned_message:
        pinned_message.attachments = ticket_db.query(DashboardAttachment).filter(DashboardAttachment.message_id == pinned_message.id).all()

    staff = user_db.query(User).filter(User.role.in_(['admin', 'curator'])).all()

    ticket_db.close()
    user_db.close()

    return render_template('dashboard.html',
                          total_tickets=total_tickets,
                          new_tickets=new_tickets,
                          resolved_tickets=resolved_tickets,
                          assigned_tickets=assigned_tickets,
                          resolved_this_month=resolved_this_month,
                          recent_tickets=formatted_tickets,
                          dashboard_messages=dashboard_messages,
                          pinned_message=pinned_message,
                          staff=staff,
                          current_user_id=current_user.id)

@app.route('/send_dashboard_message', methods=['POST'])
@login_required_role()
def send_dashboard_message():
    ticket_db = SessionLocal()

    try:
        message_content = request.form.get('message', '').strip()

        if not message_content and (('image' not in request.files) or not request.files['image'].filename):
            flash('Сообщение не может быть пустым', 'error')
            return redirect(url_for('dashboard'))

        new_message = DashboardMessage(
            sender_id=str(current_user.id),
            sender_name=current_user.full_name,
            content=message_content
        )

        ticket_db.add(new_message)
        ticket_db.commit()

        if 'image' in request.files and request.files['image'].filename:
            image_file = request.files['image']

            allowed_extensions = {'jpg', 'jpeg', 'png', 'gif'}
            if '.' in image_file.filename and image_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                attachments_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'dashboard')
                if not os.path.exists(attachments_dir):
                    os.makedirs(attachments_dir)

                filename = secure_filename(image_file.filename)
                filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"

                file_path = os.path.join(attachments_dir, filename)
                image_file.save(file_path)

                file_type = image_file.content_type if hasattr(image_file, 'content_type') else None

                new_attachment = DashboardAttachment(
                    message_id=new_message.id,
                    file_path=os.path.join('dashboard', filename),
                    file_name=image_file.filename,
                    file_type=file_type
                )

                ticket_db.add(new_attachment)
                ticket_db.commit()
            else:
                flash('Недопустимый формат файла. Допустимые форматы: jpg, jpeg, png, gif', 'error')

        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="send_dashboard_message",
            description=f"Отправлено сообщение в командный чат",
            entity_type="dashboard_message",
            entity_id=str(new_message.id),
            is_pdn_related=False,
            timestamp=datetime.utcnow()
        )

        ticket_db.add(audit_log)
        ticket_db.commit()

        flash('Сообщение отправлено', 'success')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при отправке сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при отправке сообщения в командный чат: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/dashboard_attachment/<path:filename>')
@login_required_role()
def dashboard_attachment(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/pin_dashboard_message/<int:message_id>', methods=['POST'])
@login_required_role(role=['curator', 'admin'])
def pin_dashboard_message(message_id):
    ticket_db = SessionLocal()

    try:
        ticket_db.query(DashboardMessage).filter(DashboardMessage.is_pinned == True).update({'is_pinned': False})

        message = ticket_db.query(DashboardMessage).filter(DashboardMessage.id == message_id).first()
        if message:
            message.is_pinned = True

            audit_log = AuditLog(
                actor_id=str(current_user.id),
                actor_name=current_user.full_name,
                action_type="pin_message",
                description=f"Закреплено сообщение в командном чате (ID: {message_id})",
                entity_type="dashboard_message",
                entity_id=str(message_id),
                is_pdn_related=False,
                timestamp=datetime.utcnow()
            )

            ticket_db.add(audit_log)
            ticket_db.commit()
            flash('Сообщение закреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при закреплении сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при закреплении сообщения: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/unpin_dashboard_message/<int:message_id>', methods=['POST'])
@login_required_role(role=['curator', 'admin'])
def unpin_dashboard_message(message_id):
    ticket_db = SessionLocal()

    try:
        message = ticket_db.query(DashboardMessage).filter(DashboardMessage.id == message_id).first()
        if message:
            message.is_pinned = False

            audit_log = AuditLog(
                actor_id=str(current_user.id),
                actor_name=current_user.full_name,
                action_type="unpin_message",
                description=f"Откреплено сообщение в командном чате (ID: {message_id})",
                entity_type="dashboard_message",
                entity_id=str(message_id),
                is_pdn_related=False,
                timestamp=datetime.utcnow()
            )

            ticket_db.add(audit_log)
            ticket_db.commit()
            flash('Сообщение откреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при откреплении сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при откреплении сообщения: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/delete_dashboard_message/<int:message_id>', methods=['POST'])
@login_required_role()
def delete_dashboard_message(message_id):
    ticket_db = SessionLocal()

    try:
        message = ticket_db.query(DashboardMessage).filter(DashboardMessage.id == message_id).first()

        if not message:
            flash('Сообщение не найдено', 'error')
            return redirect(url_for('dashboard'))

        # Проверяем права доступа: пользователь может удалить свое сообщение или если он админ/куратор
        if str(message.sender_id) != str(current_user.id) and current_user.role not in ['admin', 'curator']:
            flash('У вас нет прав на удаление этого сообщения', 'error')
            return redirect(url_for('dashboard'))

        message_info = {
            'id': message.id,
            'sender_id': message.sender_id,
            'sender_name': message.sender_name,
            'content': message.content[:50] + ('...' if len(message.content) > 50 else '')
        }

        ticket_db.delete(message)

        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="delete_dashboard_message",
            description=f"Удалено сообщение из командного чата (ID: {message_info['id']}, отправитель: {message_info['sender_name']})",
            entity_type="dashboard_message",
            entity_id=str(message_info['id']),
            is_pdn_related=False,
            timestamp=datetime.utcnow()
        )

        ticket_db.add(audit_log)
        ticket_db.commit()

        flash('Сообщение удалено', 'success')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при удалении сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при удалении сообщения из командного чата: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/create_category', methods=['GET', 'POST'])
@login_required_role(['curator'])
def create_category():
    db = SessionLocal()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Нужно указать название категории', 'error')
            db.close()
            return redirect(url_for('create_category'))
        new_cat = TicketCategory(name=name)
        db.add(new_cat)
        db.commit()
        flash(f'Категория "{name}" создана', 'success')
        db.close()
        return redirect(url_for('categories_page'))
    db.close()
    return render_template('create_category.html')

@app.route('/send_chat_message', methods=['POST'])
@login_required_role()
def send_chat_message():
    ticket_db = SessionLocal()

    try:
        message_text = request.form.get('message', '').strip()
        ticket_id = request.form.get('ticket_id')
        is_internal = request.form.get('is_internal') == 'true'

        has_attachment = 'image' in request.files and request.files['image'].filename

        if not message_text and not has_attachment:
            return jsonify({'success': False, 'error': 'Сообщение не может быть пустым'}), 400

        ticket = None
        if ticket_id:
            ticket = ticket_db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404

        if ticket:
            new_message = Message(
                ticket_id=ticket_id,
                sender_id=str(current_user.id),
                sender_name=current_user.full_name,
                content=message_text,
                is_internal=is_internal
            )

            if ticket.status == 'new' and not ticket.assigned_to:
                ticket.status = 'in_progress'
                ticket.assigned_to = str(current_user.id)
                ticket.updated_at = datetime.utcnow()

            entity_type = "ticket"
            entity_id = str(ticket_id)
            action_description = f"Отправлено сообщение в заявку #{ticket_id}"

        else:
            new_message = DashboardMessage(
                sender_id=str(current_user.id),
                sender_name=current_user.full_name,
                content=message_text
            )

            entity_type = "dashboard_message"
            entity_id = None
            action_description = "Отправлено сообщение в командный чат"

        ticket_db.add(new_message)
        ticket_db.flush()

        if not ticket_id:
            entity_id = str(new_message.id)

        attachment_data = None
        if has_attachment:
            image_file = request.files['image']

            allowed_extensions = {'jpg', 'jpeg', 'png', 'gif'}
            if '.' in image_file.filename and image_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                if ticket:
                    attachments_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'tickets', str(ticket_id))
                else:
                    attachments_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'dashboard')

                if not os.path.exists(attachments_dir):
                    os.makedirs(attachments_dir)

                filename = secure_filename(image_file.filename)
                filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"

                file_path = os.path.join(attachments_dir, filename)
                image_file.save(file_path)

                file_type = image_file.content_type if hasattr(image_file, 'content_type') else None

                if ticket:
                    new_attachment = Attachment(
                        message_id=new_message.id,
                        ticket_id=ticket_id,
                        file_path=os.path.join('tickets', str(ticket_id), filename),
                        file_name=image_file.filename,
                        file_type=file_type,
                        is_image=True
                    )
                else:
                    new_attachment = DashboardAttachment(
                        message_id=new_message.id,
                        file_path=os.path.join('dashboard', filename),
                        file_name=image_file.filename,
                        file_type=file_type
                    )

                ticket_db.add(new_attachment)
                ticket_db.flush()

                attachment_data = {
                    'id': new_attachment.id,
                    'file_name': new_attachment.file_name,
                    'file_path': f"/{'dashboard_attachment' if not ticket else 'ticket_attachment'}/{new_attachment.file_path}",
                    'is_image': True if ticket and hasattr(new_attachment, 'is_image') and new_attachment.is_image else file_type and file_type.startswith('image/')
                }
            else:
                ticket_db.rollback()
                return jsonify({'success': False, 'error': 'Недопустимый формат файла. Допустимые форматы: jpg, jpeg, png, gif'}), 400

        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="send_message",
            description=action_description,
            entity_type=entity_type,
            entity_id=entity_id,
            is_pdn_related=False,
            timestamp=datetime.utcnow()
        )

        ticket_db.add(audit_log)
        ticket_db.commit()

        response_data = {
            'success': True,
            'message': {
                'id': new_message.id,
                'content': new_message.content,
                'sender_name': new_message.sender_name,
                'created_at': new_message.created_at.strftime('%d.%m.%Y %H:%M'),
                'time': new_message.created_at.strftime('%H:%M'),
                'is_internal': is_internal if ticket else False,
                'attachment': attachment_data
            }
        }

        return jsonify(response_data), 200

    except Exception as e:
        ticket_db.rollback()
        logging.error(f"Ошибка при отправке сообщения в чат: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        ticket_db.close()

@app.route('/tickets')
@login_required_role()
def tickets():
    ticket_db = SessionLocal()
    user_db = SessionLocal()

    status = request.args.get('status', 'all')
    title = request.args.get('title', '')
    description = request.args.get('description', '')
    creator = request.args.get('creator_id', '')
    assignee = request.args.get('assignee_id', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = int(request.args.get('page', 1))
    per_page = 20

    query = ticket_db.query(Ticket)

    if status != 'all':
        query = query.filter(Ticket.status == status)

    if title:
        query = query.filter(Ticket.title.ilike(f'%{title}%'))

    if description:
        query = query.filter(Ticket.description.ilike(f'%{description}%'))

    if creator:
        query = query.filter(Ticket.creator_chat_id == creator)

    if assignee != 'all':
        if assignee == 'me':
            query = query.filter(Ticket.assigned_to == str(current_user.id))
        elif assignee == 'unassigned':
            query = query.filter((Ticket.assigned_to == None) | (Ticket.assigned_to == ''))
        else:
            query = query.filter(Ticket.assigned_to == assignee)

    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(Ticket.created_at >= date_from_obj)

    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        date_to_obj = date_to_obj.replace(hour=23, minute=59, second=59)
        query = query.filter(Ticket.created_at <= date_to_obj)

    categories = {cat.id: cat.name for cat in ticket_db.query(TicketCategory).all()}

    total_count = query.count()
    total_pages = (total_count + per_page - 1) // per_page

    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages

    tickets_query = query.order_by(desc(Ticket.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    all_staff = user_db.query(User).all()
    staff_map = {str(staff.id): staff.full_name for staff in all_staff}
    creator_map = {staff.chat_id: staff.full_name for staff in all_staff if staff.chat_id}

    formatted_tickets = []
    for ticket in tickets_query:
        creator_name = creator_map.get(ticket.creator_chat_id, "Неизвестный пользователь")
        assignee_name = staff_map.get(ticket.assigned_to, "-") if ticket.assigned_to else "-"
        category_name = categories.get(ticket.category_id, "-") if ticket.category_id else "-"

        formatted_tickets.append({
            'id': ticket.id,
            'title': ticket.title,
            'creator_name': creator_name,
            'assignee': assignee_name,
            'category_name': category_name,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_at': ticket.created_at
        })

    filter_params = {
        'status': status,
        'title': title,
        'description': description,
        'creator': creator,
        'assignee': assignee,
        'date_from': date_from,
        'date_to': date_to
    }

    ticket_db.close()
    user_db.close()

    return render_template('tickets.html',
                          tickets=formatted_tickets,
                          all_staff=all_staff,
                          filter_params=filter_params,
                          page=page,
                          total_pages=total_pages,
                          has_prev=(page > 1),
                          has_next=(page < total_pages))

@app.route('/tickets/fragment', methods=['POST'])
@login_required_role()
def tickets_fragment():
    ticket_db = SessionLocal()
    user_db = SessionLocal()

    status = request.form.get('status', 'all')
    title = request.form.get('title', '')
    description = request.form.get('description', '')
    creator = request.form.get('creator_id', '')
    assignee = request.form.get('assignee_id', 'all')
    date_from = request.form.get('date_from', '')
    date_to = request.form.get('date_to', '')
    page = int(request.form.get('page', 1))
    per_page = 20

    query = ticket_db.query(Ticket)

    if status != 'all':
        query = query.filter(Ticket.status == status)

    if title:
        query = query.filter(Ticket.title.ilike(f'%{title}%'))

    if description:
        query = query.filter(Ticket.description.ilike(f'%{description}%'))

    if creator:
        query = query.filter(Ticket.creator_chat_id == creator)

    if assignee != 'all':
        if assignee == 'me':
            query = query.filter(Ticket.assigned_to == str(current_user.id))
        elif assignee == 'unassigned':
            query = query.filter((Ticket.assigned_to == None) | (Ticket.assigned_to == ''))
        else:
            query = query.filter(Ticket.assigned_to == assignee)

    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(Ticket.created_at >= date_from_obj)

    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        date_to_obj = date_to_obj.replace(hour=23, minute=59, second=59)
        query = query.filter(Ticket.created_at <= date_to_obj)

    categories = {cat.id: cat.name for cat in ticket_db.query(TicketCategory).all()}

    total_count = query.count()
    total_pages = (total_count + per_page - 1) // per_page

    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages

    tickets_query = query.order_by(desc(Ticket.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    all_staff = user_db.query(User).all()
    staff_map = {str(staff.id): staff.full_name for staff in all_staff}
    creator_map = {staff.chat_id: staff.full_name for staff in all_staff if staff.chat_id}

    formatted_tickets = []
    for ticket in tickets_query:
        creator_name = creator_map.get(ticket.creator_chat_id, "Неизвестный пользователь")
        assignee_name = staff_map.get(ticket.assigned_to, "-") if ticket.assigned_to else "-"
        category_name = categories.get(ticket.category_id, "-") if ticket.category_id else "-"

        formatted_tickets.append({
            'id': ticket.id,
            'title': ticket.title,
            'creator_name': creator_name,
            'assignee': assignee_name,
            'category_name': category_name,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_at': ticket.created_at
        })

    ticket_db.close()
    user_db.close()

    return render_template('includes/tickets_table_fragment.html',
                          tickets=formatted_tickets,
                          page=page,
                          total_pages=total_pages,
                          has_prev=(page > 1),
                          has_next=(page < total_pages))

@app.route('/users')
@login_required_role(role=['curator'])
def users():
    user_db = SessionLocal()
    all_users = user_db.query(User).order_by(User.created_at.desc()).all()
    user_db.close()
    return render_template('users.html', users=all_users)

@app.route('/create_user', methods=['GET', 'POST'])
@login_required_role(role=['curator'])
def create_user():
    if request.method == 'POST':
        user_db = SessionLocal()
        ticket_db = SessionLocal()

        try:
            full_name = request.form['full_name']
            role = request.form['role']
            position = request.form.get('position', '')
            department = request.form.get('department', '')
            office = request.form.get('office', '')
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            chat_id = request.form.get('chat_id', '')

            if not full_name:
                flash('Необходимо указать ФИО пользователя', 'error')
                user_db.close()
                ticket_db.close()
                return render_template('create_user.html')

            if username and user_db.query(User).filter(User.username == username).first():
                user_db.close()
                ticket_db.close()
                flash('Пользователь с таким именем уже существует', 'error')
                return render_template('create_user.html')

            if chat_id and user_db.query(User).filter(User.chat_id == chat_id).first():
                user_db.close()
                ticket_db.close()
                flash('Пользователь с таким Chat ID уже существует', 'error')
                return render_template('create_user.html')

            new_user = User(
                username=username,
                password_hash=User.get_password_hash(password) if password else None,
                full_name=full_name,
                position=position,
                department=department,
                office=office,
                role=role,
                is_active=True,
                is_confirmed=True,
                chat_id=chat_id if chat_id else f"manual_{datetime.utcnow().timestamp()}"
            )

            user_db.add(new_user)
            user_db.commit()

            audit_log = AuditLog(
                actor_id=str(current_user.id),
                actor_name=current_user.full_name,
                action_type="create_user",
                description=f"Создан новый пользователь: {new_user.full_name} (ID: {new_user.id}) с ролью {new_user.role}",
                entity_type="user",
                entity_id=str(new_user.id),
                is_pdn_related=True,
                timestamp=datetime.utcnow()
            )

            ticket_db.add(audit_log)
            ticket_db.commit()

            user_db.close()
            ticket_db.close()

            flash(f'Пользователь {full_name} успешно создан', 'success')
            return redirect(url_for('users'))

        except Exception as e:
            user_db.rollback()
            ticket_db.rollback()
            user_db.close()
            ticket_db.close()
            flash(f'Ошибка при создании пользователя: {str(e)}', 'error')
            return render_template('create_user.html')

    return render_template('create_user.html')

@app.route('/ticket/<int:ticket_id>')
@login_required_role()
def ticket_detail(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket)\
        .options(
            joinedload(Ticket.attachments),
            joinedload(Ticket.messages)
        )\
        .filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    creator = db.query(User).filter(User.chat_id == ticket.creator_chat_id).first()
    assignee = db.query(User).filter(User.id == ticket.assigned_to).first() if ticket.assigned_to else None
    category = db.query(TicketCategory).filter(TicketCategory.id == ticket.category_id).first() if ticket.category_id else None
    staff = db.query(User).filter(User.role.in_(['admin', 'curator'])).all()
    response = render_template('ticket_detail.html', ticket=ticket, creator_name=creator.full_name if creator else 'Неизвестно', assignee=assignee, category=category, staff=staff)
    db.close()
    return response

@app.route('/ticket/<int:ticket_id>/assign', methods=['POST'])
@login_required_role()
def assign_ticket(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    assigned_to = request.form.get('assigned_to')
    if assigned_to:
        ticket.assigned_to = int(assigned_to)
        db.commit()
        flash('Исполнитель назначен', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required_role()
def resolve_ticket(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    resolution = request.form.get('resolution')
    if resolution:
        ticket.resolution = resolution
        ticket.status = 'resolved'
        db.commit()
        flash('Заявка завершена', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/reopen', methods=['POST'])
@login_required_role()
def reopen_ticket(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    reason = request.form.get('reason')
    if reason:
        ticket.resolution = None
        ticket.status = 'in_progress'
        db.commit()
        flash('Заявка возвращена в работу', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/irrelevant', methods=['POST'])
@login_required_role()
def mark_irrelevant(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    reason = request.form.get('reason')
    if reason:
        ticket.resolution = reason
        ticket.status = 'irrelevant'
        db.commit()
        flash('Заявка отмечена как неактуальная', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/message/<int:message_id>/pin/<chat_type>', methods=['POST'])
@login_required_role()
def pin_message(ticket_id, message_id, chat_type):
    db = SessionLocal()
    try:
        # Сначала открепляем все сообщения в этом чате
        if chat_type == 'external':
            db.query(Message).filter(
                Message.ticket_id == ticket_id,
                Message.is_internal == False
            ).update({'is_pinned': False})
        else:
            db.query(Message).filter(
                Message.ticket_id == ticket_id,
                Message.is_internal == True
            ).update({'is_pinned': False})

        # Закрепляем выбранное сообщение
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.ticket_id == ticket_id
        ).first()
        
        if message:
            message.is_pinned = True
            db.commit()
            flash('Сообщение закреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        db.rollback()
        flash(f'Ошибка при закреплении сообщения: {str(e)}', 'error')
    finally:
        db.close()
    
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/message/<int:message_id>/unpin/<chat_type>', methods=['POST'])
@login_required_role()
def unpin_message(ticket_id, message_id, chat_type):
    db = SessionLocal()
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.ticket_id == ticket_id
        ).first()
        
        if message:
            message.is_pinned = False
            db.commit()
            flash('Сообщение откреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        db.rollback()
        flash(f'Ошибка при откреплении сообщения: {str(e)}', 'error')
    finally:
        db.close()
    
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

if __name__ == '__main__':
    debug_mode = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
