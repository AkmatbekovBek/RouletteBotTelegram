import re
import random
import asyncio
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
from decimal import Decimal, ROUND_DOWN
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import BadRequest

from config import bot
from database import get_db
from database.crud import UserRepository, RouletteRepository
from handlers.roulette_limit import roulette_limit_manager
from handlers.roulette_logs import RouletteLogger
from main import logger


# =============================================================================
# КОНФИГУРАЦИЯ И КОНСТАНТЫ
# =============================================================================

@dataclass(frozen=True)
class RouletteConfig:
    """Конфигурационные параметры рулетки"""
    MIN_BET: int = 1000
    MAX_BET: int = 100_000_000_000_000_000_000
    MAX_TOTAL_BETS_PER_USER: int = 100_000_000_000_000_000_000
    SPIN_DELAY: int = 3
    MAX_GAME_LOGS: int = 26
    MIN_SPIN_INTERVAL: int = 3
    MAX_SPINS_PER_MINUTE: int = 10
    RESET_INTERVAL: int = 60
    CLEANUP_INTERVAL: int = 300

    # Коэффициенты выплат
    PAYOUTS: Dict[str, Decimal] = None

    # Поддерживаемые числа и цвета
    NUMBERS: Tuple[int, ...] = tuple(range(0, 13))
    RED_NUMBERS: frozenset = frozenset({1, 3, 5, 7, 9, 11})
    BLACK_NUMBERS: frozenset = frozenset({2, 4, 6, 8, 10, 12})

    def __post_init__(self):
        # Инициализация PAYOUTS после создания объекта
        if self.PAYOUTS is None:
            object.__setattr__(self, 'PAYOUTS', {
                "число": Decimal('12.0'),
                "цвет_красное": Decimal('2.0'),
                "цвет_черное": Decimal('2.0'),
                "цвет_зеленое": Decimal('12.0'),
                "группа_стандарт": Decimal('4.333')
            })


# Создаем экземпляр конфигурации
CONFIG = RouletteConfig()


# =============================================================================
# УТИЛИТЫ ДЛЯ ФОРМАТИРОВАНИЯ
# =============================================================================

class UserFormatter:
    """Утилиты для форматирования имен пользователей"""

    ESCAPE_CHARS = r'_*[]()~`>#+-=|{}.!'

    @staticmethod
    def escape_markdown(text: str) -> str:
        """Экранирует специальные символы Markdown"""
        return ''.join(f'\\{char}' if char in UserFormatter.ESCAPE_CHARS else char
                       for char in text)

    @staticmethod
    def get_user_link(user_id: int, display_name: str) -> str:
        """Создает ссылку на профиль пользователя"""
        safe_name = UserFormatter.escape_markdown(display_name)
        return f"[{safe_name}](tg://user?id={user_id})"

    @staticmethod
    def format_username(user: types.User) -> str:
        """Форматирует имя пользователя со ссылкой"""
        display_name = UserFormatter._get_display_name(user)
        return UserFormatter.get_user_link(user.id, display_name)

    @staticmethod
    def get_plain_name(display_name: str) -> str:
        """Возвращает экранированное имя без ссылки"""
        return UserFormatter.escape_markdown(display_name)

    @staticmethod
    def _get_display_name(user: types.User) -> str:
        """Возвращает отображаемое имя пользователя"""
        # Убираем "Аноним" и всегда показываем имя
        if user.first_name:
            return user.first_name
        elif user.username:
            return f"@{user.username}"
        else:
            # Если нет ни имени, ни username, используем ID
            return f"Пользователь {user.id}"


class DatabaseManager:
    """Менеджер для работы с базой данных"""

    @staticmethod
    @asynccontextmanager
    async def db_session():
        """Асинхронный контекстный менеджер для БД"""
        db = next(get_db())
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    async def update_users_batch(user_updates: Dict[int, int], user_stats_updates: Dict[int, Tuple]):
        """Пакетное обновление пользователей в БД"""
        async with DatabaseManager.db_session() as db:
            try:
                # Обновляем балансы пользователей
                for user_id, new_coins in user_updates.items():
                    user = UserRepository.get_user_by_telegram_id(db, user_id)
                    if user:
                        user.coins = new_coins

                # Обновляем статистику
                for user_id, stats in user_stats_updates.items():
                    user = UserRepository.get_user_by_telegram_id(db, user_id)
                    if user:
                        win_coins, defeat_coins, max_win, min_win = stats

                        if win_coins is not None:
                            user.win_coins = win_coins
                        if defeat_coins is not None:
                            user.defeat_coins = defeat_coins
                        if max_win is not None:
                            user.max_win_coins = max_win
                        if min_win is not None:
                            user.min_win_coins = min_win

                # Коммит изменений
                db.commit()
                logger.info(f"✅ Пакетное обновление: {len(user_updates)} пользователей")

            except Exception as e:
                db.rollback()
                logger.error(f"❌ Ошибка пакетного обновления БД: {e}")
                raise

# =============================================================================
# МОДЕЛИ ДАННЫХ
# =============================================================================

@dataclass
class Bet:
    """Модель ставки пользователя"""
    amount: int
    type: str
    value: Any
    username: str
    user_id: int
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self) -> str:
        return f"{self.amount} на {self.value} ({self.type})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": self.amount,
            "type": self.type,
            "value": self.value,
            "username": self.username,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat()
        }

    def is_same_bet(self, other_bet: 'Bet') -> bool:
        """Проверяет, является ли ставка такой же (тип и значение совпадают)"""
        return self.type == other_bet.type and self.value == other_bet.value


class UserBetSession:
    """Сессия ставок пользователя"""

    __slots__ = ('user_id', 'username', 'bets', 'total_amount', 'last_update', 'bet_message_ids')

    def __init__(self, user_id: int, username: str):
        self.user_id = user_id
        self.username = username
        self.bets: List[Bet] = []
        self.total_amount = 0
        self.last_update = datetime.now()
        self.bet_message_ids: List[int] = []

    def add_bet(self, bet: Bet) -> bool:
        """Добавляет ставку, объединяя с существующей если такая уже есть"""
        for existing_bet in self.bets:
            if existing_bet.is_same_bet(bet):
                existing_bet.amount += bet.amount
                self.total_amount += bet.amount
                self.last_update = datetime.now()
                return True

        self.bets.append(bet)
        self.total_amount += bet.amount
        self.last_update = datetime.now()
        return True

    def clear_bets(self) -> int:
        """Очищает все ставки и возвращает общую сумму"""
        total = self.total_amount
        self.bets.clear()
        self.total_amount = 0
        self.last_update = datetime.now()
        return total

    @property
    def has_bets(self) -> bool:
        """Проверяет есть ли активные ставки"""
        return bool(self.bets)

    def get_bets_info(self) -> str:
        """Возвращает текстовое описание всех ставок"""
        if not self.bets:
            return "Нет активных ставок"

        lines = []
        for bet in self.bets:
            plain_name = UserFormatter.get_plain_name(bet.username)
            lines.append(f"{plain_name} {bet.amount} на {bet.value}")
        lines.append(f"💰 Общая сумма: {self.total_amount}")

        return "\n".join(lines)


