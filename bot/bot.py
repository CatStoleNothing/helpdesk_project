import logging
import os
import re
import nest_asyncio
import asyncio.exceptions
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from sqlalchemy.orm import Session
from typing import List, Optional
import sys
import datetime
import asyncio
from aiogram.exceptions import TelegramAPIError
import requests
import json
from dotenv import load_dotenv
from models.db_init import SessionLocal

# Add parent directory to path to import the models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.user_models import User
from models.ticket_models import Ticket, Attachment, Message, TicketCategory, AuditLog

# Load environment variables
load_dotenv()

# Apply nest_asyncio to allow nested asyncio operations
nest_asyncio.apply()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialization flag
_DEPENDENCIES_LOADED = True

try:
    import logging
    import os
    import re
    import nest_asyncio
    import asyncio.exceptions
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command, CommandObject
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
    from sqlalchemy.orm import Session
    from typing import List, Optional
    import sys
    import datetime
    import asyncio
    from aiogram.exceptions import TelegramAPIError
    import requests
    import json
    from dotenv import load_dotenv

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Initialization flag
    _DEPENDENCIES_LOADED = True

except ImportError as e:
    import sys
    import logging

    # Configure basic logging
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])

    logging.error(f"Failed to import dependencies: {str(e)}")
    _DEPENDENCIES_LOADED = False

# Initialize bot and dispatcher
API_TOKEN = os.getenv("TELEGRAM_API_TOKEN", "")
bot = Bot(token=API_TOKEN if API_TOKEN else "1")  # Используем фиктивный токен если настоящего нет
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Define states for registration
class RegistrationStates(StatesGroup):
    waiting_for_gdpr_consent = State()
    waiting_for_fullname = State()
    waiting_for_position = State()
    waiting_for_department = State()
    waiting_for_office = State()
    waiting_for_phone = State()
    waiting_for_email = State()

# Define states for ticket creation
class TicketStates(StatesGroup):
    waiting_for_category = State()  # Добавлено для выбора категории
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_priority = State()  # Добавлено для выбора приоритета
    waiting_for_attachments = State()

# Define states for ticket selection
class TicketSelectStates(StatesGroup):
    waiting_for_ticket_id = State()
    pagination_data = State()

# Helper function to check if user exists
def get_user_by_chat_id(chat_id: str, db: Session) -> Optional[User]:
    return db.query(User).filter(User.chat_id == str(chat_id)).first()

# Helper function to check user status
async def check_user_status(chat_id: str, db: Session):
    """
    Проверяет статус пользователя: существует ли, активен ли, подтвержден ли.

    Args:
        chat_id: ID чата пользователя
        db: Сессия базы данных

    Returns:
        tuple: (status: bool, message: str | None, user: User | None)
            - status - True если все проверки пройдены, False если нет
            - message - сообщение об ошибке или None если проверки пройдены
            - user - объект пользователя или None если пользователь не найден
    """
    # Проверяем существование пользователя
    user = get_user_by_chat_id(chat_id, db)
    if not user:
        return False, "Вы не зарегистрированы в системе. Используйте /start для регистрации.", None

    # Проверяем активность аккаунта
    if not user.is_active:
        return False, "❌ Ваш аккаунт заблокирован. Обратитесь к администратору системы для выяснения причин.", user

    # Проверяем подтверждение администратором
    if not user.is_confirmed:
        return False, "⚠️ Ваш аккаунт ожидает подтверждения администратором.\n\nНекоторые функции ограничены до проверки. Используйте /profile для просмотра статуса.", user

    # Все проверки пройдены
    return True, None, user

