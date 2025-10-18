import datetime
import logging
import asyncio
from typing import List, Dict, Optional
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import types, Dispatcher
from aiogram.utils.deep_linking import get_start_link

from config import bot
from database import SessionLocal, get_db
from database.crud import UserRepository, ReferenceRepository, ShopRepository
from const import START_MENU_TEXT, PROFILE_MENU_TEXT, REFERENCE_MENU_TEXT, LINKS_TEXT
from handlers.shop import ShopHandler, register_shop_handlers
from handlers.donate import DonateHandler, register_donate_handlers
from handlers.roulette import RouletteHandler, register_roulette_handlers
from keyboards.main_menu_kb import main_inline_keyboard
from keyboards.reference_keyboard import reference_menu_keyboard
from main import logger


# =============================================================================
# МОДЕЛИ ДАННЫХ И КОНФИГУРАЦИЯ
# =============================================================================

@dataclass(frozen=True)
class PrivilegeConfig:
    """Конфигурация привилегий"""
    PRIVILEGE_NAMES: Dict[int, str] = None

    def __post_init__(self):
        if self.PRIVILEGE_NAMES is None:
            object.__setattr__(self, 'PRIVILEGE_NAMES', {
                # Донат привилегии - только эти две будут отображаться
                1: "👑 Вор в законе",
                2: "👮‍♂️ Полицейский",
                # Остальные привилегии скрыты из профиля
            })


# =============================================================================
# УТИЛИТЫ ДЛЯ ФОРМАТИРОВАНИЯ
# =============================================================================

class UserFormatter:
    """Утилиты для форматирования имен пользователей с ссылками"""

    __slots__ = ()

    @staticmethod
    def get_display_name(user: types.User) -> str:
        """Получает отображаемое имя пользователя"""
        if user.first_name:
            return user.first_name
        elif user.username:
            return f"@{user.username}"
        return "Аноним"

    @staticmethod
    def get_user_link_html(user_id: int, display_name: str) -> str:
        """Создает HTML-ссылку на профиль пользователя"""
        safe_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

    @staticmethod
    def format_user_html(user: types.User) -> str:
        """Форматирует объект пользователя с HTML-ссылкой"""
        display_name = UserFormatter.get_display_name(user)
        return UserFormatter.get_user_link_html(user.id, display_name)

    @staticmethod
    def format_user_by_data_html(user_id: int, username: str, first_name: str) -> str:
        """Форматирует пользователя по данным с HTML-ссылкой"""
        display_name = username if username else (first_name if first_name else "Аноним")
        return UserFormatter.get_user_link_html(user_id, display_name)


class DatabaseManager:
    """Менеджер для работы с базой данных"""

    __slots__ = ()

    @staticmethod
    @contextmanager
    def db_session():
        """Контекстный менеджер для БД"""
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


# =============================================================================
# СЕРВИСЫ
# =============================================================================

class PrivilegeService:
    """Сервис для работы с привилегиями"""

    __slots__ = ('_config',)

    def __init__(self):
        self._config = PrivilegeConfig()

    def get_privilege_names(self, privilege_ids: List[int]) -> List[str]:
        """Получает названия привилегий по их ID - только Вор и Полицейский"""
        if not privilege_ids:
            return []

        privileges = []
        for privilege_id in privilege_ids:
            # Показываем только привилегии 1 и 2 (Вор и Полицейский)
            if privilege_id in [1, 2]:
                name = self._config.PRIVILEGE_NAMES.get(privilege_id, f"Привилегия #{privilege_id}")
                privileges.append(name)

        return privileges

    @staticmethod
    def format_privileges_text(privileges: List[str]) -> str:
        """Форматирует список привилегий в текст"""
        if not privileges:
            return ""

        # Убираем дубликаты названий привилегий
        unique_privileges = []
        seen_privileges = set()

        for privilege in privileges:
            if privilege not in seen_privileges:
                unique_privileges.append(privilege)
                seen_privileges.add(privilege)

        return "\n".join([f"• {privilege}" for privilege in unique_privileges])