class ChatSession:
    """Сессия игры для отдельного чата"""

    __slots__ = ('chat_id', 'user_sessions', 'waiting_for_bet', 'last_user_bets',
                 'created_at', 'last_spin', 'spin_message_id', 'game_logs',
                 'is_doubling_operation', 'is_spinning', 'spin_lock')

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.user_sessions: Dict[int, UserBetSession] = {}
        self.waiting_for_bet: Dict[int, Tuple[str, str]] = {}
        self.last_user_bets: Dict[int, List[Tuple]] = {}
        self.created_at = datetime.now()
        self.last_spin = None
        self.spin_message_id: Optional[int] = None
        self.game_logs: List[Dict] = []
        self.is_doubling_operation = False
        self.is_spinning = False
        self.spin_lock = asyncio.Lock()

    def get_user_session(self, user_id: int, username: str) -> UserBetSession:
        """Получает или создает сессию пользователя"""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = UserBetSession(user_id, username)
        else:
            self.user_sessions[user_id].username = username
        return self.user_sessions[user_id]

    def clear_user_session(self, user_id: int) -> int:
        """Очищает сессию пользователя и возвращает сумму"""
        if user_id in self.user_sessions:
            session = self.user_sessions[user_id]
            total = session.total_amount
            del self.user_sessions[user_id]
            return total
        return 0

    @property
    def active_users(self) -> Dict[int, UserBetSession]:
        """Возвращает пользователей с активными ставками"""
        return {uid: session for uid, session in self.user_sessions.items()
                if session.has_bets}


