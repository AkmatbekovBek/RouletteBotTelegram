# utils.py
import asyncio
from datetime import datetime
from typing import List, Tuple, Optional, Any
from decimal import Decimal, ROUND_DOWN
from aiogram import types
from aiogram.utils.exceptions import BadRequest
from config import bot
from main import logger

from .validators import UserFormatter
from .config import CONFIG


# =============================================================================
# ФОРМАТИРОВАНИЕ ИМЁН
# =============================================================================

def get_display_name(user: types.User) -> str:
    """Возвращает отображаемое имя пользователя (без ссылки)"""
    if user.first_name:
        return user.first_name
    elif user.username:
        return f"@{user.username}"
    else:
        return f"Пользователь {user.id}"


def format_username_with_link(user_id: int, username: str) -> str:
    """Форматирует имя пользователя со ссылкой tg://user?id=..."""
    return UserFormatter.get_user_link(user_id, username)


def get_plain_username(username: str) -> str:
    """Возвращает экранированное имя без ссылки"""
    return UserFormatter.get_plain_name(username)


# =============================================================================
# УДАЛЕНИЕ СООБЩЕНИЙ
# =============================================================================

async def delete_bet_messages(chat_id: int, bet_message_ids: List[int]):
    """Удаляет список сообщений ставок (без доступа к UserBetSession)"""
    if not bet_message_ids:
        return
    delete_tasks = [
        bot.delete_message(chat_id=chat_id, message_id=msg_id)
        for msg_id in bet_message_ids
    ]
    results = await asyncio.gather(*delete_tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.debug(f"[Utils] Не удалось удалить сообщение: {result}")


async def delete_spin_message(chat_id: int, spin_message_id: Optional[int]):
    """Удаляет сообщение с анимацией прокрутки"""
    if not spin_message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=spin_message_id)
    except Exception as e:
        logger.debug(f"[Utils] Не удалось удалить spin-сообщение: {e}")


# =============================================================================
# ФОРМАТИРОВАНИЕ И ПОЛЕЗНЫЕ ФУНКЦИИ
# =============================================================================

def format_wait_time(wait_time: float) -> str:
    """Форматирует время ожидания в человекочитаемый вид"""
    if wait_time > 60:
        wait_minutes = int(wait_time // 60)
        wait_seconds = int(wait_time % 60)
        return f"{wait_minutes} мин {wait_seconds} сек"
    return f"{wait_time:.1f} секунд"


def get_bet_display_value(bet_type: str, bet_value: Any) -> str:
    """Возвращает отображаемое значение ставки с эмодзи (для удвоения и т.п.)"""
    if bet_type == "цвет":
        color_emojis = {"красное": "🔴", "черное": "⚫", "зеленое": "🟢"}
        return color_emojis.get(bet_value, str(bet_value))
    return str(bet_value)


def calculate_bet_result(game, bet, result: int) -> Tuple[int, int]:
    """
    Рассчитывает результат ставки (чистый выигрыш/проигрыш и выплату).
    :param game: экземпляр RouletteGame
    :param bet: Bet
    :param result: выпавшее число
    :return: (net_profit, total_payout)
    """
    multiplier = game.get_multiplier(bet.type, bet.value)
    is_win = game.check_bet(bet.type, bet.value, result)
    if is_win:
        gross_profit = int(bet.amount * multiplier)
        total_payout = gross_profit
        return gross_profit, total_payout
    else:
        return -bet.amount, 0


# =============================================================================
# ПАРСИНГ И ВА-БАНК
# =============================================================================

def parse_vabank_bet(bet_value: str) -> Optional[Tuple[str, Any]]:
    """Парсит тип и значение для ва-банк ставки"""
    color_map = {
        'к': 'красное', 'кр': 'красное', 'крас': 'красное', 'red': 'красное',
        'ч': 'черное', 'чер': 'черное', 'black': 'черное',
        'з': 'зеленое', 'зел': 'зеленое', 'green': 'зеленое', '0': 'зеленое'
    }
    bet_value = bet_value.lower().strip()

    # Число
    if bet_value.isdigit() and 0 <= int(bet_value) <= 12:
        return "число", int(bet_value)

    # Цветы (сокращения + полные)
    if bet_value in color_map:
        return "цвет", color_map[bet_value]
    if bet_value in ['красное', 'черное', 'зеленое']:
        return "цвет", bet_value

    # Группы
    group_map = {
        '1-3': '1-3', '13': '1-3',
        '4-6': '4-6', '46': '4-6',
        '7-9': '7-9', '79': '7-9',
        '10-12': '10-12', '1012': '10-12'
    }
    if bet_value in group_map:
        return "группа", group_map[bet_value]
    elif '-' in bet_value:
        try:
            start, end = map(int, bet_value.split('-'))
            if 0 <= start <= 12 and 0 <= end <= 12 and start <= end:
                return "группа", f"{start}-{end}"
        except (ValueError, TypeError):
            pass

    return None