class ReferralService:
    """Сервис для работы с реферальной системой"""

    __slots__ = ('_user_formatter',)

    def __init__(self, user_formatter: UserFormatter):
        self._user_formatter = user_formatter

    async def process_referral(self, message: types.Message, payload: str) -> bool:
        """Обработка реферальной ссылки. Возвращает True если реферал обработан"""
        with DatabaseManager.db_session() as db:
            try:
                if ReferenceRepository.check_reference_exists(db, message.from_user.id):
                    return False

                link = await get_start_link(payload=payload)
                owner = UserRepository.get_user_by_link(db, link)
                if not owner:
                    return False

                ReferenceRepository.add_reference(db, owner.telegram_id, message.from_user.id)

                user = UserRepository.get_user_by_telegram_id(db, message.from_user.id)
                if user:
                    user.coins += 1000
                    db.commit()

                    asyncio.create_task(self._send_referral_welcome(message.from_user.id, owner))
                    return True

            except Exception as e:
                logging.error(f"❌ Ошибка обработки реферальной ссылки: {e}")
                db.rollback()

            return False

    async def _send_referral_welcome(self, referred_user_id: int, referrer_user_id: int):
        """Отправляет приветственное сообщение рефералу"""
        try:
            db = next(get_db())
            try:
                referred_db_user = UserRepository.get_user_by_telegram_id(db, referred_user_id)
                referrer_db_user = UserRepository.get_user_by_telegram_id(db, referrer_user_id)

                if referred_db_user and referrer_db_user:
                    referred_db_user.coins += 10000
                    referrer_db_user.coins += 5000
                    db.commit()

                    from aiogram import Bot
                    bot = Bot.get_current()

                    try:
                        referred_user = await bot.get_chat(referred_user_id)
                        referrer_user = await bot.get_chat(referrer_user_id)

                        referrer_name = referrer_user.first_name or referrer_user.username or "пользователь"
                        referred_name = referred_user.first_name or referred_user.username or "пользователь"

                        welcome_text = (
                            f"🎉 Добро пожаловать, {referred_name}!\n\n"
                            f"💎 Вы были приглашены пользователем {referrer_name}\n"
                            f"💰 Вам начислено: 10,000 монет\n"
                            f"💝 Пригласившему начислено: 5,000 монет\n\n"
                            f"🎁 Используйте /start для начала работы!"
                        )

                        await bot.send_message(
                            chat_id=referred_user_id,
                            text=welcome_text
                        )

                        logger.info(f"✅ Реферальное приветствие отправлено пользователю {referred_user_id}")

                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось получить информацию о пользователях: {e}")
                        welcome_text = (
                            f"🎉 Добро пожаловать!\n\n"
                            f"💎 Вы были приглашены по реферальной ссылке\n"
                            f"💰 Вам начислено: 10,000 монет\n"
                            f"💝 Пригласившему начислено: 5,000 монет\n\n"
                            f"🎁 Используйте /start для начала работы!"
                        )

                        await bot.send_message(
                            chat_id=referred_user_id,
                            text=welcome_text
                        )

            except Exception as e:
                db.rollback()
                raise e
            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Ошибка отправки приветствия рефералу: {e}")