class SessionManager:
    """Менеджер сессий для разных чатов"""

    def __init__(self):
        self.sessions: Dict[int, ChatSession] = {}

    def get_session(self, chat_id: int) -> ChatSession:
        """Получает или создает сессию чата"""
        if chat_id not in self.sessions:
            self.sessions[chat_id] = ChatSession(chat_id)
        return self.sessions[chat_id]

    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Очищает старые сессии"""
        cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
        old_chats = [
            chat_id for chat_id, session in self.sessions.items()
            if session.created_at.timestamp() < cutoff_time and not session.active_users
        ]
        for chat_id in old_chats:
            del self.sessions[chat_id]


# =============================================================================
# ВАЛИДАЦИЯ И ПАРСЕРЫ
# =============================================================================

class BetValidator:
    """Валидатор ставок"""

    @staticmethod
    def validate_bet(amount: int, user_balance: int, user_total_bets: int = 0) -> Tuple[bool, str]:
        """Проверяет валидность ставки"""
        if amount <= 0:
            return False, "❌ Ставка должна быть положительным числом"

        if amount < CONFIG.MIN_BET:
            return False, f"❌ Минимальная ставка: {CONFIG.MIN_BET}"

        if amount > CONFIG.MAX_BET:
            return False, f"❌ Максимальная ставка: {CONFIG.MAX_BET}"

        if amount > user_balance:
            return False, f"❌ Недостаточно средств. Баланс: {user_balance}"

        if user_total_bets + amount > CONFIG.MAX_TOTAL_BETS_PER_USER:
            return False, "❌ Превышен лимит ставок"

        return True, ""


class BetParser:
    """Парсер ставок из текста"""

    COLOR_MAP = {
        'к': 'красное', 'кр': 'красное', 'крас': 'красное', 'red': 'красное',
        'ч': 'черное', 'чер': 'черное', 'black': 'черное',
        'з': 'зеленое', 'зел': 'зеленое', 'green': 'зеленое', '0': 'зеленое'
    }

    GROUP_MAP = {
        '1-3': '1-3', '13': '1-3',
        '4-6': '4-6', '46': '4-6',
        '7-9': '7-9', '79': '7-9',
        '10-12': '10-12', '1012': '10-12'
    }

    AMOUNT_PATTERN = re.compile(r"^(\d+)(k|к)?$", re.IGNORECASE)
    MULTIPLE_BETS_PATTERN = re.compile(r'[,и]+\s*')
    CLEAN_PATTERN = re.compile(r'\s+на\s+')

    @staticmethod
    def parse_amount(raw: str) -> Optional[int]:
        """Парсит сумму ставки (поддерживает k/к)"""
        if not raw:
            return None

        text = raw.strip().lower().replace(" ", "")
        match = BetParser.AMOUNT_PATTERN.match(text)

        if not match:
            return None

        value = int(match.group(1))
        return value * 1000 if match.group(2) else value

    @staticmethod
    def parse_single_bet(text: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        """Парсит одну ставку из текста"""
        if not text:
            return None, None, None

        text = ' '.join(text.strip().split())
        parts = text.lower().split()

        if len(parts) < 2:
            return None, None, None

        amount = BetParser.parse_amount(parts[0])
        if amount is None:
            return None, None, None

        target = ' '.join(parts[1:])

        # Проверяем цвет
        if target in BetParser.COLOR_MAP:
            return amount, "цвет", BetParser.COLOR_MAP[target]

        # Проверяем число (0-12)
        if target.isdigit() and 0 <= int(target) <= 12:
            return amount, "число", int(target)

        # Проверяем стандартные группы
        if target in BetParser.GROUP_MAP:
            return amount, "группа", BetParser.GROUP_MAP[target]

        # Проверяем пользовательские диапазоны
        if '-' in target:
            try:
                start, end = map(int, target.split('-'))
                if 0 <= start <= 12 and 0 <= end <= 12 and start < end:
                    return amount, "группа", f"{start}-{end}"
            except (ValueError, TypeError):
                return None, None, None

        return None, None, None

    @staticmethod
    def parse_multiple_bets(text: str) -> List[Tuple[int, str, str]]:
        """Парсит несколько ставок из одного сообщения"""
        text = BetParser.CLEAN_PATTERN.sub(' ', text.lower())
        bets = []

        # Сначала пробуем распарсить как одиночную ставку
        single_bet = BetParser.parse_single_bet(text)
        if all(single_bet):
            bets.append(single_bet)
            return bets

        # Парсим несколько ставок через разделители
        parts = BetParser.MULTIPLE_BETS_PATTERN.split(text)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            bet_data = BetParser.parse_single_bet(part)
            if all(bet_data):
                bets.append(bet_data)

        return bets


# =============================================================================
# ИГРОВАЯ ЛОГИКА
# =============================================================================

class RouletteGame:
    """Логика игры в рулетку"""

    def __init__(self):
        self.numbers = CONFIG.NUMBERS
        self._rng = random.Random()

        # Предварительно вычисленные группы
        self.standard_groups = {
            "1-3": {1, 2, 3}, "4-6": {4, 5, 6},
            "7-9": {7, 8, 9}, "10-12": {10, 11, 12}
        }

    def spin(self) -> int:
        """Крутит рулетку и возвращает результат"""
        return self._rng.choice(self.numbers)

    def get_color(self, number: int) -> str:
        """Возвращает цвет числа"""
        if number == 0:
            return "зеленое"
        return "красное" if number in CONFIG.RED_NUMBERS else "черное"

    def get_color_emoji(self, number: int) -> str:
        """Возвращает emoji цвета"""
        if number == 0:
            return "🟢"
        return "🔴" if number in CONFIG.RED_NUMBERS else "⚫"

    def check_bet(self, bet_type: str, bet_value: Any, result: int) -> bool:
        """Проверяет выигрышность ставки"""
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
        """Возвращает множитель для типа ставки"""
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


# =============================================================================
# ИНТЕРФЕЙС ПОЛЬЗОВАТЕЛЯ
# =============================================================================

class RouletteKeyboard:
    """Генератор клавиатур для рулетки"""

    @staticmethod
    def create_roulette_keyboard() -> InlineKeyboardMarkup:
        """Создает компактную клавиатуру для мини-рулетки"""
        return InlineKeyboardMarkup(
            row_width=4
        ).row(
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


# =============================================================================
# ЗАЩИТА ОТ ФЛУДА
# =============================================================================

class AntiFloodManager:
    """Менеджер защиты от флуда"""

    __slots__ = ('user_last_spin', 'user_spin_count', 'user_spin_reset_time')

    def __init__(self):
        self.user_last_spin: Dict[Tuple[int, int], float] = {}
        self.user_spin_count: Dict[Tuple[int, int], int] = {}
        self.user_spin_reset_time: Dict[Tuple[int, int], float] = {}

    def can_spin(self, user_id: int, chat_id: int) -> Tuple[bool, float]:
        """Проверяет, может ли пользователь запустить рулетку"""
        key = (user_id, chat_id)
        current_time = asyncio.get_event_loop().time()

        # Проверяем минимальный интервал между прокрутками
        if key in self.user_last_spin:
            last_spin_time = self.user_last_spin[key]
            elapsed = current_time - last_spin_time
            if elapsed < CONFIG.MIN_SPIN_INTERVAL:
                return False, CONFIG.MIN_SPIN_INTERVAL - elapsed

        # Инициализируем счетчики если их нет
        if key not in self.user_spin_count:
            self.user_spin_count[key] = 0
            self.user_spin_reset_time[key] = current_time

        # Сбрасываем счетчик если прошел интервал сброса
        if current_time - self.user_spin_reset_time[key] > CONFIG.RESET_INTERVAL:
            self.user_spin_count[key] = 0
            self.user_spin_reset_time[key] = current_time

        # Проверяем лимит прокруток в минуту
        if self.user_spin_count[key] >= CONFIG.MAX_SPINS_PER_MINUTE:
            time_until_reset = CONFIG.RESET_INTERVAL - (current_time - self.user_spin_reset_time[key])
            return False, time_until_reset

        # Обновляем счетчики
        self.user_last_spin[key] = current_time
        self.user_spin_count[key] += 1

        return True, 0

    def cleanup_old_entries(self):
        """Очищает старые записи для экономии памяти"""
        current_time = asyncio.get_event_loop().time()
        old_keys = [
            key for key, timestamp in self.user_last_spin.items()
            if current_time - timestamp > CONFIG.CLEANUP_INTERVAL
        ]

        for key in old_keys:
            self.user_last_spin.pop(key, None)
            self.user_spin_count.pop(key, None)
            self.user_spin_reset_time.pop(key, None)


# =============================================================================
# ОСНОВНОЙ ОБРАБОТЧИК
# =============================================================================

class RouletteHandler:
    """Основной обработчик рулетки"""

    def __init__(self):
        self.game = RouletteGame()
        self.session_manager = SessionManager()
        self.logger = RouletteLogger()
        self.anti_flood = AntiFloodManager()
        self._cleanup_task = None
        self._command_handlers = self._setup_command_handlers()

    async def initialize(self):
        """Инициализация обработчика"""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def shutdown(self):
        """Остановка обработчика"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _periodic_cleanup(self):
        """Периодическая очистка старых записей"""
        while True:
            await asyncio.sleep(60)
            self.anti_flood.cleanup_old_entries()
            self.session_manager.cleanup_old_sessions()

    def _setup_command_handlers(self) -> Dict[str, callable]:
        """Настраивает обработчики текстовых команд"""
        return {
            "го": self.spin_roulette,
            "крутить": self.spin_roulette,
            "spin": self.spin_roulette,
            "отмена": self.clear_bets_command,
            "очистить": self.clear_bets_command,
            "clear": self.clear_bets_command,
            "ставки": self.show_my_bets,
            "мои ставки": self.show_my_bets,
            "bets": self.show_my_bets,
            "лог": lambda m: self.show_logs_command(m, False),
            "!лог": lambda m: self.show_logs_command(m, True),
            "повторить": lambda m: self._repeat_last_bets(m.from_user.id, m.chat.id, m),
            "repeat": lambda m: self._repeat_last_bets(m.from_user.id, m.chat.id, m),
            "удвоить": lambda m: self._double_bets(m.from_user.id, m.chat.id, m),
            "удвой": lambda m: self._double_bets(m.from_user.id, m.chat.id, m),
            "double": lambda m: self._double_bets(m.from_user.id, m.chat.id, m),
            "лимит рулетки": self.show_limits,
            "limit roulette": self.show_limits,
        }

    # -------------------------------------------------------------------------
    # СЛУЖЕБНЫЕ МЕТОДЫ
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_display_name(user: types.User) -> str:
        """Возвращает отображаемое имя пользователя"""
        return UserFormatter._get_display_name(user)

    @staticmethod
    def _format_username_with_link(user_id: int, username: str) -> str:
        """Форматирует имя пользователя со ссылкой"""
        return UserFormatter.get_user_link(user_id, username)

    @staticmethod
    def _get_plain_username(username: str) -> str:
        """Возвращает простое имя пользователя без ссылки"""
        return UserFormatter.get_plain_name(username)

    async def _delete_bet_messages(self, chat_id: int, user_session: UserBetSession):
        """Удаляет сообщения о ставках пользователя"""
        if not user_session.bet_message_ids:
            return

        delete_tasks = []
        for msg_id in user_session.bet_message_ids:
            delete_tasks.append(
                bot.delete_message(chat_id=chat_id, message_id=msg_id)
            )

        results = await asyncio.gather(*delete_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Не удалось удалить сообщение: {result}")

        user_session.bet_message_ids.clear()

    async def _delete_spin_message(self, chat_id: int, session: ChatSession):
        """Удаляет сообщение о кручении рулетки"""
        if session.spin_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=session.spin_message_id)
            except Exception as e:
                logger.debug(f"Не удалось удалить spin сообщение: {e}")
            finally:
                session.spin_message_id = None

    def _calculate_bet_result(self, bet: Bet, result: int) -> Tuple[int, int]:
        """Рассчитывает результат ставки"""
        multiplier = self.game.get_multiplier(bet.type, bet.value)
        is_win = self.game.check_bet(bet.type, bet.value, result)

        if is_win:
            gross_profit = int(bet.amount * multiplier)
            total_payout = gross_profit
            return gross_profit, total_payout
        else:
            return -bet.amount, 0

    def _format_wait_time(self, wait_time: float) -> str:
        """Форматирует время ожидания"""
        if wait_time > 60:
            wait_minutes = int(wait_time // 60)
            wait_seconds = int(wait_time % 60)
            return f"{wait_minutes} мин {wait_seconds} сек"
        return f"{wait_time:.1f} секунд"

    # -------------------------------------------------------------------------
    # ОСНОВНЫЕ КОМАНДЫ
    # -------------------------------------------------------------------------

    async def start_roulette(self, message: types.Message):
        """Обработчик команды старта рулетки"""
        user_id = message.from_user.id

        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                await message.answer("❌ Сначала зарегистрируйтесь через /start")
                return

        examples = (
            "🎰 Минирулетка\n"
            "Угадайте число из\n"
            "0💚\n"
            "1🔴 2⚫ 3🔴 4⚫ 5🔴 6⚫\n"
            "7🔴 8⚫ 9🔴10⚫11🔴12⚫\n"
            "Ставки можно текстом\n"
            "1000 на красное | 5000 на 12"
        )

        keyboard = RouletteKeyboard.create_roulette_keyboard()
        await message.answer(examples, reply_markup=keyboard)

    async def quick_start_roulette(self, message: types.Message):
        """Быстрый старт рулетки - только если есть ставки"""
        user_id = message.from_user.id
        chat_id = message.chat.id

        session = self.session_manager.get_session(chat_id)
        user_session = session.get_user_session(user_id, self._get_display_name(message.from_user))

        if user_session.has_bets:
            await self.spin_roulette(message)

    async def clear_bets_command(self, message: types.Message):
        """Очистка ставки"""
        user_id = message.from_user.id
        chat_id = message.chat.id
        success, result = await self._clear_bets(user_id, chat_id, message)
        await message.answer(result)

    async def show_my_bets(self, message: types.Message):
        """Показать мои ставки"""
        user_id = message.from_user.id
        chat_id = message.chat.id

        session = self.session_manager.get_session(chat_id)
        if user_id not in session.user_sessions or not session.user_sessions[user_id].has_bets:
            await message.answer("❌ У вас нет активных ставок")
            return

        user_session = session.user_sessions[user_id]
        await message.answer(
            f"📋 Ваши активные ставки:\n\n{user_session.get_bets_info()}",
            parse_mode="Markdown"
        )

    async def show_balance(self, message: types.Message):
        """Показать баланс"""
        user_id = message.from_user.id
        chat_id = message.chat.id

        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                await message.answer("❌ Сначала зарегистрируйтесь через /start в ЛС с ботом!")
                return

            coins = user.coins
            display_name = self._get_plain_username(self._get_display_name(message.from_user))

            session = self.session_manager.get_session(chat_id)

            active_bets_amount = 0
            if user_id in session.user_sessions and session.user_sessions[user_id].has_bets:
                active_bets_amount = session.user_sessions[user_id].total_amount

            balance_text = f"{display_name} \nмонеты: {coins}🪙"
            if active_bets_amount > 0:
                balance_text += f" +{active_bets_amount}"

            await message.answer(balance_text, parse_mode="Markdown")

    async def show_logs_command(self, message: types.Message, show_all: bool = False):
        """Команда показа логов"""
        chat_id = message.chat.id
        logs_count = self.logger.get_logs_count(chat_id)

        if logs_count == 0:
            await message.answer("📊 Логи рулетки этого чата:\nПока нет записей о играх")
            return

        limit = CONFIG.MAX_GAME_LOGS if show_all else 10
        logs = self.logger.get_recent_logs(chat_id, limit)

        if not logs:
            await message.answer("📊 Логи рулетки этого чата:\nПока нет записей о играх")
            return

        logs_text = "".join(f"{log['color_emoji']}{log['result']}\n" for log in logs)
        await message.answer(logs_text)

    async def show_limits(self, message: types.Message):
        """Показывает информацию о лимитах рулетки"""
        user_id = message.from_user.id
        chat_id = message.chat.id

        limit_info = roulette_limit_manager.get_spin_info_for_chat(user_id, chat_id)

        if not roulette_limit_manager.has_roulette_limit_removed_in_chat(user_id, chat_id):
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🛍️ Купить снятие лимита", callback_data="back_to_shop")
            )
            await message.answer(
                f"{limit_info}\n\n💡 Снимите лимит рулетки в этом чате всего за 2кк монет!",
                reply_markup=keyboard
            )
        else:
            await message.answer(limit_info)

    # -------------------------------------------------------------------------
    # ОБРАБОТКА СТАВОК
    # -------------------------------------------------------------------------

    async def _place_multiple_bets(self, user_id: int, chat_id: int, bets: List[Tuple[int, str, str]],
                                   username: str, reply_target: types.Message) -> Tuple[bool, str, int]:
        """Размещает несколько ставок"""
        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                return False, "❌ Сначала зарегистрируйтесь через /start", 0

            coins = user.coins
            session = self.session_manager.get_session(chat_id)
            user_session = session.get_user_session(user_id, username)

            successful_bets = []
            total_amount = 0
            errors = []

            for amount, bet_type, bet_value in bets:
                is_valid, error_msg = BetValidator.validate_bet(amount, coins, user_session.total_amount)
                if not is_valid:
                    errors.append(error_msg)
                    continue

                bet = Bet(amount, bet_type, bet_value, username, user_id)
                if user_session.add_bet(bet):
                    coins -= amount
                    total_amount += amount
                    successful_bets.append(bet)
                    UserRepository.update_user_balance(db, user_id, coins)
                    UserRepository.update_max_bet(db, user_id, amount)

            if not successful_bets:
                error_message = "\n".join(errors) if errors else "❌ Не удалось разместить ни одну ставку"
                return False, error_message, 0

            if not getattr(session, 'is_doubling_operation', False):
                session.last_user_bets[user_id] = bets

            session.is_doubling_operation = False

            user_link = self._format_username_with_link(user_id, username)
            success_text = self._format_success_message(successful_bets, total_amount, user_link, errors)

            try:
                msg = await reply_target.answer(success_text, parse_mode="Markdown")
                user_session.bet_message_ids.append(msg.message_id)
            except Exception as e:
                logger.error(f"Ошибка при создании сообщения: {e}")

            return True, success_text, total_amount

    def _format_success_message(self, successful_bets: List[Bet], total_amount: int,
                                user_link: str, errors: List[str]) -> str:
        """Форматирует сообщение об успешной ставке"""
        if len(successful_bets) == 1:
            bet = successful_bets[0]
            text = f"Ставка принята: {user_link} {total_amount} монет на {bet.value}"
        else:
            bet_details = [f" ᅠ{bet.amount} на {bet.value}" for bet in successful_bets]
            text = f"Ставки приняты:\n" + "\n".join(bet_details) + f"\n💰 Общая сумма: {total_amount}"

        if errors:
            text += f"\n\nОшибки:\n" + "\n".join(errors)

        return text

    async def _clear_bets(self, user_id: int, chat_id: int, message: types.Message) -> Tuple[bool, str]:
        """Очищает все ставки пользователя"""
        session = self.session_manager.get_session(chat_id)

        if user_id not in session.user_sessions or not session.user_sessions[user_id].has_bets:
            return False, "❌ У вас нет активных ставок для очистки"

        user_session = session.user_sessions[user_id]
        total_amount = user_session.clear_bets()

        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if user:
                UserRepository.update_user_balance(db, user_id, user.coins + total_amount)

        await self._delete_bet_messages(chat_id, user_session)

        return True, f"✅ Все ставки очищены. Возвращено {total_amount} монет"

    # -------------------------------------------------------------------------
    # ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ
    # -------------------------------------------------------------------------

    async def place_bet(self, message: types.Message):
        """Обработка текстовых ставок"""
        text = (message.text or "").strip()
        user_id = message.from_user.id
        chat_id = message.chat.id
        username = self._get_display_name(message.from_user)

        if await self._handle_special_commands(text, message, user_id, chat_id, username):
            return

        if text.upper() == "Б" or text.startswith("/"):
            return

        session = self.session_manager.get_session(chat_id)

        if user_id in session.waiting_for_bet:
            await self._handle_waiting_bet(user_id, chat_id, text, username, message, session)
            return

        bets = BetParser.parse_multiple_bets(text)
        if bets:
            ok, result_msg, total = await self._place_multiple_bets(user_id, chat_id, bets, username, message)
            if not ok:
                await message.answer(result_msg)
            return

        amount, bet_type, bet_value = BetParser.parse_single_bet(text)
        if amount and bet_type and bet_value:
            ok, result_msg, total = await self._place_multiple_bets(
                user_id, chat_id, [(amount, bet_type, bet_value)], username, message
            )
            if not ok:
                await message.answer(result_msg)

    async def _handle_special_commands(self, text: str, message: types.Message,
                                       user_id: int, chat_id: int, username: str) -> bool:
        """Обрабатывает специальные команды"""
        text_lower = text.lower().strip()

        if text_lower in ['лимиты', 'лимит', 'limits']:
            from handlers.transfer_limit import transfer_limit
            limit_info = transfer_limit.get_limit_info(user_id)
            await message.answer(limit_info)
            return True

        if text_lower.startswith(("ва-банк", "вабанк", "ва банк")):
            parts = text_lower.split()
            if len(parts) < 2:
                await message.answer("❌ Укажите тип ставки для вабанка\nПример: вабанк красное")
                return True

            bet_type = parts[1]
            await self._handle_vabank(user_id, chat_id, bet_type, message)
            return True

        if text_lower in self._command_handlers:
            await self._command_handlers[text_lower](message)
            return True

        return False

    async def _handle_vabank(self, user_id: int, chat_id: int, bet_value: str, message: types.Message):
        """Обработка ва-банк"""
        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                await message.answer("❌ Сначала зарегистрируйтесь через /start")
                return

            session = self.session_manager.get_session(chat_id)
            username = self._get_display_name(message.from_user)
            user_session = session.get_user_session(user_id, username)

            current_balance = user.coins

            if current_balance <= 0:
                await message.answer("❌ Недостаточно средств для ва-банка")
                return

            if current_balance < CONFIG.MIN_BET:
                await message.answer(f"❌ Минимальная ставка для ва-банка: {CONFIG.MIN_BET}")
                return

            bet_data = self._parse_vabank_bet(bet_value)
            if not bet_data:
                await message.answer("❌ Неверный тип ставки для вабанка")
                return

            bet_type, full_bet_value = bet_data
            vabank_bet = Bet(current_balance, bet_type, full_bet_value, username, user_id)

            if not user_session.add_bet(vabank_bet):
                await message.answer("❌ Не удалось разместить ва-банк ставку")
                return

            UserRepository.update_user_balance(db, user_id, 0)

            total_all_bets = user_session.total_amount
            UserRepository.update_max_bet(db, user_id, max(getattr(user, 'max_bet', 0), total_all_bets))

            user_link = self._format_username_with_link(user_id, username)
            vabank_text = f"🎲 ВА-БАНК! {user_link} поставил все {current_balance:,} монет на {full_bet_value}"

            try:
                msg = await message.answer(vabank_text, parse_mode="Markdown")
                user_session.bet_message_ids.append(msg.message_id)
            except Exception as e:
                logger.error(f"Ошибка при создании сообщения: {e}")

    def _parse_vabank_bet(self, bet_value: str) -> Optional[Tuple[str, str]]:
        """Парсит ставку для ва-банка"""
        color_map = {
            'к': 'красное', 'кр': 'красное', 'крас': 'красное', 'red': 'красное',
            'ч': 'черное', 'чер': 'черное', 'black': 'черное',
            'з': 'зеленое', 'зел': 'зеленое', 'green': 'зеленое', '0': 'зеленое'
        }

        bet_value = bet_value.lower().strip()

        if bet_value.isdigit() and 0 <= int(bet_value) <= 12:
            return "число", int(bet_value)

        if bet_value in color_map:
            return "цвет", color_map[bet_value]

        if bet_value in ['красное', 'черное', 'зеленое']:
            return "цвет", bet_value

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

    async def _handle_waiting_bet(self, user_id: int, chat_id: int, text: str, username: str,
                                  message: types.Message, session: ChatSession):
        """Обработка ожидаемой ставки"""
        bet_type, bet_value = session.waiting_for_bet[user_id]
        amount = BetParser.parse_amount(text.split()[0])

        if amount is None:
            await message.answer("❌ Введите корректную сумму (пример: 1000 или 1k)")
            return

        ok, result_msg, total = await self._place_multiple_bets(
            user_id, chat_id, [(amount, bet_type, bet_value)], username, message
        )
        del session.waiting_for_bet[user_id]

        if not ok:
            await message.answer(result_msg)

    # -------------------------------------------------------------------------
    # ОБРАБОТКА CALLBACK-ОВ
    # -------------------------------------------------------------------------

    async def handle_callback(self, call: types.CallbackQuery):
        """Обработчик callback-ов от инлайн-кнопок"""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        data = call.data

        if not data:
            await call.answer("❌ Недействительная кнопка!")
            return

        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                await call.answer("❌ Сначала зарегистрируйтесь через /start")
                return

            try:
                if ':' in data:
                    prefix, callback_data = data.split(':', 1)
                    await self._route_callback(prefix, callback_data, call, user_id, chat_id)
                else:
                    await self._handle_legacy_callback(data, call, user_id, chat_id)

            except Exception as e:
                logger.error(f"❌ Ошибка обработки callback: {e}")
                await call.answer("❌ Ошибка обработки кнопки")

    async def _route_callback(self, prefix: str, callback_data: str, call: types.CallbackQuery,
                              user_id: int, chat_id: int):
        """Маршрутизирует callback по префиксам"""
        handlers = {
            "bet": self._handle_bet_callback,
            "quick": self._handle_quick_bet_callback,
            "action": self._handle_action_callback
        }

        handler = handlers.get(prefix)
        if handler:
            await handler(call, user_id, chat_id, callback_data)
        else:
            await call.answer("❌ Неизвестный тип кнопки")

    async def _handle_bet_callback(self, call: types.CallbackQuery, user_id: int,
                                   chat_id: int, callback_data: str):
        """Обработка callback-ов ставок"""
        bet_type_mapping = {
            "1-3": ("группа", "1-3"),
            "4-6": ("группа", "4-6"),
            "7-9": ("группа", "7-9"),
            "10-12": ("группа", "10-12"),
        }

        if callback_data in bet_type_mapping:
            session = self.session_manager.get_session(chat_id)
            bet_type, bet_value = bet_type_mapping[callback_data]
            session.waiting_for_bet[user_id] = (bet_type, bet_value)
            await call.answer(f"Выбрано: {bet_value}. Введите сумму ставки")
        else:
            await call.answer("❌ Неизвестный тип ставки")

    async def _handle_quick_bet_callback(self, call: types.CallbackQuery, user_id: int,
                                         chat_id: int, callback_data: str):
        """Обработка callback-ов быстрых ставок"""
        try:
            amount_str, color_type = callback_data.split("_")
            amount = int(amount_str)

            color_map = {
                "red": ("цвет", "красное"),
                "black": ("цвет", "черное"),
                "green": ("цвет", "зеленое")
            }

            if color_type in color_map:
                bet_type, bet_value = color_map[color_type]
                username = self._get_display_name(call.from_user)

                ok, result_msg, total = await self._place_multiple_bets(
                    user_id, chat_id, [(amount, bet_type, bet_value)], username, call.message
                )

                if ok:
                    await call.answer(f"Ставка {amount} на {bet_value} принята!")
                else:
                    await call.answer(f"❌ {result_msg}")
            else:
                await call.answer("❌ Неизвестный тип ставки")

        except Exception as e:
            logger.error(f"❌ Ошибка быстрой ставки: {e}")
            await call.answer("❌ Ошибка размещения ставки")

    async def _handle_action_callback(self, call: types.CallbackQuery, user_id: int,
                                      chat_id: int, callback_data: str):
        """Обработка callback-ов действий"""
        username = self._get_display_name(call.from_user)
        session = self.session_manager.get_session(chat_id)

        if callback_data == "spin":
            if session.is_spinning:
                await call.answer("🎰 Рулетка уже крутится! Подождите...")
                return

            await self.spin_roulette(call.message)
            await call.answer("🎰 Крутим рулетку!")
        elif callback_data == "repeat":
            await self._repeat_last_bets(user_id, chat_id, call)
            await call.answer("🔄 Повторяем последние ставки")
        elif callback_data == "double":
            await self._double_bets(user_id, chat_id, call)
            await call.answer("⚡ Удваиваем ставки")

    async def _handle_legacy_callback(self, data: str, call: types.CallbackQuery,
                                      user_id: int, chat_id: int):
        """Обработка старых форматов callback"""
        username = self._get_display_name(call.from_user)
        session = self.session_manager.get_session(chat_id)

        if data.startswith("bet_"):
            bet_value = data.replace("bet_", "")
            session.waiting_for_bet[user_id] = ("группа", bet_value)
            await call.answer(f"Выбрано: {bet_value}. Введите сумму ставки")
        elif data.startswith("quick_"):
            quick_data = data.replace("quick_", "")
            await self._handle_quick_bet_callback(call, user_id, chat_id, quick_data)
        elif data in ["repeat", "double", "spin"]:
            await self._handle_action_callback(call, user_id, chat_id, data)

    # -------------------------------------------------------------------------
    # ИГРОВАЯ МЕХАНИКА
    # -------------------------------------------------------------------------

    async def spin_roulette(self, message: types.Message):
        """Кручение рулетки и расчет результатов"""
        user_id = message.from_user.id
        chat_id = message.chat.id

        session = self.session_manager.get_session(chat_id)

        try:
            async with asyncio.timeout(1.0):
                await session.spin_lock.acquire()
        except asyncio.TimeoutError:
            await message.answer("🎰 Рулетка уже крутится! Подождите завершения текущей игры.")
            return

        try:
            if session.is_spinning:
                await message.answer("🎰 Рулетка уже крутится! Подождите завершения текущей игры.")
                return

            session.is_spinning = True

            can_spin, wait_time = self.anti_flood.can_spin(user_id, chat_id)
            if not can_spin:
                time_text = self._format_wait_time(wait_time)
                await message.answer(f"⏳ Слишком часто! Подождите {time_text} перед следующим запуском.")
                return

            if not await self.check_spin_limit(user_id, chat_id, message):
                return

            active_users = session.active_users

            if not active_users:
                await message.answer("❌ Нет активных ставок для игры!")
                return

            if not roulette_limit_manager.record_spin_in_chat(user_id, chat_id):
                await message.answer("❌ Лимит прокрутов в этом чате исчерпан!")
                return

            spin_msg = await message.answer(f"🎰 Крутим рулетку (через {CONFIG.SPIN_DELAY} сек.)")
            session.spin_message_id = spin_msg.message_id

            await asyncio.sleep(CONFIG.SPIN_DELAY)

            result = self.game.spin()
            color_emoji = self.game.get_color_emoji(result)

            self.logger.add_game_log(chat_id, result, color_emoji)

            await self._delete_spin_message(chat_id, session)

            result_text = await self._process_game_results(active_users, result, color_emoji, chat_id, session)

            try:
                await message.answer(result_text, parse_mode="Markdown")
            except BadRequest as e:
                if "Message to be replied not found" in str(e):
                    await message.answer(result_text, parse_mode="Markdown")
                else:
                    try:
                        await message.answer(result_text, parse_mode="Markdown")
                    except Exception:
                        logger.error(f"Failed to send roulette result: {e}")

        except Exception as e:
            logger.error(f"❌ Ошибка при кручении рулетки: {e}")
            await message.answer("❌ Произошла ошибка при кручении рулетки")
        finally:
            session.is_spinning = False
            if session.spin_lock.locked():
                session.spin_lock.release()

    async def _process_game_results(self, active_users: Dict[int, UserBetSession], result: int,
                                    color_emoji: str, chat_id: int, session: ChatSession) -> str:
        """Обрабатывает результаты игры для всех пользователей"""
        result_text = f"🎰 Рулетка: {result}{color_emoji}\n\n"

        user_updates = {}
        user_stats_updates = {}

        # Сохраняем ставки для повторения
        for user_id, user_session in active_users.items():
            if user_session.bets:
                bets_for_repeat = [(bet.amount, bet.type, bet.value) for bet in user_session.bets]
                session.last_user_bets[user_id] = bets_for_repeat

        # Обрабатываем каждого пользователя
        for user_id, user_session in active_users.items():
            async with DatabaseManager.db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    continue

                user_result_text = await self._process_user_results(
                    user_id, user_session, result, user, user_updates, user_stats_updates, chat_id
                )
                result_text += user_result_text + "\n\n"

                # Удаляем сообщения о ставках
                await self._delete_bet_messages(chat_id, user_session)

        # Выполняем пакетное обновление БД
        if user_updates:
            await self._update_database_batch(user_updates, user_stats_updates)

        # Очищаем ставки всех активных пользователей
        for user_id in active_users:
            if user_id in session.user_sessions:
                session.user_sessions[user_id].clear_bets()

        return result_text

    async def _process_user_results(self, user_id: int, user_session: UserBetSession, result: int,
                                    user, user_updates: Dict, user_stats_updates: Dict,
                                    chat_id: int) -> str:
        """Обрабатывает результаты для одного пользователя"""
        current_coins = user.coins
        win_coins = user.win_coins or 0
        defeat_coins = user.defeat_coins or 0
        max_win = user.max_win_coins or 0
        min_win = user.min_win_coins

        total_net_profit = 0
        total_payout = 0
        user_bets_text = []
        win_bets_text = []

        display_name = user_session.username

        # Сначала собираем все данные для транзакций
        transactions_data = []

        for bet in user_session.bets:
            net_profit, payout = self._calculate_bet_result(bet, result)
            total_net_profit += net_profit
            total_payout += payout

            plain_name = self._get_plain_username(display_name)
            user_bets_text.append(f"{plain_name} {bet.amount} на {bet.value}")

            if net_profit > 0:
                user_link = self._format_username_with_link(user_id, display_name)
                win_bets_text.append(f"{user_link} выиграл {net_profit} на {bet.value}")

            # Сохраняем данные для транзакций
            transactions_data.append({
                'user_id': user_id,
                'amount': bet.amount,
                'is_win': net_profit > 0,
                'bet_type': bet.type,
                'bet_value': str(bet.value),
                'result_number': result,
                'profit': net_profit
            })

        # Обновляем статистику
        if total_net_profit < 0:
            defeat_coins += abs(total_net_profit)
        elif total_net_profit > 0:
            win_coins += total_net_profit
            max_win = max(max_win, total_net_profit)
            min_win = total_net_profit if min_win is None else min(min_win, total_net_profit)

        # Сохраняем обновления для batch-обработки
        user_updates[user_id] = current_coins + total_payout
        user_stats_updates[user_id] = (win_coins, defeat_coins, max_win, min_win)

        # Создаем транзакции в отдельной операции
        await self._create_roulette_transactions(transactions_data)

        # Добавляем рекорд если есть выигрыш
        if total_net_profit > 0:
            await self._add_win_record(user_id, total_net_profit, user, chat_id)

        return "\n".join(user_bets_text + win_bets_text)

    async def _create_roulette_transactions(self, transactions_data: List[Dict]):
        """Создает транзакции рулетки в БД"""
        async with DatabaseManager.db_session() as db:
            for transaction in transactions_data:
                RouletteRepository.create_roulette_transaction(
                    db=db,
                    user_id=transaction['user_id'],
                    amount=transaction['amount'],
                    is_win=transaction['is_win'],
                    bet_type=transaction['bet_type'],
                    bet_value=transaction['bet_value'],
                    result_number=transaction['result_number'],
                    profit=transaction['profit']
                )

    async def _update_database_batch(self, user_updates: Dict, user_stats_updates: Dict):
        """Пакетное обновление БД"""
        try:
            await DatabaseManager.update_users_batch(user_updates, user_stats_updates)
        except Exception as e:
            logger.error(f"❌ Ошибка при пакетном обновлении БД: {e}")

    async def _add_win_record(self, user_id: int, net_profit: int, user, chat_id: int):
        """Добавляет запись о рекорде при выигрыше"""
        try:
            from handlers.record import RecordHandler
            record_handler = RecordHandler()
            username = user.username or ''
            first_name = user.first_name or ''
            await record_handler.add_score(user_id, net_profit, chat_id, username, first_name)
        except Exception as e:
            logger.error(f"⚠️ Ошибка добавления рекорда: {e}")

    # -------------------------------------------------------------------------
    # ИСТОРИЯ СТАВОК
    # -------------------------------------------------------------------------

    async def show_bet_history(self, message: types.Message, show_all: bool = False):
        """Показать историю ставок пользователя"""
        user_id = message.from_user.id

        async with DatabaseManager.db_session() as db:
            limit = 50 if show_all else 10
            history = RouletteRepository.get_user_bet_history(db, user_id, limit)

            if not history:
                await message.answer("📊 История ставок:\nПока нет записей о ставках")
                return

            history_text = "📊 История ваших ставок:\n\n"
            for i, bet in enumerate(history, 1):
                result_emoji = "✅" if bet.is_win else "❌"
                bet_type_info = f" ({bet.bet_type}: {bet.bet_value})" if bet.bet_type else ""
                profit_sign = "+" if bet.profit > 0 else ""
                history_text += f"{i}. {result_emoji} {bet.amount} монет{bet_type_info} - {profit_sign}{bet.profit}\n"

            if not show_all and len(history) >= 10:
                history_text += f"\n📈 Показано последние 10 ставок. Используйте !история для полной истории."

            await message.answer(history_text)

    # -------------------------------------------------------------------------
    # ПОВТОРИТЬ/УДВОИТЬ
    # -------------------------------------------------------------------------

    async def _repeat_last_bets(self, user_id: int, chat_id: int, message_or_call):
        """Повторяет последние ставки пользователя"""
        session = self.session_manager.get_session(chat_id)
        username = self._get_display_name(
            message_or_call.from_user if hasattr(message_or_call, 'from_user')
            else message_or_call
        )

        if user_id not in session.last_user_bets or not session.last_user_bets[user_id]:
            reply_method = getattr(message_or_call, 'answer', message_or_call.answer)
            await reply_method("❌ Нет последних ставок для повторения")
            return

        last_bets = session.last_user_bets[user_id]

        if hasattr(message_or_call, 'message'):
            ok, result_msg, total = await self._place_multiple_bets(
                user_id, chat_id, last_bets, username, message_or_call.message
            )
        else:
            ok, result_msg, total = await self._place_multiple_bets(
                user_id, chat_id, last_bets, username, message_or_call
            )

        if not ok and hasattr(message_or_call, 'answer'):
            await message_or_call.answer(result_msg)

    async def _double_bets(self, user_id: int, chat_id: int, message_or_call):
        """Удваивает текущие ставки пользователя"""
        session = self.session_manager.get_session(chat_id)
        username = self._get_display_name(
            message_or_call.from_user if hasattr(message_or_call, 'from_user')
            else message_or_call
        )

        if user_id not in session.user_sessions or not session.user_sessions[user_id].has_bets:
            reply_method = getattr(message_or_call, 'answer', message_or_call.answer)
            await reply_method("❌ Нет активных ставок для удвоения")
            return

        user_session = session.user_sessions[user_id]

        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)

            if not user:
                reply_method = getattr(message_or_call, 'answer', message_or_call.answer)
                await reply_method("❌ Пользователь не найден")
                return

            double_amount = user_session.total_amount
            if double_amount > user.coins:
                reply_method = getattr(message_or_call, 'answer', message_or_call.answer)
                await reply_method(
                    f"❌ Недостаточно средств для удвоения. Нужно: {double_amount}, есть: {user.coins}")
                return

            doubled_bets = [(bet.amount * 2, bet.type, bet.value) for bet in user_session.bets]

            session.is_doubling_operation = True
            user_session.clear_bets()

            bet_details = [f"{amount} на {self._get_bet_display_value(bet_type, value)}"
                           for amount, bet_type, value in doubled_bets]
            double_text = f"ᅠᅠ удвоил(а) ставки:\n" + "\n".join(bet_details)

            if hasattr(message_or_call, 'message'):
                ok, result_msg, total = await self._place_multiple_bets_silent(
                    user_id, chat_id, doubled_bets, username, message_or_call.message
                )

                if ok:
                    try:
                        msg = await message_or_call.message.answer(double_text, parse_mode="Markdown")
                        user_session = session.get_user_session(user_id, username)
                        user_session.bet_message_ids.append(msg.message_id)
                    except Exception as e:
                        logger.error(f"Ошибка при создании сообщения: {e}")
                else:
                    await message_or_call.answer(f"❌ {result_msg}")
            else:
                ok, result_msg, total = await self._place_multiple_bets_silent(
                    user_id, chat_id, doubled_bets, username, message_or_call
                )

                if ok:
                    try:
                        msg = await message_or_call.answer(double_text, parse_mode="Markdown")
                        user_session = session.get_user_session(user_id, username)
                        user_session.bet_message_ids.append(msg.message_id)
                    except Exception as e:
                        logger.error(f"Ошибка при создании сообщения: {e}")
                else:
                    await message_or_call.answer(result_msg)

    def _get_bet_display_value(self, bet_type: str, bet_value) -> str:
        """Возвращает отображаемое значение ставки с эмодзи"""
        if bet_type == "цвет":
            color_emojis = {"красное": "🔴", "черное": "⚫", "зеленое": "🟢"}
            return color_emojis.get(bet_value, bet_value)
        return str(bet_value)

    async def _place_multiple_bets_silent(self, user_id: int, chat_id: int, bets: List[Tuple[int, str, str]],
                                          username: str, reply_target: types.Message) -> Tuple[bool, str, int]:
        """Размещает несколько ставок без показа сообщения (для удвоения)"""
        async with DatabaseManager.db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                return False, "❌ Сначала зарегистрируйтесь через /start", 0

            coins = user.coins
            session = self.session_manager.get_session(chat_id)
            user_session = session.get_user_session(user_id, username)

            successful_bets = []
            total_amount = 0

            for amount, bet_type, bet_value in bets:
                is_valid, error_msg = BetValidator.validate_bet(amount, coins, user_session.total_amount)
                if not is_valid:
                    return False, error_msg, 0

                bet = Bet(amount, bet_type, bet_value, username, user_id)
                if user_session.add_bet(bet):
                    coins -= amount
                    total_amount += amount
                    successful_bets.append(bet)
                    UserRepository.update_user_balance(db, user_id, coins)
                    UserRepository.update_max_bet(db, user_id, amount)

            if not successful_bets:
                return False, "❌ Не удалось разместить ни одну ставку", 0

            if not getattr(session, 'is_doubling_operation', False):
                session.last_user_bets[user_id] = bets

            session.is_doubling_operation = False

            return True, "", total_amount

    async def check_spin_limit(self, user_id: int, chat_id: int, message: types.Message) -> bool:
        """Проверяет лимит прокрутов в конкретном чате"""
        can_spin, remaining = roulette_limit_manager.can_spin_roulette_in_chat(user_id, chat_id)

        if not can_spin:
            limit_info = roulette_limit_manager.get_spin_info_for_chat(user_id, chat_id)

            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🛍️ Купить снятие лимита", callback_data="back_to_shop")
            )

            await message.answer(
                f"{limit_info}\n\n💡 Хотите снять лимит в этом чате? Купите в магазине за 2кк монет!",
                reply_markup=keyboard
            )
            return False

        return True