# Helper function to add audit log entry
def add_audit_log(db: Session, actor_id: str, actor_name: str, action_type: str,
                  description: str, entity_type: str = None, entity_id: str = None,
                  is_pdn_related: bool = False, ip_address: str = None, details: str = None):
    """
    Добавляет запись в журнал аудита

    Args:
        db: Сессия базы данных
        actor_id: ID пользователя, выполнившего действие (chat_id)
        actor_name: Имя пользователя
        action_type: Тип действия (create, update, delete, login, etc.)
        description: Описание действия
        entity_type: Тип сущности (user, ticket, etc.)
        entity_id: ID сущности, связанной с действием
        is_pdn_related: Связано ли с обработкой ПДн (для аудита по 152-ФЗ)
        ip_address: IP-адрес пользователя
        details: Дополнительные детали (JSON или текст)
    """
    try:
        log_entry = AuditLog(
            actor_id=str(actor_id),
            actor_name=actor_name,
            action_type=action_type,
            description=description,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            is_pdn_related=is_pdn_related,
            ip_address=ip_address,
            details=details,
            timestamp=datetime.datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка при добавлении записи в журнал аудита: {str(e)}")
        return False

# Функции для отправки уведомлений
async def send_notification(chat_id: str, message: str):
    """
    Асинхронная функция для отправки уведомлений пользователям через Telegram бота
    """
    try:
        if not API_TOKEN:
            logging.error("Telegram bot token is not configured")
            return False

        await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
        return True
    except TelegramAPIError as e:
        logging.error(f"Failed to send notification to {chat_id}: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"Error sending notification: {str(e)}")
        return False

def sync_send_notification(chat_id: str, message: str):
    """
    Синхронная обертка для отправки уведомлений
    """
    try:
        if not API_TOKEN:
            logging.error("Telegram bot token is not configured")
            return False

        # Используем loop для запуска асинхронной функции
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_notification(chat_id, message))
        loop.close()
        return result
    except Exception as e:
        logging.error(f"Error in sync notification sender: {str(e)}")
        return False

# Synchronous function to send notification using requests
def sync_send_notification(chat_id, message):
    if not chat_id:
        logging.error(f"Невозможно отправить сообщение: chat_id отсутствует")
        return False

    # Check for manually created users
    if isinstance(chat_id, str) and chat_id.startswith('manual_'):
        logging.warning(f"Попытка отправки сообщения вручную созданному пользователю: {chat_id}")
        return False

    # Ensure chat_id is a string
    chat_id_str = str(chat_id).strip()
    logging.info(f"Отправка сообщения пользователю {chat_id_str}: {message[:50]}...")

    # Prepare the API request
    api_url = f"https://api.telegram.org/bot{API_TOKEN}/sendMessage"

    try:
        # First attempt with original message
        payload = {
            'chat_id': chat_id_str,
            'text': message,
            'parse_mode': 'HTML'
        }

        response = requests.post(api_url, json=payload, timeout=10)

        if response.status_code == 200:
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str}")
            return True

        # If HTML parsing fails, try without HTML
        logging.warning(f"Ошибка при отправке сообщения: {response.text}. Пробуем без парсинга HTML...")
        clean_message = re.sub(r'<[^>]*>', '', message)

        payload = {
            'chat_id': chat_id_str,
            'text': clean_message
        }

        response = requests.post(api_url, json=payload, timeout=10)

        if response.status_code == 200:
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str} (без HTML)")
            return True
        else:
            error_data = response.json() if response.content else {"description": "Unknown error"}
            logging.error(f"Не удалось отправить сообщение: {error_data.get('description', 'Unknown error')}")
            return False

    except Exception as e:
        logging.error(f"Ошибка отправки уведомления пользователю {chat_id}: {str(e)}")
        try:
            error_type = type(e).__name__
            logging.error(f"Тип ошибки: {error_type}")

            if hasattr(e, '__traceback__'):
                import traceback
                error_trace = ''.join(traceback.format_tb(e.__traceback__))
                logging.error(f"Трассировка: {error_trace}")
        except:
            pass

        return False