class ProfileService:
    """Сервис для работы с профилями пользователей"""

    __slots__ = ('_user_formatter', '_privilege_service')

    def __init__(self, user_formatter: UserFormatter, privilege_service: PrivilegeService):
        self._user_formatter = user_formatter
        self._privilege_service = privilege_service

    def format_profile_text(self, user, telegram_user_id: int, privileges: List[str]) -> str:
        """Форматирует текст профиля - показывает только Вора и Полицейского"""
        display_name = self._user_formatter.get_display_name(types.User(
            id=telegram_user_id,
            first_name=user.first_name,
            username=user.username
        ))

        user_link = self._user_formatter.get_user_link_html(telegram_user_id, display_name)

        # Получаем информацию о привилегиях с сроком действия (только Вор и Полицейский)
        detailed_privileges = self.get_active_privileges_with_expiry(telegram_user_id)

        # Создаем детализированный текст привилегий
        if detailed_privileges:
            # Обрабатываем все привилегии
            privilege_lines = []
            for priv in detailed_privileges:
                # Для каждой привилегии используем свою эмодзи
                if priv['id'] == 1:  # Вор в законе
                    privilege_line = f"{priv['name'].replace('👑 ', '').split(' (')[0]} ✵"
                elif priv['id'] == 2:  # Полицейский
                    privilege_line = f"{priv['name'].replace('👮‍♂️ ', '').split(' (')[0]}👮‍♂️ "
                else:
                    privilege_line = f"{priv['name'].split(' (')[0]} ✵"
                privilege_lines.append(privilege_line)

            # Каждая привилегия на новой строке
            privileges_section = "\n".join(privilege_lines)
        else:
            privileges_section = ""

        return (
            f"{display_name}: ♠️♥️\n"
            f"{privileges_section}\n"
            f"Монеты: {user.coins}🪙\n"
            f"Выиграно: {user.win_coins or 0}\n"
            f"Проиграно: {user.defeat_coins or 0}\n"
            f"Макс. выигрыш: {user.max_win_coins or 0}\n"
            f"Макс. ставка: {getattr(user, 'max_bet', 0)}"
        )

    def get_user_privileges(self, user_id: int) -> List[str]:
        """Получает список привилегий пользователя (только Вор и Полицейский)"""
        with DatabaseManager.db_session() as db:
            try:
                # Получаем детальную информацию о привилегиях с проверкой срока действия
                from sqlalchemy import text
                result = db.execute(
                    text("""
                         SELECT item_id, item_name, expires_at
                         FROM user_purchases
                         WHERE user_id = :user_id
                         """),
                    {"user_id": user_id}
                ).fetchall()

                active_privileges = []
                current_time = datetime.now()

                for item_id, item_name, expires_at in result:
                    # Показываем только привилегии 1 и 2 (Вор и Полицейский)
                    if item_id in [1, 2]:
                        # Проверяем срок действия
                        if expires_at is None or expires_at > current_time:
                            privilege_name = self._privilege_service._config.PRIVILEGE_NAMES.get(
                                item_id, item_name
                            )
                            active_privileges.append(privilege_name)

                # Убираем дубликаты и сортируем
                unique_privileges = sorted(list(set(active_privileges)))
                return unique_privileges

            except Exception as e:
                logging.error(f"❌ Ошибка получения привилегий: {e}")
                return []

    def get_active_privileges_with_expiry(self, user_id: int) -> List[Dict]:
        """Получает активные привилегии с информацией о сроке действия (только Вор и Полицейский)"""
        with DatabaseManager.db_session() as db:
            try:
                from sqlalchemy import text
                result = db.execute(
                    text("""
                         SELECT item_id, item_name, expires_at
                         FROM user_purchases
                         WHERE user_id = :user_id
                         """),
                    {"user_id": user_id}
                ).fetchall()

                active_privileges = []
                current_time = datetime.now()

                for item_id, item_name, expires_at in result:
                    # Фильтруем только привилегии 1 и 2 (Вор и Полицейский)
                    if item_id in [1, 2]:
                        if expires_at is None or expires_at > current_time:
                            privilege_name = self._privilege_service._config.PRIVILEGE_NAMES.get(
                                item_id, item_name
                            )

                            time_left_str = ""
                            if expires_at:
                                time_left = expires_at - current_time
                                days_left = time_left.days
                                time_left_str = f" ({days_left} дней)"
                            else:
                                time_left_str = " (навсегда)"

                            active_privileges.append({
                                'id': item_id,
                                'name': privilege_name + time_left_str,
                                'expires_at': expires_at
                            })

                return active_privileges

            except Exception as e:
                logging.error(f"❌ Ошибка получения привилегий с сроком: {e}")
                return []


# =============================================================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ
# =============================================================================

