# handlers/donate/keyboards.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .config import DONATE_ITEMS, BONUS_AMOUNT, BONUS_COOLDOWN_HOURS, SUPPORT_USERNAME
from database.crud import DonateRepository
from .utils import db_session

def _get_bonus_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для раздела бонусов"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("💰 Бонусы за привилегии", callback_data="privilege_bonus"),
        InlineKeyboardButton("⬅️ Назад в донат", callback_data="back_to_donate")
    )
    return keyboard

def _get_privilege_bonus_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для раздела бонусов за привилегии"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🎁 Получить бонусы", callback_data="privilege_bonus"),
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_donate")
    )
    return keyboard

def _get_purchase_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения покупки"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("💳 Перейти к оплате", url=f"https://t.me/{SUPPORT_USERNAME}"), # Используем ссылку, а не callback
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_donate")
    )
    return keyboard

def _get_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для возврата"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_donate"))
    return keyboard

def _create_donate_keyboard(user_id: int = None) -> InlineKeyboardMarkup:
    """Создает клавиатуру доната с учетом купленных привилегий"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    try:
        with db_session() as db:
            # Получаем все покупки пользователя
            user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
            purchased_ids = [p.item_id for p in user_purchases]

            # Кнопки для всех товаров доната
            for item in DONATE_ITEMS:
                if item["id"] in purchased_ids:
                    # Привилегия уже куплена - ИСПОЛЬЗУЕМ СТАРЫЙ ФОРМАТ callback
                    button_text = f"✅ {item['name']} (куплено)"
                    callback_data = f"donate_already_bought_{item['id']}"
                else:
                    # Привилегия доступна для покупки - ИСПОЛЬЗУЕМ СТАРЫЙ ФОРМАТ callback
                    button_text = f"{item['name']} - {item['price']}"
                    callback_data = f"donate_buy_{item['id']}"

                keyboard.add(InlineKeyboardButton(text=button_text, callback_data=callback_data))

            # Кнопка "Бонус"
            keyboard.add(InlineKeyboardButton(
                text=f"🎁 Бонус ({BONUS_AMOUNT} монет / {BONUS_COOLDOWN_HOURS}ч)",
                callback_data="daily_bonus"
            ))
            # Кнопка "Бонусы за привилегии"
            keyboard.add(InlineKeyboardButton(
                text="💰 Бонусы за привилегии",
                callback_data="privilege_bonus"
            ))
    except Exception as e:
        # Логирование может потребовать импорта logger
        # logger.error(f"Error creating donate keyboard: {e}")
        print(f"Error creating donate keyboard: {e}") # Временный вывод, замените на logger
    return keyboard