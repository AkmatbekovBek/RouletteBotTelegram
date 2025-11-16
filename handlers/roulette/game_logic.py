import random
import asyncio
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Tuple, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .config import CONFIG
from handlers.roulette_logs import RouletteLogger


class RouletteGame:
    def __init__(self):
        self.numbers = CONFIG.NUMBERS
        self._rng = random.Random()
        self.standard_groups = {
            "1-3": {1, 2, 3}, "4-6": {4, 5, 6},
            "7-9": {7, 8, 9}, "10-12": {10, 11, 12}
        }

    def spin(self) -> int:
        return self._rng.choice(self.numbers)

    def get_color(self, number: int) -> str:
        if number == 0:
            return "зеленое"
        return "красное" if number in CONFIG.RED_NUMBERS else "черное"

    def get_color_emoji(self, number: int) -> str:
        if number == 0:
            return "🟢"
        return "🔴" if number in CONFIG.RED_NUMBERS else "⚫"

    def check_bet(self, bet_type: str, bet_value: Any, result: int) -> bool:
        try:
            if bet_type == "число":
                num_value = int(bet_value) if isinstance(bet_value, str) else bet_value
                return num_value == result
            elif bet_type == "цвет":
                return (
                    (bet_value == "красное" and result in CONFIG.RED_NUMBERS) or
                    (bet_value == "черное" and result in CONFIG.BLACK_NUMBERS) or
                    (bet_value == "зеленое" and result == 0)
                )
            elif bet_type == "группа":
                if bet_value in self.standard_groups:
                    return result in self.standard_groups[bet_value]
                if isinstance(bet_value, str) and '-' in bet_value:
                    try:
                        start, end = map(int, bet_value.split('-'))
                        if 0 <= start <= 12 and 0 <= end <= 12 and start < end:
                            return start <= result <= end
                    except (ValueError, TypeError):
                        return False
            return False
        except (ValueError, TypeError):
            return False

    def get_multiplier(self, bet_type: str, bet_value: Any) -> Decimal:
        if bet_type == "число":
            return CONFIG.PAYOUTS["число"]
        elif bet_type == "цвет":
            color_key = f"цвет_{bet_value}"
            return CONFIG.PAYOUTS.get(color_key, Decimal('1.0'))
        elif bet_type == "группа":
            if isinstance(bet_value, str) and '-' in bet_value:
                try:
                    start, end = map(int, bet_value.split('-'))
                    if 0 <= start <= 12 and 0 <= end <= 12 and start < end:
                        count = end - start + 1
                        return (CONFIG.PAYOUTS["число"] / Decimal(count)).quantize(
                            Decimal('0.001'), rounding=ROUND_DOWN
                        )
                except (ValueError, TypeError):
                    pass
            return CONFIG.PAYOUTS["группа_стандарт"]
        return Decimal('1.0')


class RouletteKeyboard:
    @staticmethod
    def create_roulette_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(row_width=4).row(
            InlineKeyboardButton("1-3", callback_data="bet:1-3"),
            InlineKeyboardButton("4-6", callback_data="bet:4-6"),
            InlineKeyboardButton("7-9", callback_data="bet:7-9"),
            InlineKeyboardButton("10-12", callback_data="bet:10-12"),
        ).row(
            InlineKeyboardButton("1к 🔴", callback_data="quick:1000_red"),
            InlineKeyboardButton("1к ⚫", callback_data="quick:1000_black"),
            InlineKeyboardButton("1к 🟢", callback_data="quick:1000_green"),
        ).row(
            InlineKeyboardButton("Повторить", callback_data="action:repeat"),
            InlineKeyboardButton("Удвоить", callback_data="action:double"),
            InlineKeyboardButton("Крутить", callback_data="action:spin"),
        )


class AntiFloodManager:
    __slots__ = ('user_last_spin', 'user_spin_count', 'user_spin_reset_time')

    def __init__(self):
        self.user_last_spin: Dict[Tuple[int, int], float] = {}
        self.user_spin_count: Dict[Tuple[int, int], int] = {}
        self.user_spin_reset_time: Dict[Tuple[int, int], float] = {}

    def can_spin(self, user_id: int, chat_id: int) -> Tuple[bool, float]:
        key = (user_id, chat_id)
        current_time = asyncio.get_event_loop().time()
        if key in self.user_last_spin:
            last_spin_time = self.user_last_spin[key]
            elapsed = current_time - last_spin_time
            if elapsed < CONFIG.MIN_SPIN_INTERVAL:
                return False, CONFIG.MIN_SPIN_INTERVAL - elapsed
        if key not in self.user_spin_count:
            self.user_spin_count[key] = 0
            self.user_spin_reset_time[key] = current_time
        if current_time - self.user_spin_reset_time[key] > CONFIG.RESET_INTERVAL:
            self.user_spin_count[key] = 0
            self.user_spin_reset_time[key] = current_time
        if self.user_spin_count[key] >= CONFIG.MAX_SPINS_PER_MINUTE:
            time_until_reset = CONFIG.RESET_INTERVAL - (current_time - self.user_spin_reset_time[key])
            return False, time_until_reset
        self.user_last_spin[key] = current_time
        self.user_spin_count[key] += 1
        return True, 0

    def cleanup_old_entries(self):
        current_time = asyncio.get_event_loop().time()
        old_keys = [
            key for key, timestamp in self.user_last_spin.items()
            if current_time - timestamp > CONFIG.CLEANUP_INTERVAL
        ]
        for key in old_keys:
            self.user_last_spin.pop(key, None)
            self.user_spin_count.pop(key, None)
            self.user_spin_reset_time.pop(key, None)