class StartHandlers:
    """Обработчики стартовых команд и меню"""

    __slots__ = ('_user_formatter', '_privilege_service', '_referral_service', '_profile_service')

    def __init__(self):
        self._user_formatter = UserFormatter()
        self._privilege_service = PrivilegeService()
        self._referral_service = ReferralService(self._user_formatter)
        self._profile_service = ProfileService(self._user_formatter, self._privilege_service)

    async def privileges_command(self, message: types.Message):
        """Обработчик команды 'привилегии' - показывает детальную информацию (только Вор и Полицейский)"""
        try:
            with DatabaseManager.db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, message.from_user.id)

                if not user:
                    await message.reply("❌ Профиль не найден")
                    return

                # Получаем детальную информацию о привилегиях (только Вор и Полицейский)
                detailed_privileges = self._profile_service.get_active_privileges_with_expiry(message.from_user.id)

                if not detailed_privileges:
                    await message.reply(
                        "💎 <b>Ваши привилегии</b>\n\n"
                        "❌ У вас нет активных привилегий\n\n"
                        "💡 Приобрести привилегии можно:\n"
                        "• Через админа: /admin_help",
                        parse_mode=types.ParseMode.HTML
                    )
                    return

                privileges_text = "💎 <b>Ваши привилегии</b>\n\n"

                for i, priv in enumerate(detailed_privileges, 1):
                    privileges_text += f"{i}. {priv['name']}\n"

                privileges_text += f"\n📊 Всего активных привилегий: {len(detailed_privileges)}"

                await message.reply(privileges_text, parse_mode=types.ParseMode.HTML)

        except Exception as e:
            logging.error(f"❌ Ошибка в privileges_command: {e}")
            await message.reply("❌ Ошибка загрузки привилегий")

    async def start_button(self, message: types.Message) -> None:
        """Обработчик команды /start"""
        command = message.get_full_command()
        payload = command[1] if len(command) > 1 else None

        referral_processed = False
        if payload:
            referral_processed = await self._referral_service.process_referral(message, payload)

        await self._send_main_menu(message, referral_processed)

    async def _send_main_menu(self, message: types.Message, referral_processed: bool = False) -> None:
        """Отправляет главное меню"""
        try:
            user_link = self._user_formatter.format_user_html(message.from_user)
            start_text = START_MENU_TEXT.format(user=user_link).replace('*', '')

            if referral_processed:
                start_text = "🎉 Вам начислено 1000 монет за переход по реферальной ссылке!\n\n" + start_text

            await bot.send_message(
                chat_id=message.chat.id,
                text=start_text,
                parse_mode=types.ParseMode.HTML,
                reply_markup=main_inline_keyboard()
            )
        except Exception as e:
            logging.error(f"❌ Ошибка в _send_main_menu: {e}")
            await message.answer("❌ Ошибка загрузки меню")

    # ---------- ТЕКСТОВЫЕ КОМАНДЫ ----------

    async def profile_command(self, message: types.Message):
        """Обработчик текстовой команды 'профиль'"""
        try:
            with DatabaseManager.db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, message.from_user.id)

                if not user:
                    await message.reply("❌ Профиль не найден")
                    return

                # Получаем привилегии пользователя (только Вор и Полицейский)
                privileges = self._profile_service.get_user_privileges(message.from_user.id)

                profile_text = self._profile_service.format_profile_text(
                    user, message.from_user.id, privileges
                )
                await message.reply(profile_text, parse_mode=types.ParseMode.HTML)

        except Exception as e:
            logging.error(f"❌ Ошибка в profile_command: {e}")
            await message.reply("❌ Ошибка загрузки профиля")

    async def links_command(self, message: types.Message):
        """Обработчик текстовой команды 'ссылки'"""
        try:
            await message.reply(LINKS_TEXT, parse_mode=types.ParseMode.MARKDOWN)
        except Exception as e:
            logging.error(f"❌ Ошибка в links_command: {e}")
            await message.reply("❌ Ошибка загрузки ссылок")

    async def id_command(self, message: types.Message):
        """Обработчик команды /id - показывает ID пользователя"""
        try:
            if message.reply_to_message:
                replied_user = message.reply_to_message.from_user
                user_id = replied_user.id
                user_name = self._user_formatter.get_display_name(replied_user)

                await message.reply(
                    f"👤 Пользователь: {user_name}\n"
                    f"🆔 ID: <code>{user_id}</code>",
                    parse_mode=types.ParseMode.HTML
                )
            else:
                user_id = message.from_user.id
                user_name = self._user_formatter.get_display_name(message.from_user)

                await message.reply(
                    f"👤 Ваш профиль: {user_name}\n"
                    f"🆔 Ваш ID: <code>{user_id}</code>",
                    parse_mode=types.ParseMode.HTML
                )
        except Exception as e:
            logging.error(f"❌ Ошибка в id_command: {e}")
            await message.reply("❌ Ошибка выполнения команды")

    # ---------- INLINE КНОПКИ ----------

    async def profile_button(self, callback: types.CallbackQuery) -> None:
        """Показ профиля через inline кнопку (только Вор и Полицейский)"""
        try:
            with DatabaseManager.db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, callback.from_user.id)

                if not user:
                    await callback.answer("❌ Профиль не найден", show_alert=True)
                    return

                # Получаем привилегии пользователя (только Вор и Полицейский)
                privileges = self._profile_service.get_user_privileges(callback.from_user.id)

                profile_text = self._profile_service.format_profile_text(
                    user, callback.from_user.id, privileges
                )
                await callback.message.edit_text(profile_text, parse_mode=types.ParseMode.HTML)
                await callback.answer()

        except Exception as e:
            logging.error(f"❌ Ошибка в profile_button: {e}")
            await callback.answer("❌ Ошибка загрузки профиля", show_alert=True)

    async def reference_button(self, callback: types.CallbackQuery) -> None:
        """Показ реферального меню"""
        try:
            with DatabaseManager.db_session() as db:
                referrals_count = ReferenceRepository.get_referrals_count(db, callback.from_user.id)
                reference_text = REFERENCE_MENU_TEXT.format(referrals_count=referrals_count)

                await callback.message.edit_text(
                    text=reference_text,
                    parse_mode=types.ParseMode.MARKDOWN,
                    reply_markup=reference_menu_keyboard()
                )
                await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в reference_button: {e}")
            await callback.answer("❌ Ошибка загрузки реферального меню", show_alert=True)

    async def links_button(self, callback: types.CallbackQuery) -> None:
        """Показ ссылок через inline кнопку"""
        try:
            await callback.message.edit_text(LINKS_TEXT, parse_mode=types.ParseMode.MARKDOWN)
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в links_button: {e}")
            await callback.answer("❌ Ошибка загрузки ссылок", show_alert=True)

    async def shop_button(self, callback: types.CallbackQuery) -> None:
        """Переход в магазин"""
        try:
            shop_handler = ShopHandler()
            await shop_handler.shop_command(callback.message)
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в shop_button: {e}")
            await callback.answer("❌ Ошибка загрузки магазина", show_alert=True)

    async def roulette_button(self, callback: types.CallbackQuery) -> None:
        """Переход в рулетку"""
        try:
            roulette_handler = RouletteHandler()
            await roulette_handler.start_roulette(callback.message)
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в roulette_button: {e}")
            await callback.answer("❌ Ошибка загрузки рулетки", show_alert=True)

    async def stickers_button(self, callback: types.CallbackQuery) -> None:
        """Раздел стикеров"""
        try:
            await callback.message.edit_text(
                "🎭 Раздел стикеров\n\n"
                "📌 В разработке...",
                parse_mode=types.ParseMode.MARKDOWN
            )
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в stickers_button: {e}")
            await callback.answer("❌ Ошибка загрузки раздела", show_alert=True)

    async def other_bots_button(self, callback: types.CallbackQuery) -> None:
        """Другие боты"""
        try:
            await callback.message.edit_text(
                "🤖 Другие боты\n\n"
                "📌 В разработке...",
                parse_mode=types.ParseMode.MARKDOWN
            )
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в other_bots_button: {e}")
            await callback.answer("❌ Ошибка загрузки раздела", show_alert=True)

    async def donate_button(self, callback: types.CallbackQuery) -> None:
        """Переход к донату"""
        try:
            donate_handler = DonateHandler()
            await donate_handler.donate_command(callback.message)
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в donate_button: {e}")
            await callback.answer("❌ Ошибка загрузки доната", show_alert=True)

    async def agreement_button(self, callback: types.CallbackQuery) -> None:
        """Обработчик кнопки пользовательского соглашения"""
        try:
            file_path = r'C:\Bek_32-2_hw-master\media\Пользовательское_Соглашение_EXEZ_кириллица.pdf'

            # Создаем инлайн-клавиатуру с кнопкой тех. поддержки
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            support_keyboard = InlineKeyboardMarkup(row_width=1)
            support_button = InlineKeyboardButton(
                "🛠️ Тех. поддержка",
                url="https://t.me/YaMusu1man"
            )
            support_keyboard.add(support_button)

            with open(file_path, 'rb') as file:
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=file,
                    caption="📄 Пользовательское соглашение\n\n"
                            "🛠️ Если у вас возникли проблемы, обратитесь в техническую поддержку:",
                    reply_markup=support_keyboard
                )
            await callback.answer()
        except FileNotFoundError:
            await callback.answer("❌ Файл соглашения не найден", show_alert=True)
        except Exception as e:
            logging.error(f"❌ Ошибка отправки соглашения: {e}")
            await callback.answer("❌ Ошибка отправки файла", show_alert=True)

    async def support_button(self, callback: types.CallbackQuery) -> None:
        """Обработчик кнопки технической поддержки"""
        try:
            # Создаем кнопку для перехода в тех. поддержку
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            support_keyboard = InlineKeyboardMarkup()
            support_button = InlineKeyboardButton(
                "🛠️ Написать в поддержку",
                url="https://t.me/YaMusu1man"
            )
            support_keyboard.add(support_button)

            await callback.message.edit_text(
                "🛠️ <b>Техническая поддержка</b>\n\n"
                "Если у вас возникли проблемы с ботом, вопросы по функционалу "
                "или предложения по улучшению - напишите нашему специалисту.\n\n"
                "Мы постараемся помочь вам в кратчайшие сроки! ⚡",
                parse_mode=types.ParseMode.HTML,
                reply_markup=support_keyboard
            )
            await callback.answer()
        except Exception as e:
            logging.error(f"❌ Ошибка в support_button: {e}")
            await callback.answer("❌ Ошибка загрузки информации о поддержке", show_alert=True)