# =============================================================================
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# =============================================================================

def register_roulette_handlers(dp):
    """Регистрирует обработчики рулетки"""
    handler = RouletteHandler()

    # Основные команды
    dp.register_message_handler(
        handler.show_balance,
        lambda m: m.text and m.text.strip().lower() in ["б", "баланс", "balance"]
    )

    dp.register_message_handler(
        handler.start_roulette,
        commands=["рулетка", "roulette"]
    )
    dp.register_message_handler(
        handler.start_roulette,
        lambda m: m.text and m.text.lower() == "рулетка"
    )

    dp.register_message_handler(
        handler.quick_start_roulette,
        lambda m: m.text and m.text.lower() in ["го", "крутить", "spin", "гоу"]
    )

    # Команды управления ставками
    dp.register_message_handler(
        handler.clear_bets_command,
        lambda m: m.text and m.text.lower() in ["отмена", "очистить", "clear", "отменить"]
    )

    dp.register_message_handler(
        handler.show_my_bets,
        lambda m: m.text and m.text.lower() in ["ставки", "мои ставки", "bets"]
    )

    # Команды повторения и удвоения
    dp.register_message_handler(
        lambda m: handler._repeat_last_bets(m.from_user.id, m.chat.id, m),
        lambda m: m.text and m.text.lower() in ["повторить", "repeat", "репит"]
    )

    dp.register_message_handler(
        lambda m: handler._double_bets(m.from_user.id, m.chat.id, m),
        lambda m: m.text and m.text.lower() in ["удвоить", "удвой", "double", "дабл"]
    )

    # Команды логов
    dp.register_message_handler(
        lambda m: handler.show_logs_command(m, False),
        lambda m: m.text and m.text.lower() == "лог"
    )
    dp.register_message_handler(
        lambda m: handler.show_logs_command(m, True),
        lambda m: m.text and m.text.lower() == "!лог"
    )

    # История ставок
    dp.register_message_handler(
        lambda m: handler.show_bet_history(m, False),
        lambda m: m.text and m.text.lower() in ["история", "ист", "history"]
    )
    dp.register_message_handler(
        lambda m: handler.show_bet_history(m, True),
        lambda m: m.text and m.text.lower() in ["!история", "!ист", "!history"]
    )

    # Лимиты рулетки
    dp.register_message_handler(
        handler.show_limits,
        lambda m: m.text and m.text.lower() in ["лимит рулетки", "limit roulette"]
    )

    # Текстовые ставки
    BET_PATTERNS = [
        r'^\d+\s*[kк]?\s+',  # Сообщения начинающиеся с чисел
        r'\d+\s*-\s*\d+',  # Сообщения с диапазонами
    ]

    BET_KEYWORDS = ["на", "ставка", "ставку", "ставки", "красн", "черн", "зелен", "кр ", "ч ", "з "]
    VABANK_KEYWORDS = ["ва-банк", "вабанк", "ва банк"]

    dp.register_message_handler(
        handler.place_bet,
        lambda m: m.text and (
                any(word in m.text.lower() for word in BET_KEYWORDS) or
                any(m.text.lower().startswith(keyword) for keyword in VABANK_KEYWORDS) or
                any(re.search(pattern, m.text.lower()) for pattern in BET_PATTERNS)
        ),
        content_types=["text"],
        state="*"
    )

    # Обработчики callback
    dp.register_callback_query_handler(
        handler.handle_callback,
        lambda c: c.data and any(c.data.startswith(prefix) for prefix in ["bet:", "quick:", "action:"])
    )

    return handler