# Функция для отправки уведомлений пользователю
async def send_notification(chat_id, message):
    try:
        # Проверка валидности chat_id
        if not chat_id:
            logging.error(f"Невозможно отправить сообщение: chat_id отсутствует")
            return False

        # Проверка на manual_ в chat_id (для вручную созданных пользователей)
        if isinstance(chat_id, str) and chat_id.startswith('manual_'):
            logging.warning(f"Попытка отправки сообщения вручную созданному пользователю: {chat_id}")
            return False

        # Преобразование chat_id в строку, если это число
        chat_id_str = str(chat_id).strip()

        # Детальное логирование для отладки
        logging.info(f"Отправка сообщения пользователю {chat_id_str}: {message[:50]}...")

        try:
            # Отправка сообщения через бота напрямую без timeout
            await bot.send_message(chat_id=chat_id_str, text=message)
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str}")
            return True
        except TelegramAPIError as api_error:
            # Обработка ошибок API Telegram
            logging.warning(f"Ошибка API Telegram: {str(api_error)}. Пробуем без HTML...")
            clean_message = re.sub(r'<[^>]*>', '', message)
            await bot.send_message(chat_id=chat_id_str, text=clean_message)
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str} (без HTML)")
            return True
        except Exception as msg_error:
            # Если первая попытка не удалась, попробуем отправить без форматирования
            logging.warning(f"Ошибка при отправке сообщения: {str(msg_error)}. Пробуем без парсинга HTML...")

            # Удаляем все HTML-теги из сообщения
            clean_message = re.sub(r'<[^>]*>', '', message)
            try:
                await bot.send_message(chat_id=chat_id_str, text=clean_message)
                logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str} (без HTML)")
                return True
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение даже без HTML: {str(e)}")
                return False

    except Exception as e:
        # Подробный лог ошибки
        logging.error(f"Ошибка отправки уведомления пользователю {chat_id}: {str(e)}")

        # Дополнительная информация для отладки
        try:
            error_type = type(e).__name__
            logging.error(f"Тип ошибки: {error_type}")

            if hasattr(e, 'with_traceback'):
                import traceback
                error_trace = ''.join(traceback.format_tb(e.__traceback__))
                logging.error(f"Трассировка: {error_trace}")
        except:
            pass

        return False

# Function to create inline keyboard for tickets
async def create_tickets_keyboard(tickets, page=0, items_per_page=3):
    # Создаем строитель клавиатуры
    builder = InlineKeyboardBuilder()

    # Получаем только часть заявок для текущей страницы
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_page_tickets = tickets[start_idx:end_idx]

    # Для каждой заявки на текущей странице добавляем кнопку
    for ticket in current_page_tickets:
        status_text = "Новая" if ticket.status == "new" else \
                    "В работе" if ticket.status == "in_progress" else \
                    "Решена" if ticket.status == "resolved" else \
                    "Неактуальна" if ticket.status == "irrelevant" else "Закрыта"

        # Форматируем дату создания
        created_date = ticket.created_at.strftime('%d.%m.%Y')

        # Ограничиваем длину темы для лучшего отображения на кнопке
        title_display = ticket.title
        if len(title_display) > 25:
            title_display = title_display[:22] + "..."

        # Создаем двустрочную кнопку с датой, темой и статусом
        button_text = f"📅 {created_date} | {status_text}\n📝 {title_display}"

        # Добавляем кнопку с колбэк-данными в отдельный ряд
        builder.row(InlineKeyboardButton(
            text=button_text,
            callback_data=f"select_ticket:{ticket.id}"
        ))

    # Добавляем кнопки для навигации по страницам
    navigation_buttons = []

    # Кнопка "Назад" (если не на первой странице)
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"page:{page-1}"
        ))

    # Номер текущей страницы
    page_count = (len(tickets) + items_per_page - 1) // items_per_page
    navigation_buttons.append(InlineKeyboardButton(
        text=f"📄 {page+1}/{page_count}",
        callback_data="page_info"
    ))

    # Кнопка "Вперед" (если не на последней странице)
    if (page + 1) * items_per_page < len(tickets):
        navigation_buttons.append(InlineKeyboardButton(
            text="Вперед ▶️",
            callback_data=f"page:{page+1}"
        ))

    # Добавляем навигационные кнопки в отдельный ряд
    builder.row(*navigation_buttons)

    return builder.as_markup()

# Function to update user's last activity timestamp
async def update_user_activity(user_id, state: FSMContext):
    """Update the user's last activity timestamp in their state data"""
    current_time = datetime.datetime.now().isoformat()
    await state.update_data(last_activity=current_time)
    logging.debug(f"Updated last activity for user {user_id} to {current_time}")

