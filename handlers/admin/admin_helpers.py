# admin_helpers.py

import logging
from contextlib import contextmanager
from pathlib import Path
from aiogram import types
from aiogram.dispatcher.filters.state import StatesGroup, State
from database import get_db

logger = logging.getLogger(__name__)

class GiftAdminStates(StatesGroup):
    """Состояния FSM для управления подарками"""
    waiting_for_gift_name = State()
    waiting_for_gift_sticker = State()
    waiting_for_gift_price = State()
    waiting_for_gift_compliment = State()

@contextmanager
def db_session():
    """Контекстный менеджер для безопасной работы с БД"""
    session = None
    try:
        session = next(get_db())
        yield session
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        if session:
            session.rollback()
        raise
    finally:
        if session:
            session.close()

def check_admin_sync(user_id: int) -> bool:
    """Проверяет права администратора (синхронная версия для получения статуса из БД)."""
    from database.crud import UserRepository
    from .admin_constants import ADMIN_IDS
    # Быстрая проверка основных админов
    if user_id in ADMIN_IDS:
        return True
    # Проверка админов из БД
    with db_session() as db:
        try:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            return user is not None and user.is_admin
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            return False

async def check_admin_async(message: types.Message) -> bool:
    """Проверяет права администратора и отправляет сообщение об ошибке."""
    user_id = message.from_user.id
    is_admin = check_admin_sync(user_id)
    if not is_admin:
        await message.answer("❌ У вас нет прав администратора")
    return is_admin

def get_all_admins_from_db() -> list[int]:
    """Получает всех администраторов из БД."""
    from database.crud import UserRepository
    with db_session() as db:
        try:
            admin_users = UserRepository.get_admin_users(db)
            return [user.telegram_id for user in admin_users]
        except Exception as e:
            logger.error(f"Error getting admins from DB: {e}")
            return []

def format_number(number: int) -> str:
    """Форматирует числа с разделителями тысяч"""
    return f"{number:,}".replace(",", ".")

def get_gift_cancel_keyboard() -> types.InlineKeyboardMarkup:
    """Клавиатура для отмены операций с подарками"""
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_gift_cancel")
    )

def get_gift_management_keyboard() -> types.InlineKeyboardMarkup:
    """Клавиатура для управления подарками"""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_gift_add_more"),
        types.InlineKeyboardButton("📊 Список подарков", callback_data="admin_gift_list_cmd")
    )
    keyboard.add(
        types.InlineKeyboardButton("🗑️ Удалить подарок", callback_data="admin_gift_delete_start")
    )
    return keyboard

def get_broadcast_cancel_keyboard(broadcast_type: str = "") -> types.InlineKeyboardMarkup:
    """Клавиатура для отмены рассылки"""
    callback_data = f"cancel_broadcast{'_' + broadcast_type if broadcast_type else ''}"
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("❌ Отменить рассылку", callback_data=callback_data)
    )