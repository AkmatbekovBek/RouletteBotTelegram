# handlers/mute_ban.py
import asyncio
import re
import time
import logging
from typing import Optional, Dict, List, Tuple
from aiogram import types, Dispatcher
from aiogram.dispatcher.filters import Command
from aiogram.utils.exceptions import (
    ChatAdminRequired,
    NotEnoughRightsToRestrict,
    BadRequest,
    UserIsAnAdministratorOfTheChat,
    BotKicked,
    BotBlocked
)
from datetime import datetime, timedelta
import json
import os

from database import get_db
from database.crud import UserRepository

# Файлы для хранения активных мутов/банов
MUTE_STORAGE_FILE = "active_mutes.json"
BAN_STORAGE_FILE = "active_bans.json"
BOT_BAN_STORAGE_FILE = "bot_bans.json"  # Новый файл для банов в боте

# Список ID администраторов (должен совпадать с admin.py)
ADMIN_IDS = [1054684037]  # Замените на реальные ID админов


class BotBanManager:
    """Менеджер для управления банами в боте"""

    def __init__(self, mute_ban_manager):
        self.mute_ban_manager = mute_ban_manager
        self.logger = logging.getLogger(__name__)
        self.bot_bans = self._load_bot_bans()
        self.cleanup_task = None
        self.middleware = None  # Будет установлено позже

    def set_middleware(self, middleware):
        """Устанавливает ссылку на middleware для отправки уведомлений"""
        self.middleware = middleware

    def _load_bot_bans(self) -> Dict:
        """Загружает баны в боте из файла"""
        try:
            if os.path.exists(BOT_BAN_STORAGE_FILE):
                with open(BOT_BAN_STORAGE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.logger.info(f"✅ Загружено {len(data)} банов из файла")
                    return data
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки банов: {e}")
        return {}

    def _save_bot_bans(self):
        """Сохраняет баны в боте в файл"""
        try:
            with open(BOT_BAN_STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.bot_bans, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения банов: {e}")

    def is_user_bot_banned(self, user_id: int) -> bool:
        """Проверяет, забанен ли пользователь в боте с автоочисткой истекших"""
        try:
            user_id_str = str(user_id)

            # Проверяем в активных банах
            if user_id_str in self.bot_bans:
                ban_data = self.bot_bans[user_id_str]
                expires_at = ban_data.get('expires_at')

                # Если бан временный и время истекло
                if expires_at and time.time() > expires_at:
                    # Удаляем истекший бан
                    del self.bot_bans[user_id_str]
                    self._save_bot_bans()
                    self.logger.info(f"✅ Автоочистка истекшего бана для пользователя {user_id}")
                    return False

                return True

            return False
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки бана: {e}")
            return False

    async def ban_user_in_bot(self, user_id: int, admin_id: int, reason: str = "Не указана",
                              seconds: int = None) -> bool:
        """Банит пользователя в боте"""
        try:
            user_id_str = str(user_id)

            ban_data = {
                'user_id': user_id,
                'admin_id': admin_id,
                'reason': reason,
                'banned_at': time.time(),
                'banned_at_text': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            if seconds:
                ban_data['expires_at'] = time.time() + seconds
                ban_data['expires_at_text'] = (datetime.now() + timedelta(seconds=seconds)).strftime(
                    "%Y-%m-%d %H:%M:%S")

            self.bot_bans[user_id_str] = ban_data
            self._save_bot_bans()

            self.logger.info(f"User {user_id} banned in bot by {admin_id} for {seconds} seconds, reason: {reason}")
            return True

        except Exception as e:
            self.logger.error(f"Error banning user in bot: {e}")
            return False

    async def unban_user_in_bot(self, user_id: int) -> bool:
        """Разбанивает пользователя в боте"""
        try:
            user_id_str = str(user_id)

            if user_id_str in self.bot_bans:
                del self.bot_bans[user_id_str]
                self._save_bot_bans()

                # Уведомляем middleware о ручном разбане
                if self.middleware:
                    self.middleware.add_recently_unbanned(user_id)
                    self.logger.info(f"Notified middleware about manual unban for user {user_id}")

                self.logger.info(f"User {user_id} unbanned in bot")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Error unbanning user in bot: {e}")
            return False

    def get_ban_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о бане пользователя в боте"""
        try:
            user_id_str = str(user_id)
            return self.bot_bans.get(user_id_str)
        except Exception as e:
            self.logger.error(f"Error getting ban info: {e}")
            return None

    def start_cleanup_task(self):
        """Запускает задачу проверки истекших банов"""
        if not self.cleanup_task or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._cleanup_expired_bans())

    async def stop_cleanup_task(self):
        """Останавливает задачу очистки"""
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            self.cleanup_task = None

    async def _cleanup_expired_bans(self):
        """Фоновая задача для проверки и удаления истекших банов"""
        while True:
            try:
                current_time = time.time()
                expired_bans = []

                for user_id_str, ban_data in list(self.bot_bans.items()):
                    expires_at = ban_data.get('expires_at')
                    if expires_at and current_time > expires_at:
                        expired_bans.append(user_id_str)
                        self.logger.info(f"Auto-removed expired bot ban for user {user_id_str}")

                        # Уведомляем middleware о разбане
                        if self.middleware:
                            user_id = int(user_id_str)
                            self.middleware.add_recently_unbanned(user_id)
                            self.logger.info(f"Notified middleware about unban for user {user_id}")

                # Удаляем истекшие баны
                for user_id_str in expired_bans:
                    del self.bot_bans[user_id_str]

                if expired_bans:
                    self._save_bot_bans()

                await asyncio.sleep(60)  # Проверяем каждую минуту

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in bot ban cleanup task: {e}")
                await asyncio.sleep(300)

    async def restore_bans_after_restart(self):
        """Восстанавливает баны после перезапуска бота"""
        self.logger.info("Restoring bot bans after restart...")

        current_time = time.time()
        expired_count = 0

        for user_id_str, ban_data in list(self.bot_bans.items()):
            expires_at = ban_data.get('expires_at')
            if expires_at and current_time > expires_at:
                # Удаляем истекшие баны
                del self.bot_bans[user_id_str]
                expired_count += 1

        if expired_count > 0:
            self._save_bot_bans()
            self.logger.info(f"Removed {expired_count} expired bot bans during restoration")

        active_count = len(self.bot_bans)
        self.logger.info(f"Restored {active_count} active bot bans")


class MuteBanManager:
    """Менеджер для управления мутами и банами с проверками безопасности"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.active_mutes = self._load_active_mutes()
        self.active_bans = self._load_active_bans()
        self.bot_ban_manager = BotBanManager(self)
        self.cleanup_task = None

    def _get_db_session(self):
        """Создает сессию БД с обработкой ошибок"""
        try:
            return next(get_db())
        except Exception as e:
            self.logger.error(f"Database connection error: {e}")
            raise

    def _load_active_mutes(self) -> Dict:
        """Загружает активные муты из файла"""
        try:
            if os.path.exists(MUTE_STORAGE_FILE):
                with open(MUTE_STORAGE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading mutes: {e}")
        return {}

    def _load_active_bans(self) -> Dict:
        """Загружает активные баны из файла"""
        try:
            if os.path.exists(BAN_STORAGE_FILE):
                with open(BAN_STORAGE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading bans: {e}")
        return {}

    def _save_active_mutes(self):
        """Сохраняет активные муты в файл"""
        try:
            with open(MUTE_STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.active_mutes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving mutes: {e}")

    def _save_active_bans(self):
        """Сохраняет активные баны в файл"""
        try:
            with open(BAN_STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.active_bans, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving bans: {e}")

    async def _is_user_admin(self, user_id: int, chat_id: int = None, bot=None) -> bool:
        """Проверяет, является ли пользователь администратором"""
        try:
            # Проверяем основные админы
            if user_id in ADMIN_IDS:
                return True

            # Проверяем админов из БД
            db = self._get_db_session()
            try:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if user and user.is_admin:
                    return True
            except Exception as e:
                self.logger.error(f"Error checking if user is admin in DB: {e}")
            finally:
                db.close()

            # Проверяем, является ли пользователь админом чата
            if chat_id and bot:
                try:
                    member = await bot.get_chat_member(chat_id, user_id)
                    return member.is_chat_admin() or member.status in ['creator', 'administrator']
                except Exception as e:
                    self.logger.warning(f"Error checking chat admin status: {e}")

            return False
        except Exception as e:
            self.logger.error(f"Error in _is_user_admin: {e}")
            return False

    async def _check_admin(self, message: types.Message) -> bool:
        """Проверяет, является ли пользователь администратором"""
        try:
            user_id = message.from_user.id

            if await self._is_user_admin(user_id, message.chat.id if message.chat else None, message.bot):
                return True

            # Не отправляем сообщение если бот не может писать в чат
            try:
                await message.answer("❌ У вас нет прав администратора")
            except BadRequest:
                pass  # Бот не может писать в чат
            return False
        except Exception as e:
            self.logger.error(f"Error in _check_admin: {e}")
            return False

    async def _check_bot_permissions(self, message: types.Message) -> bool:
        """Проверяет права бота в чате с улучшенной обработкой ошибок"""
        try:
            # Если это личные сообщения с ботом, пропускаем проверку
            if message.chat.type == 'private':
                return True

            bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)

            # Проверяем различные статусы бота
            if bot_member.status == 'restricted':
                # Бот ограничен в правах
                if hasattr(bot_member, 'can_send_messages') and not bot_member.can_send_messages:
                    self.logger.warning(f"❌ Бот не может отправлять сообщения в чате {message.chat.id}")
                    return False
                if hasattr(bot_member, 'can_restrict_members') and not bot_member.can_restrict_members:
                    self.logger.warning(f"❌ Бот не может ограничивать пользователей в чате {message.chat.id}")
                    return False
                return True
            elif bot_member.status == 'administrator':
                # Бот - администратор
                if not bot_member.can_restrict_members:
                    try:
                        await message.answer("❌ У бота нет прав для ограничения пользователей")
                    except BadRequest:
                        pass
                    return False
                return True
            elif bot_member.status == 'left' or bot_member.status == 'kicked':
                # Бот вышел из чата или был кикнут
                self.logger.warning(f"❌ Бот не является участником чата {message.chat.id}")
                return False
            else:
                # Бот обычный участник
                try:
                    await message.answer("❌ Бот не является администратором чата")
                except BadRequest:
                    pass
                return False

        except BotKicked:
            self.logger.warning(f"❌ Бот был кикнут из чата {message.chat.id}")
            return False
        except BotBlocked:
            self.logger.warning(f"❌ Бот заблокирован в чате {message.chat.id}")
            return False
        except BadRequest as e:
            self.logger.error(f"BadRequest checking bot permissions: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error checking bot permissions: {e}")
            return False

    async def _get_target_user_from_reply(self, message: types.Message) -> Optional[types.User]:
        """Получает целевого пользователя из reply сообщения"""
        try:
            if not message.reply_to_message:
                try:
                    await message.answer("❌ Ответьте на сообщение пользователя, чтобы выполнить действие")
                except BadRequest:
                    pass
                return None

            if not message.reply_to_message.from_user:
                try:
                    await message.answer("❌ Не удалось определить пользователя")
                except BadRequest:
                    pass
                return None

            return message.reply_to_message.from_user
        except Exception as e:
            self.logger.error(f"Error getting target user: {e}")
            return None

    async def _get_target_user_id_from_args(self, message: types.Message) -> Optional[int]:
        """Получает ID пользователя из аргументов команды"""
        try:
            args = message.get_args().split()
            if not args:
                return None

            try:
                return int(args[0])
            except ValueError:
                return None

        except Exception as e:
            self.logger.error(f"Error getting user id from args: {e}")
            return None

    async def _check_target_is_admin(self, message: types.Message, user_id: int) -> bool:
        """Проверяет, является ли целевой пользователь администратором"""
        try:
            # Нельзя мутить/банить самого себя
            if user_id == message.from_user.id:
                try:
                    await message.answer("❌ Нельзя выполнить действие над самим собой")
                except BadRequest:
                    pass
                return True

            # Нельзя мутить/банить других админов
            if await self._is_user_admin(user_id, message.chat.id if message.chat else None, message.bot):
                try:
                    await message.answer("❌ Нельзя выполнить действие над администратором")
                except BadRequest:
                    pass
                return True

            return False
        except Exception as e:
            self.logger.warning(f"Could not check admin status: {e}")
            return False

    def start_cleanup_tasks(self, bot):
        """Запускает задачи для проверки истечения времени мутов/банов"""
        if not self.cleanup_task or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._check_expired_mutes_bans(bot))

        # Запускаем задачу очистки банов в боте
        self.bot_ban_manager.start_cleanup_task()

    async def stop_cleanup_tasks(self):
        """Останавливает задачи очистки"""
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            self.cleanup_task = None

        # Останавливаем задачу очистки банов
        await self.bot_ban_manager.stop_cleanup_task()

    async def _check_expired_mutes_bans(self, bot):
        """Проверяет истечение времени мутов и банов"""
        while True:
            try:
                current_time = time.time()
                expired_mutes = []
                expired_bans = []

                # Проверяем муты
                for mute_id, mute_data in list(self.active_mutes.items()):
                    if mute_data.get('expires_at') and current_time > mute_data['expires_at']:
                        expired_mutes.append(mute_id)

                        try:
                            chat_id = mute_data['chat_id']
                            user_id = mute_data['user_id']

                            chat = await bot.get_chat(chat_id)
                            await chat.restrict(
                                user_id=user_id,
                                permissions=types.ChatPermissions(
                                    can_send_messages=True,
                                    can_send_media_messages=True,
                                    can_send_polls=True,
                                    can_send_other_messages=True,
                                    can_add_web_page_previews=True,
                                    can_change_info=False,
                                    can_invite_users=True,
                                    can_pin_messages=False
                                ),
                            )

                            # Отправляем сообщение о снятии мута
                            user_name = mute_data.get('user_name', 'Пользователь')
                            try:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"🔊 Мут автоматически снят с {user_name}\n⏰ Время мута истекло"
                                )
                            except Exception as e:
                                self.logger.warning(f"Could not send unmute message: {e}")

                            self.logger.info(f"Auto-unmuted user {user_id} in chat {chat_id}")

                        except Exception as e:
                            self.logger.error(f"Error auto-unmuting user {user_id}: {e}")

                # Удаляем истекшие муты
                for mute_id in expired_mutes:
                    self.active_mutes.pop(mute_id, None)

                # Проверяем баны
                for ban_id, ban_data in list(self.active_bans.items()):
                    if ban_data.get('expires_at') and current_time > ban_data['expires_at']:
                        expired_bans.append(ban_id)

                        try:
                            chat_id = ban_data['chat_id']
                            user_id = ban_data['user_id']

                            chat = await bot.get_chat(chat_id)
                            await chat.unban(user_id=user_id)

                            # Отправляем сообщение о разбане
                            user_name = ban_data.get('user_name', 'Пользователь')
                            try:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"✅ Пользователь {user_name} автоматически разбанен\n⏰ Время бана истекло"
                                )
                            except Exception as e:
                                self.logger.warning(f"Could not send unban message: {e}")

                            self.logger.info(f"Auto-unbanned user {user_id} in chat {chat_id}")

                        except Exception as e:
                            self.logger.error(f"Error auto-unbanning user {user_id}: {e}")

                # Удаляем истекшие баны
                for ban_id in expired_bans:
                    self.active_bans.pop(ban_id, None)

                # УДАЛЕНО: await self.bot_ban_manager.check_expired_bot_bans()
                # Баны в боте теперь проверяются в отдельной задаче _cleanup_expired_bans()

                # Сохраняем изменения
                if expired_mutes:
                    self._save_active_mutes()
                if expired_bans:
                    self._save_active_bans()

                await asyncio.sleep(30)  # Проверяем каждые 30 секунд

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)

    # Временные множители
    TIME_MULTIPLIERS = {
        's': 1,  # секунды
        'm': 60,  # минуты
        'h': 3600,  # часы
        'd': 86400,  # дни
        'w': 604800  # недели
    }

    TIME_LABELS = {
        's': 'секунд',
        'm': 'минут',
        'h': 'часов',
        'd': 'дней',
        'w': 'недель'
    }

    def parse_time(self, text: str) -> Optional[dict]:
        """
        Преобразует строку 10m, 2h, 1d, 30s и т.д. в количество секунд и текстовое представление.
        Поддерживает русские и английские обозначения.
        """
        if not text:
            return None

        # Заменяем русские обозначения на английские
        text = text.lower().strip()
        ru_to_en = {'с': 's', 'м': 'm', 'ч': 'h', 'д': 'd', 'н': 'w'}
        for ru, en in ru_to_en.items():
            text = text.replace(ru, en)

        # Ищем паттерн: число + опциональная буква
        m = re.match(r"^(\d+)([smhdw]?)$", text)
        if not m:
            return None

        value, unit = m.groups()
        value = int(value)

        # Если единица не указана, используем минуты по умолчанию
        if not unit:
            unit = 'm'

        if unit not in self.TIME_MULTIPLIERS:
            return None

        seconds = value * self.TIME_MULTIPLIERS[unit]

        # Формируем читаемое время
        if unit == 's':
            time_text = f"{value} {self._get_plural_form(value, ['секунда', 'секунды', 'секунд'])}"
        elif unit == 'm':
            time_text = f"{value} {self._get_plural_form(value, ['минута', 'минуты', 'минут'])}"
        elif unit == 'h':
            time_text = f"{value} {self._get_plural_form(value, ['час', 'часа', 'часов'])}"
        elif unit == 'd':
            time_text = f"{value} {self._get_plural_form(value, ['день', 'дня', 'дней'])}"
        elif unit == 'w':
            time_text = f"{value} {self._get_plural_form(value, ['неделя', 'недели', 'недель'])}"
        else:
            time_text = f"{value} {self.TIME_LABELS[unit]}"

        return {
            'seconds': seconds,
            'text': time_text
        }

    def _get_plural_form(self, n: int, forms: List[str]) -> str:
        """Возвращает правильную форму слова для числа"""
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
            return forms[1]
        else:
            return forms[2]

    def _parse_command_text(self, message: types.Message, command_type: str) -> Tuple[List[str], str]:
        """
        Парсит текст команды для разных типов команд
        """
        try:
            if command_type == 'slash':
                # Для слеш-команд используем get_args()
                args_text = message.get_args()
                if not args_text:
                    return [], ""

                args = args_text.split()
                return args, args_text

            else:  # command_type == 'text'
                # Для текстовых команд парсим весь текст
                text = message.text.strip()

                # Определяем команду и убираем ее из текста
                command_patterns = [
                    ('мут ', 4), ('бан ', 4), ('кик ', 4), ('ботбан ', 7),
                    ('размут', 6), ('разбан', 6), ('разботбан', 9)
                ]

                for pattern, length in command_patterns:
                    if text.lower().startswith(pattern):
                        text = text[length:].strip()
                        break

                args = text.split() if text else []
                return args, text

        except Exception as e:
            self.logger.error(f"Error parsing command text: {e}")
            return [], ""

    # Новые методы для бана в боте
    async def botban_user(self, message: types.Message):
        """Банит пользователя в боте (слеш-команда)"""
        await self._process_botban_command(message, 'slash')

    async def botunban_user(self, message: types.Message):
        """Разбанивает пользователя в боте (слеш-команда)"""
        await self._process_botunban_command(message, 'slash')

    async def botban_user_text(self, message: types.Message):
        """Банит пользователя в боте (текстовая команда)"""
        await self._process_botban_command(message, 'text')

    async def botunban_user_text(self, message: types.Message):
        """Разбанивает пользователя в боте (текстовая команда)"""
        await self._process_botunban_command(message, 'text')

    async def _process_botban_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду бана в боте"""
        try:
            # Проверяем права администратора
            if not await self._check_admin(message):
                return

            # Получаем целевого пользователя
            user_id = None
            user_name = "Пользователь"

            if message.reply_to_message:
                user = message.reply_to_message.from_user
                user_id = user.id
                user_name = user.full_name
            else:
                # Пытаемся получить user_id из аргументов
                user_id = await self._get_target_user_id_from_args(message)
                if not user_id:
                    try:
                        await message.answer("❌ Ответьте на сообщение пользователя или укажите ID: /botban [ID]")
                    except BadRequest:
                        pass
                    return
                user_name = f"ID {user_id}"

            if not user_id:
                try:
                    await message.answer("❌ Не удалось определить пользователя")
                except BadRequest:
                    pass
                return

            # Проверяем, не является ли пользователь администратором или самим собой
            if await self._check_target_is_admin(message, user_id):
                return

            # Парсим аргументы команды
            args, full_text = self._parse_command_text(message, command_type)
            seconds = None
            reason = "Не указана"

            if args:
                # Пытаемся распарсить время из первого аргумента
                time_result = self.parse_time(args[0])
                if time_result:
                    seconds = time_result['seconds']
                    time_text = time_result['text']
                    # Остальные аргументы - причина (если есть)
                    if len(args) > 1:
                        reason = ' '.join(args[1:])
                else:
                    # Если время не распарсилось, все аргументы - причина
                    reason = full_text
                    time_text = "навсегда"
            else:
                time_text = "навсегда"

            # Баним пользователя в боте
            success = await self.bot_ban_manager.ban_user_in_bot(
                user_id=user_id,
                admin_id=message.from_user.id,
                reason=reason,
                seconds=seconds
            )

            if success:
                text = f"🚫 Пользователь {user_name} забанен в боте"
                if seconds:
                    text += f" на {time_text}"
                else:
                    text += " навсегда"
                text += f"\n📝 Причина: {reason}"

                if seconds:
                    text += f"\n⏰ Бан автоматически сниму через {time_text}"

                await message.answer(text)
                self.logger.info(f"User {user_id} bot-banned by {message.from_user.id}")
            else:
                await message.answer("❌ Произошла ошибка при бане пользователя в боте")

        except Exception as e:
            self.logger.error(f"Error in _process_botban_command: {e}")
            try:
                await message.answer("❌ Произошла ошибка при выполнении действия")
            except BadRequest:
                pass

    async def _process_botunban_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду разбана в боте"""
        try:
            # Проверяем права администратора
            if not await self._check_admin(message):
                return

            # Получаем целевого пользователя
            user_id = None

            if message.reply_to_message:
                user_id = message.reply_to_message.from_user.id
            else:
                # Пытаемся получить user_id из аргументов
                user_id = await self._get_target_user_id_from_args(message)
                if not user_id:
                    try:
                        await message.answer("❌ Ответьте на сообщение пользователя или укажите ID: /botunban [ID]")
                    except BadRequest:
                        pass
                    return

            if not user_id:
                try:
                    await message.answer("❌ Не удалось определить пользователя")
                except BadRequest:
                    pass
                return

            # Разбаниваем пользователя в боте
            success = await self.bot_ban_manager.unban_user_in_bot(user_id)

            if success:
                await message.answer(f"✅ Пользователь {user_id} разбанен в боте")
                self.logger.info(f"User {user_id} bot-unbanned by {message.from_user.id}")
            else:
                await message.answer("❌ Пользователь не забанен в боте или произошла ошибка")

        except Exception as e:
            self.logger.error(f"Error in _process_botunban_command: {e}")
            try:
                await message.answer("❌ Произошла ошибка при выполнении действия")
            except BadRequest:
                pass

    async def check_bot_ban(self, user_id: int) -> bool:
        """Проверяет, забанен ли пользователь в боте (публичный метод для других хендлеров)"""
        return self.bot_ban_manager.is_user_bot_banned(user_id)

    async def get_bot_ban_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о бане пользователя в боте"""
        return self.bot_ban_manager.get_ban_info(user_id)

    # Остальные существующие методы остаются без изменений...
    # [Здесь должны быть все остальные методы из предыдущей версии класса MuteBanManager]
    # Для экономии места я не дублирую их все, но они должны остаться

    async def _process_mute_ban_command(self, message: types.Message, command_type: str, action_type: str):
        """Общий метод для обработки команд мута и бана"""
        try:
            # Проверяем права администратора
            if not await self._check_admin(message):
                return

            # Проверяем права бота (если не в личных сообщениях)
            if message.chat.type != 'private' and not await self._check_bot_permissions(message):
                return

            # Получаем целевого пользователя
            user = await self._get_target_user_from_reply(message)
            if not user:
                return

            # Парсим аргументы команды
            args, full_text = self._parse_command_text(message, command_type)
            seconds = None
            reason = "Не указана"

            if args:
                # Пытаемся распарсить время из первого аргумента
                time_result = self.parse_time(args[0])
                if time_result:
                    seconds = time_result['seconds']
                    time_text = time_result['text']
                    # Остальные аргументы - причина (если есть)
                    if len(args) > 1:
                        reason = ' '.join(args[1:])
                else:
                    # Если время не распарсилось, все аргументы - причина
                    reason = full_text
                    time_text = "навсегда"
            else:
                time_text = "навсегда"

            # Проверяем, не является ли пользователь администратором или самим собой
            if await self._check_target_is_admin(message, user.id):
                return

            # Выполняем действие в зависимости от типа
            if action_type == 'mute':
                await self._execute_mute(message, user, seconds, reason, time_text)

            elif action_type == 'ban':
                await self._execute_ban(message, user, seconds, reason, time_text)

            elif action_type == 'kick':
                await self._execute_kick(message, user, reason)

        except Exception as e:
            self.logger.error(f"Error in _process_mute_ban_command: {e}")
            try:
                await message.answer("❌ Произошла ошибка при выполнении действия")
            except BadRequest:
                pass

    async def _execute_mute(self, message: types.Message, user: types.User, seconds: int, reason: str, time_text: str):
        """Выполняет мут пользователя"""
        try:
            if seconds:
                until_date = datetime.now() + timedelta(seconds=seconds)
            else:
                until_date = None

            await message.chat.restrict(
                user_id=user.id,
                permissions=types.ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=until_date,
            )

            # Сохраняем информацию о муте
            if seconds:
                mute_id = f"{message.chat.id}_{user.id}"
                self.active_mutes[mute_id] = {
                    'chat_id': message.chat.id,
                    'user_id': user.id,
                    'user_name': user.full_name,
                    'expires_at': time.time() + seconds,
                    'reason': reason,
                    'admin_id': message.from_user.id,
                    'admin_name': message.from_user.full_name
                }
                self._save_active_mutes()

            # Формируем сообщение
            text = f"🔇 Пользователь {user.full_name} получил мут"
            if seconds:
                text += f" на {time_text}"
            else:
                text += " навсегда"
            text += f"\n📝 Причина: {reason}"

            if seconds:
                text += f"\n⏰ Мут автоматически сниму через {time_text}"

            await message.answer(text)
            self.logger.info(f"User {user.id} muted by {message.from_user.id} for {time_text}, reason: {reason}")

        except ChatAdminRequired:
            try:
                await message.answer("❌ У бота нет прав для выполнения этого действия")
            except BadRequest:
                pass
        except NotEnoughRightsToRestrict:
            try:
                await message.answer("❌ Недостаточно прав, чтобы выполнить это действие")
            except BadRequest:
                pass
        except BadRequest as e:
            try:
                await message.answer(f"❌ Ошибка Telegram: {e}")
            except BadRequest:
                pass
        except Exception as e:
            self.logger.error(f"Error executing mute: {e}")
            try:
                await message.answer("❌ Произошла ошибка при муте пользователя")
            except BadRequest:
                pass

    async def _execute_ban(self, message: types.Message, user: types.User, seconds: int, reason: str, time_text: str):
        """Выполняет бан пользователя"""
        try:
            if seconds:
                until_date = datetime.now() + timedelta(seconds=seconds)
            else:
                until_date = None

            await message.chat.kick(user_id=user.id, until_date=until_date)

            # Сохраняем информацию о бане
            if seconds:
                ban_id = f"{message.chat.id}_{user.id}"
                self.active_bans[ban_id] = {
                    'chat_id': message.chat.id,
                    'user_id': user.id,
                    'user_name': user.full_name,
                    'expires_at': time.time() + seconds,
                    'reason': reason,
                    'admin_id': message.from_user.id,
                    'admin_name': message.from_user.full_name
                }
                self._save_active_bans()

            # Формируем сообщение
            text = f"⛔ Пользователь {user.full_name} забанен"
            if seconds:
                text += f" на {time_text}"
            else:
                text += " навсегда"
            text += f"\n📝 Причина: {reason}"

            if seconds:
                text += f"\n⏰ Бан автоматически сниму через {time_text}"

            await message.answer(text)
            self.logger.info(f"User {user.id} banned by {message.from_user.id} for {time_text}, reason: {reason}")

        except ChatAdminRequired:
            try:
                await message.answer("❌ У бота нет прав для выполнения этого действия")
            except BadRequest:
                pass
        except BadRequest as e:
            try:
                await message.answer(f"❌ Ошибка Telegram: {e}")
            except BadRequest:
                pass
        except Exception as e:
            self.logger.error(f"Error executing ban: {e}")
            try:
                await message.answer("❌ Произошла ошибка при бане пользователя")
            except BadRequest:
                pass

    async def _execute_kick(self, message: types.Message, user: types.User, reason: str):
        """Выполняет кик пользователя без бана и ЧС"""
        try:
            # Используем unban_chat_member для кика без бана
            await message.bot.unban_chat_member(
                chat_id=message.chat.id,
                user_id=user.id,
                only_if_banned=False  # Это позволяет кикнуть даже если пользователь не забанен
            )

            await message.answer(f"👢 Пользователь {user.full_name} кикнут\n📝 Причина: {reason}")
            self.logger.info(f"User {user.id} kicked by {message.from_user.id}, reason: {reason}")

        except ChatAdminRequired:
            try:
                await message.answer("❌ У бота нет прав для выполнения этого действия")
            except BadRequest:
                pass
        except BadRequest as e:
            error_msg = str(e).lower()
            if "user is an administrator" in error_msg:
                try:
                    await message.answer("❌ Нельзя кикнуть администратора чата")
                except BadRequest:
                    pass
            elif "not enough rights" in error_msg:
                try:
                    await message.answer("❌ Недостаточно прав для кика пользователя")
                except BadRequest:
                    pass
            elif "user not found" in error_msg:
                try:
                    await message.answer("❌ Пользователь не найден в чате")
                except BadRequest:
                    pass
            else:
                try:
                    await message.answer(f"❌ Ошибка Telegram: {e}")
                except BadRequest:
                    pass
        except Exception as e:
            self.logger.error(f"Error executing kick: {e}")
            try:
                await message.answer("❌ Произошла ошибка при кике пользователя")
            except BadRequest:
                pass

    # Методы для слеш-команд
    async def mute_user(self, message: types.Message):
        """Мутит пользователя (слеш-команда)"""
        await self._process_mute_ban_command(message, 'slash', 'mute')

    async def unmute_user(self, message: types.Message):
        """Снимает мут с пользователя"""
        try:
            if not await self._check_admin(message):
                return

            if not await self._check_bot_permissions(message):
                return

            # Получаем пользователя из reply или из аргументов
            user = None
            user_id = None
            user_name = "Пользователь"

            if message.reply_to_message:
                user = message.reply_to_message.from_user
                user_id = user.id
                user_name = user.full_name
            else:
                # Пытаемся получить user_id из аргументов
                args = message.get_args().split()
                if args:
                    try:
                        user_id = int(args[0])
                        user_name = f"ID {user_id}"
                    except ValueError:
                        try:
                            await message.answer("❌ Неверный формат ID пользователя")
                        except BadRequest:
                            pass
                        return
                else:
                    try:
                        await message.answer("❌ Ответьте на сообщение пользователя или укажите ID: /unmute [ID]")
                    except BadRequest:
                        pass
                    return

            if not user_id:
                try:
                    await message.answer("❌ Не удалось определить пользователя")
                except BadRequest:
                    pass
                return

            # Снимаем ограничения
            await message.chat.restrict(
                user_id=user_id,
                permissions=types.ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False
                ),
            )

            # Удаляем из активных мутов
            mute_id = f"{message.chat.id}_{user_id}"
            if mute_id in self.active_mutes:
                del self.active_mutes[mute_id]
                self._save_active_mutes()
                self.logger.info(f"Removed mute record for user {user_id}")

            try:
                await message.answer(f"🔊 Мут снят с {user_name}")
            except BadRequest:
                pass
            self.logger.info(f"User {user_id} unmuted by {message.from_user.id}")

        except BadRequest as e:
            error_msg = str(e).lower()
            if "user not found" in error_msg:
                try:
                    await message.answer("❌ Пользователь не найден в этом чате")
                except BadRequest:
                    pass
            elif "not enough rights" in error_msg:
                try:
                    await message.answer("❌ Недостаточно прав для снятия мута")
                except BadRequest:
                    pass
            elif "can't remove chat owner" in error_msg:
                try:
                    await message.answer("❌ Нельзя снять мут с создателя чата")
                except BadRequest:
                    pass
            else:
                try:
                    await message.answer(f"❌ Ошибка Telegram API: {e}")
                except BadRequest:
                    pass
        except Exception as e:
            self.logger.error(f"Error in unmute_user: {e}")
            try:
                await message.answer("❌ Произошла ошибка при снятии мута")
            except BadRequest:
                pass

    async def ban_user(self, message: types.Message):
        """Банит пользователя (слеш-команда)"""
        await self._process_mute_ban_command(message, 'slash', 'ban')

    async def unban_user(self, message: types.Message):
        """Разбанивает пользователя"""
        try:
            if not await self._check_admin(message):
                return

            if not await self._check_bot_permissions(message):
                return

            user_id = None

            if message.reply_to_message:
                # Если есть reply, используем ID из reply
                user_id = message.reply_to_message.from_user.id
            else:
                # Иначе используем аргументы
                args = message.get_args().split()
                if args and len(args) >= 1:
                    try:
                        user_id = int(args[0])
                    except ValueError:
                        try:
                            await message.answer("❌ Неверный формат. ID должен быть числом")
                        except BadRequest:
                            pass
                        return
                else:
                    try:
                        await message.answer("❌ Использование: /unban [ID пользователя] или ответьте на сообщение")
                    except BadRequest:
                        pass
                    return

            if not user_id:
                try:
                    await message.answer("❌ Не удалось определить пользователя")
                except BadRequest:
                    pass
                return

            await message.chat.unban(user_id=user_id)

            # Удаляем из активных банов
            ban_id = f"{message.chat.id}_{user_id}"
            if ban_id in self.active_bans:
                del self.active_bans[ban_id]
                self._save_active_bans()

            try:
                await message.answer(f"✅ Пользователь {user_id} разбанен")
            except BadRequest:
                pass
            self.logger.info(f"User {user_id} unbanned by {message.from_user.id}")

        except BadRequest as e:
            if "user not found" in str(e).lower() or "not in the chat" in str(e).lower():
                try:
                    await message.answer("❌ Пользователь не найден в бане этого чата")
                except BadRequest:
                    pass
            else:
                try:
                    await message.answer(f"❌ Ошибка: {e}")
                except BadRequest:
                    pass
        except Exception as e:
            self.logger.error(f"Error in unban_user: {e}")
            try:
                await message.answer("❌ Произошла ошибка при разбане")
            except BadRequest:
                pass

    async def kick_user(self, message: types.Message):
        """Кикает пользователя (слеш-команда)"""
        await self._process_mute_ban_command(message, 'slash', 'kick')

    # Методы для текстовых команд (без слеша)
    async def mute_user_text(self, message: types.Message):
        """Мутит пользователя (текстовая команда)"""
        await self._process_mute_ban_command(message, 'text', 'mute')

    async def ban_user_text(self, message: types.Message):
        """Банит пользователя (текстовая команда)"""
        await self._process_mute_ban_command(message, 'text', 'ban')

    async def kick_user_text(self, message: types.Message):
        """Кикает пользователя (текстовая команда)"""
        await self._process_mute_ban_command(message, 'text', 'kick')

    # Простые текстовые команды без аргументов
    async def simple_ban(self, message: types.Message):
        """Простая команда бана"""
        await self._process_simple_command(message, 'ban')

    async def simple_mute(self, message: types.Message):
        """Простая команда мута"""
        await self._process_simple_command(message, 'mute')

    async def simple_kick(self, message: types.Message):
        """Простая команда кика"""
        await self._process_simple_command(message, 'kick')

    async def _process_simple_command(self, message: types.Message, action_type: str):
        """Обрабатывает простые команды без аргументов"""
        try:
            # Проверяем права администратора
            if not await self._check_admin(message):
                return

            # Проверяем права бота
            if not await self._check_bot_permissions(message):
                return

            user = await self._get_target_user_from_reply(message)
            if not user:
                return

            # Проверяем, не является ли пользователь администратором или самим собой
            if await self._check_target_is_admin(message, user.id):
                return

            reason = "Не указана"

            if action_type == 'mute':
                await self._execute_mute(message, user, None, reason, "навсегда")
            elif action_type == 'ban':
                await self._execute_ban(message, user, None, reason, "навсегда")
            elif action_type == 'kick':
                await self._execute_kick(message, user, reason)

        except Exception as e:
            self.logger.error(f"Error in simple_{action_type}: {e}")
            try:
                await message.answer("❌ Произошла ошибка при выполнении действия")
            except BadRequest:
                pass

    async def unmute_user_text(self, message: types.Message):
        """Снимает мут (текстовая команда)"""
        await self.unmute_user(message)

    async def unban_user_text(self, message: types.Message):
        """Разбанивает пользователя (текстовая команда)"""
        await self.unban_user(message)

    async def restore_mutes_after_restart(self, bot):
        """Восстанавливает активные муты после перезапуска бота"""
        self.logger.info("Restoring active mutes after restart...")

        await self.bot_ban_manager.restore_bans_after_restart()

        for mute_id, mute_data in list(self.active_mutes.items()):
            try:
                chat_id = mute_data['chat_id']
                user_id = mute_data['user_id']
                expires_at = mute_data['expires_at']

                # Проверяем не истекло ли время
                if time.time() > expires_at:
                    # Мут истек, снимаем его
                    chat = await bot.get_chat(chat_id)
                    await chat.restrict(
                        user_id=user_id,
                        permissions=types.ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=True,
                            can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                            can_change_info=False,
                            can_invite_users=True,
                            can_pin_messages=False
                        ),
                    )
                    # Удаляем из активных
                    del self.active_mutes[mute_id]
                    self.logger.info(f"Removed expired mute for user {user_id} in chat {chat_id}")
                else:
                    # Мут еще активен, обновляем права
                    until_date = datetime.fromtimestamp(expires_at)
                    chat = await bot.get_chat(chat_id)
                    await chat.restrict(
                        user_id=user_id,
                        permissions=types.ChatPermissions(
                            can_send_messages=False,
                            can_send_media_messages=False,
                            can_send_polls=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                            can_change_info=False,
                            can_invite_users=False,
                            can_pin_messages=False
                        ),
                        until_date=until_date,
                    )
                    self.logger.info(f"Restored mute for user {user_id} in chat {chat_id}")

            except Exception as e:
                self.logger.error(f"Error restoring mute {mute_id}: {e}")
                # Если не удалось восстановить, удаляем из активных
                del self.active_mutes[mute_id]

        self._save_active_mutes()
        self.logger.info("Active mutes restoration completed")

    async def temp_ban_user(self, message: types.Message):
        """Временный бан пользователя"""
        await self.ban_user(message)

    async def warn_user(self, message: types.Message):
        """Выдает предупреждение пользователю"""
        try:
            if not await self._check_admin(message):
                return

            user = await self._get_target_user_from_reply(message)
            if not user:
                return

            reason = message.get_args() or "Не указана"

            try:
                await message.answer(
                    f"⚠️ Пользователь {user.full_name} получил предупреждение\n"
                    f"📝 Причина: {reason}\n\n"
                    f"ℹ️ При повторных нарушениях последуют более строгие меры"
                )
            except BadRequest:
                pass
            self.logger.info(f"User {user.id} warned by {message.from_user.id}, reason: {reason}")

        except Exception as e:
            self.logger.error(f"Error in warn_user: {e}")
            try:
                await message.answer("❌ Произошла ошибка при выдаче предупреждения")
            except BadRequest:
                pass


def register_mute_ban_handlers(dp: Dispatcher):
    """Регистрирует обработчики мутов и банов"""
    manager = MuteBanManager()

    # Основные команды модерации (английские слеш-команды)
    dp.register_message_handler(manager.mute_user, Command("mute"))
    dp.register_message_handler(manager.unmute_user, Command("unmute"))
    dp.register_message_handler(manager.ban_user, Command("ban"))
    dp.register_message_handler(manager.unban_user, Command("unban"))
    dp.register_message_handler(manager.kick_user, Command("kick"))
    dp.register_message_handler(manager.temp_ban_user, Command("tempban"))
    dp.register_message_handler(manager.warn_user, Command("warn"))

    # Новые команды для бана в боте
    dp.register_message_handler(manager.botban_user, Command("botban"))
    dp.register_message_handler(manager.botunban_user, Command("botunban"))

    # Русские слеш-команды
    dp.register_message_handler(manager.mute_user, commands=["мут"])
    dp.register_message_handler(manager.unmute_user, commands=["размут"])
    dp.register_message_handler(manager.ban_user, commands=["бан"])
    dp.register_message_handler(manager.unban_user, commands=["разбан"])
    dp.register_message_handler(manager.kick_user, commands=["кик"])

    # Русские команды для бана в боте
    dp.register_message_handler(manager.botban_user, commands=["ботбан"])
    dp.register_message_handler(manager.botunban_user, commands=["разботбан"])

    # Текстовые команды (без слеша) с аргументами
    dp.register_message_handler(manager.mute_user_text, lambda m: m.text and m.text.lower().startswith('мут '))
    dp.register_message_handler(manager.ban_user_text, lambda m: m.text and m.text.lower().startswith('бан '))
    dp.register_message_handler(manager.kick_user_text, lambda m: m.text and m.text.lower().startswith('кик '))
    dp.register_message_handler(manager.botban_user_text, lambda m: m.text and m.text.lower().startswith('ботбан '))

    # Простые текстовые команды (просто "бан", "мут", "кик" без аргументов)
    dp.register_message_handler(manager.simple_ban, lambda m: m.text and m.text.lower().strip() == 'бан')
    dp.register_message_handler(manager.simple_mute, lambda m: m.text and m.text.lower().strip() == 'мут')
    dp.register_message_handler(manager.simple_kick, lambda m: m.text and m.text.lower().strip() == 'кик')

    # Текстовые команды для размута и разбана
    dp.register_message_handler(manager.unmute_user_text, lambda m: m.text and m.text.lower().startswith('размут'))
    dp.register_message_handler(manager.unban_user_text, lambda m: m.text and m.text.lower().startswith('разбан'))
    dp.register_message_handler(manager.botunban_user_text, lambda m: m.text and m.text.lower().startswith('разботбан'))

    print("✅ Mute/Ban обработчики зарегистрированы")
    return manager