# Start command handler
@dp.message(Command("start"))
async def send_welcome(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        # Check if user exists
        user = get_user_by_chat_id(message.chat.id, user_db)

        if user:
            await message.answer(f"Привет, {user.full_name}! Вы уже зарегистрированы в системе.\n"
                               f"Используйте /new_ticket для создания новой заявки или /my_tickets для просмотра своих заявок.\n\n"
                               f"Внимание: если в чате не будет активности в течение 12 часов, активная заявка будет очищена, "
                               f"и вам потребуется выбрать её снова через команду /ticket.")
        else:
            # Send GDPR consent message
            gdpr_text = (
                "Добро пожаловать в систему поддержки ОБУЗ КГКБСМП!\n\n"
                "Перед регистрацией в системе, пожалуйста, ознакомьтесь с информацией о обработке персональных данных:\n\n"
                "1. Ваши персональные данные (ФИО, должность, отделение, номер кабинета) будут храниться в защищенной базе данных системы.\n"
                "2. Данные используются исключительно для идентификации пользователей и обработки заявок в системе.\n"
                "3. Мы не передаем ваши данные третьим лицам.\n"
                "4. Вы имеете право на удаление ваших данных из системы по запросу.\n\n"
                "Для продолжения регистрации, пожалуйста, подтвердите свое согласие на обработку персональных данных."
            )

            # Create inline keyboard for consent
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="Согласен", callback_data="gdpr_agree"))
            keyboard.add(InlineKeyboardButton(text="Отказаться", callback_data="gdpr_decline"))

            await message.answer(gdpr_text, reply_markup=keyboard.as_markup())
            await state.set_state(RegistrationStates.waiting_for_gdpr_consent)
    finally:
        user_db.close()

# Handle GDPR consent callback
@dp.callback_query(F.data.startswith("gdpr_"))
async def process_gdpr_consent(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]

    if action == "agree":
        # Сохраняем согласие на обработку ПД
        await state.update_data(privacy_consent=True, consent_date=datetime.datetime.utcnow())

        await callback.message.answer("Спасибо за согласие! Теперь продолжим процесс регистрации.\n"
                                     "Пожалуйста, введите ваше ФИО:")
        await state.set_state(RegistrationStates.waiting_for_fullname)
    else:
        await callback.message.answer("Вы отказались от обработки персональных данных.\n"
                                     "К сожалению, без этого согласия вы не можете использовать систему поддержки.\n"
                                     "Если вы измените решение, используйте команду /start для начала регистрации.")
        await state.clear()

    await callback.answer()

# Process fullname input
@dp.message(RegistrationStates.waiting_for_fullname)
async def process_fullname(message: types.Message, state: FSMContext):
    # Validate full name (only letters and spaces)
    if not all(c.isalpha() or c.isspace() for c in message.text):
        await message.answer("ФИО должно содержать только буквы и пробелы. Пожалуйста, попробуйте снова:")
        return

    await state.update_data(full_name=message.text)
    await state.set_state(RegistrationStates.waiting_for_position)
    await message.answer("Спасибо! Теперь введите вашу должность:")
    await update_user_activity(message.chat.id, state)  # Update user activity