# =============================================================================
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# =============================================================================

def register_start_handler(dp: Dispatcher) -> None:
    """Регистрация обработчиков стартовых команд"""
    handlers = StartHandlers()

    # Команды
    dp.register_message_handler(handlers.start_button, commands=['start'])
    dp.register_message_handler(handlers.id_command, commands=['id'])

    # Текстовые команды
    dp.register_message_handler(
        handlers.profile_command,
        lambda message: message.text and message.text.strip().lower() == 'профиль'
    )
    dp.register_message_handler(
        handlers.links_command,
        lambda message: message.text and message.text.strip().lower() == 'ссылки'
    )
    dp.register_message_handler(
        handlers.privileges_command,
        lambda message: message.text and message.text.strip().lower() in ['привилегии', 'privileges']
    )

    # inline-кнопки
    callback_handlers = {
        "profile": handlers.profile_button,
        "links": handlers.links_button,
        "reference": handlers.reference_button,
        "shop": handlers.shop_button,
        "roulette": handlers.roulette_button,
        "stickers": handlers.stickers_button,
        "other_bots": handlers.other_bots_button,
        "donate": handlers.donate_button,
        "agreement": handlers.agreement_button,
        "support": handlers.support_button,  # Добавляем новую кнопку
    }

    for callback_data, handler in callback_handlers.items():
        dp.register_callback_query_handler(
            handler,
            lambda c, data=callback_data: c.data == data
        )

    logging.info("✅ Стартовые обработчики зарегистрированы")