# Process position input
@dp.message(RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    await state.update_data(position=message.text)
    await state.set_state(RegistrationStates.waiting_for_department)
    await message.answer("Спасибо! Теперь введите ваше отделение:")
    await update_user_activity(message.chat.id, state)  # Update user activity

# Process department input
@dp.message(RegistrationStates.waiting_for_department)
async def process_department(message: types.Message, state: FSMContext):
    await state.update_data(department=message.text)
    await state.set_state(RegistrationStates.waiting_for_office)
    await message.answer("Спасибо! Наконец, введите номер вашего кабинета:")
    await update_user_activity(message.chat.id, state)  # Update user activity

# Process office input and continue registration (ask for phone)
@dp.message(RegistrationStates.waiting_for_office)
async def process_office(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        await state.update_data(office=message.text)
        await message.answer("Спасибо! Теперь введите ваш номер телефона (можно пропустить, отправив '-'):")
        await state.set_state(RegistrationStates.waiting_for_phone)
        await update_user_activity(message.chat.id, state)  # Update user activity
    finally:
        user_db.close()

# Process phone input
@dp.message(RegistrationStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    # Сохраняем телефон, если он был введен
    phone = None
    if message.text != "-":
        # Проверка формата телефона (можно добавить регулярное выражение)
        phone = message.text

    await state.update_data(phone=phone)
    await message.answer("Спасибо! Последний шаг - введите ваш email (можно пропустить, отправив '-'):")
    await state.set_state(RegistrationStates.waiting_for_email)
    await update_user_activity(message.chat.id, state)  # Update user activity

# Process email input and complete registration
@dp.message(RegistrationStates.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        # Сохраняем email, если он был введен
        email = None
        if message.text != "-":
            email = message.text

        await state.update_data(email=email)
        data = await state.get_data()

        # Create new user with is_confirmed=False
        new_user = User(
            full_name=data['full_name'],
            position=data['position'],
            department=data['department'],
            office=data['office'],
            phone=data.get('phone'),
            email=data.get('email'),
            chat_id=str(message.chat.id),
            role="agent",  # Default role
            privacy_consent=data.get('privacy_consent', False),
            consent_date=data.get('consent_date'),
            is_confirmed=False,  # Добавляем флаг - требуется подтверждение администратором
            is_active=True  # Пользователь активен, но не подтвержден
        )

        user_db.add(new_user)
        user_db.commit()

        # Добавляем запись в журнал аудита о регистрации пользователя
        add_audit_log(
            user_db,
            new_user.chat_id,
            new_user.full_name,
            "user_registration",
            f"Зарегистрирован новый пользователь: {new_user.full_name}",
            "user",
            new_user.id,
            is_pdn_related=True,
            details=f"Должность: {new_user.position}, Отделение: {new_user.department}, Кабинет: {new_user.office}"
        )

        await message.answer(
            f"Регистрация успешно завершена, {new_user.full_name}!✅\n\n"
            f"⚠️ Ваш аккаунт находится на проверке у администратора. "
            f"До подтверждения профиля некоторые функции будут ограничены.\n\n"
            f"Вы сможете просматривать свой профиль по команде /profile, "
            f"но создание заявок станет доступно только после подтверждения.\n\n"
            f"Если вам срочно требуется доступ, обратитесь к администратору системы."
        )

        # Clear state and update activity
        await state.clear()
        await update_user_activity(message.chat.id, state)
    finally:
        user_db.close()

@dp.message(Command("new_ticket"))
async def new_ticket(message: types.Message, state: FSMContext):
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Проверка статуса пользователя
        status, error_msg, user = await check_user_status(message.chat.id, user_db)
        if not status:
            await message.answer(error_msg)
            return

        # Получаем список активных категорий
        categories = ticket_db.query(TicketCategory).filter(TicketCategory.is_active == True).all()

        if not categories:
            await message.answer("К сожалению, в системе не настроены категории заявок. Обратитесь к администратору.")
            return

        # Создаем клавиатуру с категориями
        keyboard = InlineKeyboardBuilder()
        for category in categories:
            keyboard.add(InlineKeyboardButton(
                text=category.name,
                callback_data=f"category:{category.id}"
            ))
        keyboard.adjust(1)  # По одной кнопке в строке

        await message.answer("Создание новой заявки. Пожалуйста, выберите категорию заявки:",
                           reply_markup=keyboard.as_markup())
        await state.set_state(TicketStates.waiting_for_category)
        await update_user_activity(message.chat.id, state)  # Update user activity

        # Логируем попытку создания тикета
        add_audit_log(
            user_db,
            str(message.chat.id),
            user.full_name,
            "start_ticket_creation",
            "Пользователь начал создание новой заявки",
            "ticket"
        )
    finally:
        user_db.close()
        ticket_db.close()

# Handle category selection callback
@dp.callback_query(F.data.startswith("category:"))
async def process_category_selection(callback: CallbackQuery, state: FSMContext):
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Extract category ID from callback data
        category_id = callback.data.split(":")[1]

        # Get the category name
        category = ticket_db.query(TicketCategory).filter(TicketCategory.id == category_id).first()
        if not category:
            await callback.message.answer("Ошибка: выбранная категория не найдена.")
            await callback.answer()
            return

        # Save category selection to state
        await state.update_data(category_id=category_id, category_name=category.name)

        # Ask for ticket title
        await callback.message.answer(f"Вы выбрали категорию: <b>{category.name}</b>.\n\nТеперь введите заголовок заявки:", parse_mode="HTML")
        await state.set_state(TicketStates.waiting_for_title)

        # Check user status
        status, _, user = await check_user_status(callback.message.chat.id, user_db)
        if status and user:
            # Audit log
            add_audit_log(
                ticket_db,
                str(callback.message.chat.id),
                user.full_name,
                "select_ticket_category",
                f"Пользователь выбрал категорию заявки: {category.name}",
                "ticket_category",
                category_id
            )

        await callback.answer()
        await update_user_activity(callback.message.chat.id, state)
    finally:
        user_db.close()
        ticket_db.close()

# Команда для выбора заявки
@dp.message(Command("ticket"))
async def select_ticket(message: types.Message, state: FSMContext):
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Проверка статуса пользователя
        status, error_msg, user = await check_user_status(message.chat.id, user_db)
        if not status:
            await message.answer(error_msg)
            return

        # Получаем все заявки пользователя, отсортированные по дате создания (новые сверху)
        tickets = ticket_db.query(Ticket).filter(
            Ticket.creator_chat_id == str(message.chat.id)
        ).order_by(Ticket.created_at.desc()).all()

        if not tickets:
            await message.answer("У вас нет заявок. Используйте /new_ticket для создания новой заявки.")
            return

        # Сохраняем все заявки в состоянии пользователя для дальнейшей пагинации
        ticket_data = [{
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "resolved_at": t.updated_at.isoformat() if t.status in ["resolved", "irrelevant", "closed"] else None
        } for t in tickets]
        await state.update_data(tickets=ticket_data, current_page=0)

        # Создаем клавиатуру с пагинацией
        keyboard = await create_tickets_keyboard(tickets, page=0)

        # Формируем информативное сообщение
        total_tickets = len(tickets)
        active_tickets = sum(1 for t in tickets if t.status in ["new", "in_progress"])

        message_text = (
            f"<b>Ваши заявки ({total_tickets})</b>\n"
            f"Активных заявок: {active_tickets}\n\n"
            f"Выберите заявку из списка ниже:"
        )

        await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await update_user_activity(message.chat.id, state)  # Update user activity

    finally:
        user_db.close()
        ticket_db.close()

# My tickets command handler
@dp.message(Command("my_tickets"))
async def show_my_tickets(message: types.Message, state: FSMContext):
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Проверка статуса пользователя
        status, error_msg, user = await check_user_status(message.chat.id, user_db)
        if not status:
            await message.answer(error_msg)
            return

        # Get user's tickets
        tickets = ticket_db.query(Ticket).filter(Ticket.creator_chat_id == str(message.chat.id)).order_by(Ticket.created_at.desc()).all()

        if not tickets:
            await message.answer("У вас пока нет заявок. Используйте /new_ticket для создания новой заявки.")
            return

        # Format and send tickets
        response = "<b>Ваши заявки:</b>\n\n"
        for ticket in tickets:
            status_text = "Новая" if ticket.status == "new" else \
                        "В работе" if ticket.status == "in_progress" else \
                        "Решена" if ticket.status == "resolved" else \
                        "Неактуальна" if ticket.status == "irrelevant" else "Закрыта"

            response += f"<b>{ticket.title}</b>\n"
            response += f"Статус: {status_text}\n"
            response += f"Создано: {ticket.created_at.strftime('%d.%m.%Y %H:%M')}\n"

            if ticket.status in ["resolved", "irrelevant", "closed"]:
                response += f"Закрыто: {ticket.updated_at.strftime('%d.%m.%Y %H:%M')}\n"

            response += f"ID: #{ticket.id}\n"
            response += "\n"

        await message.answer(response, parse_mode="HTML")
        await update_user_activity(message.chat.id, state)  # Update user activity
    finally:
        user_db.close()
        ticket_db.close()

# Help command handler
@dp.message(Command("help"))
async def show_help(message: types.Message, state: FSMContext):
    await message.answer("Список доступных команд:\n"
                      "/start - Начать работу с ботом или зарегистрироваться\n"
                      "/new_ticket - Создать новую заявку\n"
                      "/my_tickets - Просмотреть мои заявки\n"
                      "/ticket - Выбрать активную заявку\n"
                      "/profile - Показать информацию о моем профиле\n"
                      "/pdn_policy - Политика обработки персональных данных\n"
                      "/help - Показать эту справку\n\n"
                      "Внимание: если в чате не будет активности в течение 12 часов, "
                      "активная заявка будет очищена, и вам потребуется выбрать её снова через команду /ticket.")
    await update_user_activity(message.chat.id, state)  # Update user activity

# Команда для отображения политики обработки персональных данных
@dp.message(Command("pdn_policy"))
async def show_pdn_policy(message: types.Message, state: FSMContext):
    try:
        # Путь к файлу с текстом политики
        policy_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdn_policy.txt")

        # Проверяем существование файла
        if os.path.exists(policy_file_path):
            # Читаем текст из файла
            with open(policy_file_path, "r", encoding="utf-8") as f:
                policy_text = f.read()

            # Форматируем текст для Telegram (добавляем HTML-форматирование)
            lines = policy_text.split('\n')
            if lines:
                formatted_text = f"<b>{lines[0]}</b>\n\n" + "\n".join(lines[1:])
            else:
                formatted_text = policy_text
            await message.answer(formatted_text, parse_mode="HTML")
        else:
            # Если файл не найден, используем встроенный текст
            gdpr_text = (
                "<b>Политика обработки персональных данных</b>\n\n"
                "В соответствии с требованиями Федерального закона от 27.07.2006 г. № 152-ФЗ «О персональных данных»:\n\n"
                "1. Ваши персональные данные (ФИО, должность, отделение, номер кабинета, телефон, email) "
                "хранятся в защищенной базе данных системы поддержки ОБУЗ КГКБСМП.\n\n"
                "2. Данные используются исключительно для идентификации пользователей и обработки заявок в системе поддержки.\n\n"
                "3. Мы не передаем ваши данные третьим лицам без вашего согласия, за исключением случаев, "
                "предусмотренных законодательством РФ.\n\n"
                "4. Вы имеете право на доступ к своим персональным данным, их обновление, удаление или ограничение обработки "
                "по запросу к администратору системы.\n\n"
                "5. Система хранит дату и время вашего согласия с политикой обработки персональных данных.\n\n"
                "6. Политика может быть изменена в соответствии с требованиями законодательства. "
                "В случае существенных изменений, вам будет предложено ознакомиться с обновленной версией.\n\n"
                "7. По всем вопросам относительно обработки ваших персональных данных вы можете обратиться "
                "к администратору системы поддержки.\n\n"
                "Используя бота поддержки ОБУЗ КГКБСМП, вы подтверждаете своё согласие с данной политикой."
            )
            await message.answer(gdpr_text, parse_mode="HTML")

            # Логируем ошибку
            logging.warning(f"Файл политики обработки ПДн не найден: {policy_file_path}")

    except Exception as e:
        logging.error(f"Ошибка при чтении файла политики обработки ПДн: {str(e)}")
        await message.answer("Произошла ошибка при получении текста политики обработки ПДн. Попробуйте позднее.")

    await update_user_activity(message.chat.id, state)  # Update user activity

# Profile command handler - показывает информацию о пользователе
@dp.message(Command("profile"))
async def show_profile(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        # Проверяем, зарегистрирован ли пользователь (без проверки статуса)
        user = get_user_by_chat_id(message.chat.id, user_db)

        if not user:
            await message.answer("Вы не зарегистрированы в системе. Используйте /start для регистрации.")
            return

        # Форматируем дату согласия
        consent_date_str = "Не указана"
        if user.consent_date:
            consent_date_str = user.consent_date.strftime('%d.%m.%Y %H:%M')

        # Форматируем дату создания профиля
        created_date_str = user.created_at.strftime('%d.%m.%Y %H:%M')

        # Получаем статусы активности и подтверждения
        confirmation_status = "✅ Подтвержден" if user.is_confirmed else "❌ Ожидает подтверждения"
        active_status = "✅ Активен" if user.is_active else "❌ Заблокирован"

        # Форматируем телефон и email, если они есть
        phone_str = user.phone if user.phone else "Не указан"
        email_str = user.email if user.email else "Не указан"

        # Формируем сообщение с информацией о профиле
        profile_text = (
            f"📋 <b>Ваш профиль</b>\n\n"
            f"👤 <b>ФИО:</b> {user.full_name}\n"
            f"🏢 <b>Должность:</b> {user.position}\n"
            f"🏥 <b>Отделение:</b> {user.department}\n"
            f"🚪 <b>Кабинет:</b> {user.office}\n"
            f"📱 <b>Телефон:</b> {phone_str}\n"
            f"📧 <b>Email:</b> {email_str}\n\n"
            f"🔐 <b>Статус профиля:</b> {active_status}, {confirmation_status}\n"
            f"📅 <b>Дата регистрации:</b> {created_date_str}\n"
            f"✍️ <b>Согласие на обработку ПДн:</b> {'Получено' if user.privacy_consent else 'Не получено'}\n"
            f"📆 <b>Дата согласия:</b> {consent_date_str}\n"
            f"👑 <b>Роль:</b> {'Администратор' if user.role == 'admin' else 'Куратор' if user.role == 'curator' else 'Пользователь'}\n"
        )

        # Добавляем сообщение с рекомендациями, если аккаунт не подтвержден или заблокирован
        if not user.is_confirmed:
            profile_text += (
                f"\n⚠️ <b>Внимание:</b> Ваш аккаунт ожидает подтверждения администратором. "
                f"До подтверждения вы не сможете создавать заявки и писать сообщения."
            )
        elif not user.is_active:
            profile_text += (
                f"\n⛔ <b>Внимание:</b> Ваш аккаунт заблокирован администратором. "
                f"Для выяснения причин обратитесь к администратору системы."
            )

        await message.answer(profile_text, parse_mode="HTML")
        await update_user_activity(message.chat.id, state)  # Update user activity

        # Логируем просмотр профиля в аудит
        add_audit_log(
            user_db,
            str(message.chat.id),
            user.full_name,
            "view_profile",
            f"Пользователь просмотрел свой профиль",
            "user",
            user.id,
            is_pdn_related=True
        )

    finally:
        user_db.close()

# Background task to check for inactive users and clear their active tickets
async def check_inactive_users():
    try:
        while True:
            logging.info("Checking for inactive users...")

            try:
                # Safety check to ensure storage is initialized
                if not hasattr(dp, 'storage') or not dp.storage:
                    logging.warning("Storage is not properly initialized. Skipping inactive user check.")
                    await asyncio.sleep(3600)
                    continue

                # Access the internal data directly if available
                if hasattr(dp.storage, 'data') and dp.storage.data:
                    # This approach works for MemoryStorage which stores data in a dictionary
                    states_data = dp.storage.data
                    current_time = datetime.datetime.now()

                    for user_id, user_data in states_data.items():
                        if isinstance(user_data, dict) and 'data' in user_data:
                            state_data = user_data['data']
                            active_ticket_id = state_data.get('active_ticket_id')
                            last_activity = state_data.get('last_activity')

                            if active_ticket_id and last_activity:
                                # Parse last_activity from string to datetime
                                try:
                                    last_activity_time = datetime.datetime.fromisoformat(last_activity)
                                    inactive_hours = (current_time - last_activity_time).total_seconds() / 3600

                                    # If inactive for 12+ hours, clear the active ticket
                                    if inactive_hours >= 12:
                                        logging.info(f"User {user_id} has been inactive for {inactive_hours:.2f} hours. Clearing active ticket.")
                                        # Update the data directly in the storage
                                        state_data['active_ticket_id'] = None

                                        # Try to notify the user
                                        try:
                                            await bot.send_message(
                                                chat_id=user_id,
                                                text="Из-за длительного отсутствия активности (более 12 часов) ваш чат был очищен. "
                                                     "Для продолжения работы с заявкой, пожалуйста, выберите её снова через команду /ticket"
                                            )
                                        except Exception as e:
                                            logging.error(f"Failed to notify user {user_id} about chat clearing: {str(e)}")
                                except (ValueError, TypeError) as e:
                                    logging.error(f"Error parsing last_activity for user {user_id}: {str(e)}")
                else:
                    logging.warning("Storage doesn't have 'data' attribute or it's empty. Unable to check inactive users.")
            except Exception as e:
                logging.error(f"Error accessing storage data: {str(e)}")

            # Check every hour
            await asyncio.sleep(3600)
    except Exception as e:
        logging.error(f"Error in inactive users check task: {str(e)}")
        if hasattr(e, '__traceback__'):
            import traceback
            error_trace = ''.join(traceback.format_tb(e.__traceback__))
            logging.error(f"Traceback: {error_trace}")

# Function to start bot
async def start_bot():
    # Create uploads directory if it doesn't exist
    if not os.path.exists('uploads'):
        os.makedirs('uploads')

    # Start the background task for checking inactive users
    asyncio.create_task(check_inactive_users())

    # Start polling
    await dp.start_polling(bot)

# Main function to run the bot
def run_bot():
    """Start the Telegram bot"""
    if not _DEPENDENCIES_LOADED:
        logging.error("Telegram bot could not start due to missing dependencies.")
        logging.error("Please install required packages: pip install aiogram sqlalchemy nest_asyncio python-dotenv requests")
        return

    try:
        asyncio.run(start_bot())
    except Exception as e:
        logging.error(f"Error starting bot: {str(e)}")
