# handlers/mute_ban.py
import asyncio
import re
import time
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
import json
import os

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

from database import get_db
from database.crud import UserRepository, ShopRepository
from database.models import UserPurchase

# Файлы для хранения активных мутов/банов
MUTE_STORAGE_FILE = "active_mutes.json"
BAN_STORAGE_FILE = "active_bans.json"
BOT_BAN_STORAGE_FILE = "bot_bans.json"

# Список ID администраторов
ADMIN_IDS = [1054684037]


class BotBanManager:
    """Менеджер для управления банами в боте"""

    def __init__(self, mute_ban_manager):
        self.mute_ban_manager = mute_ban_manager
        self.logger = logging.getLogger(__name__)
        self.bot_bans = self._load_bot_bans()
        self.cleanup_task = None
        self.middleware = None

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

            if user_id_str in self.bot_bans:
                ban_data = self.bot_bans[user_id_str]
                expires_at = ban_data.get('expires_at')

                if expires_at and time.time() > expires_at:
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
                if seconds <= 0:
                    self.logger.error(f"Invalid seconds value: {seconds}")
                    return False

                max_seconds = 315360000
                if seconds > max_seconds:
                    seconds = max_seconds

                ban_data['expires_at'] = time.time() + seconds

                try:
                    expire_date = datetime.now() + timedelta(seconds=seconds)
                    ban_data['expires_at_text'] = expire_date.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OverflowError) as e:
                    self.logger.error(f"Error creating expire date text: {e}")
                    default_expire = datetime.now() + timedelta(days=365)
                    ban_data['expires_at_text'] = default_expire.strftime("%Y-%m-%d %H:%M:%S")

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

                        if self.middleware:
                            user_id = int(user_id_str)
                            self.middleware.add_recently_unbanned(user_id)
                            self.logger.info(f"Notified middleware about unban for user {user_id}")

                for user_id_str in expired_bans:
                    del self.bot_bans[user_id_str]

                if expired_bans:
                    self._save_bot_bans()

                await asyncio.sleep(60)

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
                del self.bot_bans[user_id_str]
                expired_count += 1

        if expired_count > 0:
            self._save_bot_bans()
            self.logger.info(f"Removed {expired_count} expired bot bans during restoration")

        active_count = len(self.bot_bans)
        self.logger.info(f"Restored {active_count} active bot bans")


class MuteBanManager:
    """Менеджер для управления мутами и банами с упрощенными командами"""

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
            if user_id in ADMIN_IDS:
                return True

            db = self._get_db_session()
            try:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if user and user.is_admin:
                    return True
            except Exception as e:
                self.logger.error(f"Error checking if user is admin in DB: {e}")
            finally:
                db.close()

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

    def has_mute_protection(self, user_id: int, chat_id: int) -> bool:
        """Проверяет, есть ли у пользователя защита от мутов - ГЛОБАЛЬНАЯ ВЕРСИЯ"""
        db = next(get_db())
        try:
            print(f"🔍 ДЕТАЛЬНАЯ ПРОВЕРКА ЗАЩИТЫ ОТ МУТОВ:")
            print(f"   👤 Пользователь: {user_id}")
            print(f"   💬 Чат: {chat_id}")

            # ID товаров защиты от мутов
            PROTECTION_ITEM_IDS = [6]  # ID товара "🚫🙊 Защита от !!мут и !бот стоп"

            # Способ 1: Проверка через has_active_purchase (глобальная)
            for item_id in PROTECTION_ITEM_IDS:
                if ShopRepository.has_active_purchase(db, user_id, item_id):
                    print(f"   ✅ Способ 1: Глобальная защита (товар {item_id})")
                    return True

            # Способ 2: Проверка через get_active_purchases
            active_purchases = ShopRepository.get_active_purchases(db, user_id)
            print(f"   🛍️ Все активные покупки: {active_purchases}")

            for item_id in PROTECTION_ITEM_IDS:
                if item_id in active_purchases:
                    print(f"   ✅ Способ 2: Защита через активные покупки (товар {item_id})")
                    return True

            # Способ 3: Прямая проверка в базе данных (глобальная)
            current_time = datetime.now()
            protection_purchases = db.query(UserPurchase).filter(
                UserPurchase.user_id == user_id,
                UserPurchase.item_id.in_(PROTECTION_ITEM_IDS)
                # Убрана проверка chat_id - защита глобальная
            ).all()

            print(f"   📊 Найдено покупок защиты: {len(protection_purchases)}")

            for purchase in protection_purchases:
                print(f"   🛒 Покупка: item_id={purchase.item_id}, expires_at={purchase.expires_at}")
                if purchase.expires_at is None or purchase.expires_at > current_time:
                    print(f"   ✅ Способ 3: Активная глобальная защита (товар {purchase.item_id})")
                    return True

            print(f"   ❌ Все способы проверки: ЗАЩИТЫ НЕТ")
            return False

        except Exception as e:
            print(f"❌ Ошибка детальной проверки защиты: {e}")
            return False
        finally:
            db.close()

    async def _check_admin(self, message: types.Message) -> bool:
        """Проверяет, является ли пользователь администратором"""
        try:
            user_id = message.from_user.id

            if await self._is_user_admin(user_id, message.chat.id if message.chat else None, message.bot):
                return True

            return False
        except Exception as e:
            self.logger.error(f"Error in _check_admin: {e}")
            return False

    async def _check_bot_permissions(self, message: types.Message) -> bool:
        """Проверяет права бота в чате"""
        try:
            if message.chat.type == 'private':
                return True

            bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)

            if bot_member.status == 'restricted':
                if hasattr(bot_member, 'can_send_messages') and not bot_member.can_send_messages:
                    return False
                if hasattr(bot_member, 'can_restrict_members') and not bot_member.can_restrict_members:
                    return False
                return True
            elif bot_member.status == 'administrator':
                if not bot_member.can_restrict_members:
                    return False
                return True
            elif bot_member.status == 'left' or bot_member.status == 'kicked':
                return False
            else:
                return False

        except Exception as e:
            self.logger.error(f"Error checking bot permissions: {e}")
            return False

    async def _get_target_user_from_reply(self, message: types.Message) -> Optional[types.User]:
        """Получает целевого пользователя из reply сообщения"""
        try:
            if not message.reply_to_message:
                return None

            if not message.reply_to_message.from_user:
                return None

            return message.reply_to_message.from_user
        except Exception as e:
            self.logger.error(f"Error getting target user: {e}")
            return None

    async def _check_target_is_admin(self, message: types.Message, user_id: int) -> bool:
        """Проверяет, является ли целевой пользователь администратором"""
        try:
            # Не блокируем себя самого
            if user_id == message.from_user.id:
                return False

            # Проверяем, является ли пользователь администратором бота
            if await self._is_user_admin(user_id, message.chat.id if message.chat else None, message.bot):
                return True

            # В групповых чатах проверяем права администратора
            if message.chat.type in ['group', 'supergroup']:
                try:
                    member = await message.bot.get_chat_member(message.chat.id, user_id)
                    return member.is_chat_admin() or member.status in ['creator', 'administrator']
                except Exception as e:
                    self.logger.warning(f"Could not check chat admin status: {e}")

            return False
        except Exception as e:
            self.logger.warning(f"Error checking target admin status: {e}")
            return False

    def start_cleanup_tasks(self, bot):
        """Запускает задачи для проверки истечения времени мутов/банов"""
        if not self.cleanup_task or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._check_expired_mutes_bans(bot))

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

                            self.logger.info(f"Auto-unbanned user {user_id} in chat {chat_id}")

                        except Exception as e:
                            self.logger.error(f"Error auto-unbanning user {user_id}: {e}")

                # Удаляем истекшие баны
                for ban_id in expired_bans:
                    self.active_bans.pop(ban_id, None)

                if expired_mutes:
                    self._save_active_mutes()
                if expired_bans:
                    self._save_active_bans()

                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)

    # Временные множители
    TIME_MULTIPLIERS = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800
    }

    def parse_time(self, text: str) -> Optional[dict]:
        """Парсит время из строки"""
        if not text:
            return None

        text = text.lower().strip()
        ru_to_en = {'с': 's', 'м': 'm', 'ч': 'h', 'д': 'd', 'н': 'w'}
        for ru, en in ru_to_en.items():
            text = text.replace(ru, en)

        m = re.match(r"^(\d+)([smhdw]?)$", text)
        if not m:
            return None

        value, unit = m.groups()
        value = int(value)

        if not unit:
            unit = 'm'

        if unit not in self.TIME_MULTIPLIERS:
            return None

        seconds = value * self.TIME_MULTIPLIERS[unit]

        max_seconds = 315360000
        if seconds > max_seconds:
            seconds = max_seconds
            value = max_seconds // self.TIME_MULTIPLIERS[unit]

        if unit == 's':
            time_text = f"{value}с"
        elif unit == 'm':
            time_text = f"{value}м"
        elif unit == 'h':
            time_text = f"{value}ч"
        elif unit == 'd':
            time_text = f"{value}д"
        elif unit == 'w':
            time_text = f"{value}н"
        else:
            time_text = f"{value}{unit}"

        return {
            'seconds': seconds,
            'text': time_text
        }

    def _extract_time_from_text(self, text: str) -> Tuple[Optional[int], Optional[str]]:
        """Извлекает время из текста команды (без описания)"""
        if not text:
            return None, None

        words = text.strip().split()
        if not words:
            return None, None

        # Пытаемся распарсить первое слово как время
        time_result = self.parse_time(words[0])
        if time_result:
            seconds = time_result['seconds']
            time_text = time_result['text']
            return seconds, time_text

        return None, None

    async def _process_mute_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду мута"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            if message.chat.type != 'private' and not await self._check_bot_permissions(message):
                await message.reply("❌ У бота нет прав для ограничения пользователей!")
                return

            user = await self._get_target_user_from_reply(message)
            if not user:
                await message.reply("❌ Команда должна быть отправлена в ответ на сообщение пользователя!")
                return

            # ПРОВЕРКА ЗАЩИТЫ: если у целевого пользователя есть защита от мутов
            if self.has_mute_protection(user.id, message.chat.id):
                protection_msg = await message.reply("🛡️ <i>Проверяем защиту пользователя...</i>", parse_mode="HTML")

                await protection_msg.edit_text(
                    f"🛡️ <b>Пользователь защищен от мутов!</b>\n\n"
                    f"👤 <b>{user.full_name}</b> приобрел защиту от команд мутов.\n\n"
                    f"💡 <i>Мут невозможен для этого пользователя</i>",
                    parse_mode="HTML"
                )
                return

            # ПРОВЕРКА: является ли целевой пользователь администратором
            if await self._check_target_is_admin(message, user.id):
                await message.reply(
                    f"❌ <b>Нельзя мутить администратора!</b>\n\n"
                    f"👤 <b>{user.full_name}</b> является администратором.\n\n"
                    f"💡 <i>Мут невозможен для этого пользователя</i>",
                    parse_mode="HTML"
                )
                return

            # Извлекаем время из команды
            text = message.text or ""
            if command_type == 'slash':
                args = message.get_args()
                time_text = args
            else:
                # Для текстовых команд убираем "мут" из текста
                text = text[4:].strip() if text.lower().startswith('мут ') else text
                time_text = text

            seconds, time_display = self._extract_time_from_text(time_text)  # Убрали reason

            # Если время не указано, используем стандартное (30 минут)
            if not seconds:
                seconds = 1800  # 30 минут
                time_display = "30м"

            await self._execute_mute(message, user, seconds, time_display)  # Убрали reason

        except Exception as e:
            self.logger.error(f"Error in _process_mute_command: {e}")
            await message.reply("❌ Произошла ошибка при выполнении команды!")

    async def _process_ban_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду бана"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            if message.chat.type != 'private' and not await self._check_bot_permissions(message):
                await message.reply("❌ У бота нет прав для бана пользователей!")
                return

            user = await self._get_target_user_from_reply(message)
            if not user:
                await message.reply("❌ Команда должна быть отправлена в ответ на сообщение пользователя!")
                return

            # ПРОВЕРКА: является ли целевой пользователь администратором
            if await self._check_target_is_admin(message, user.id):
                await message.reply(
                    f"❌ <b>Нельзя банить администратора!</b>\n\n"
                    f"👤 <b>{user.full_name}</b> является администратором.\n\n"
                    f"💡 <i>Бан невозможен для этого пользователя</i>",
                    parse_mode="HTML"
                )
                return

            # Извлекаем время из команды (без описания)
            text = message.text or ""
            if command_type == 'slash':
                args = message.get_args()
                time_text = args
            else:
                # Для текстовых команд убираем "бан" из текста
                text = text[4:].strip() if text.lower().startswith('бан ') else text
                time_text = text

            seconds, time_display = self._extract_time_from_text(time_text)  # Убрали третий параметр

            # Если время не указано, используем стандартное (1 день)
            if not seconds:
                seconds = 86400  # 1 день
                time_display = "1д"

            await self._execute_ban(message, user, seconds, time_display)

        except Exception as e:
            self.logger.error(f"Error in _process_ban_command: {e}")
            await message.reply("❌ Произошла ошибка при выполнении команды!")

    async def _process_kick_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду кика"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            if message.chat.type != 'private' and not await self._check_bot_permissions(message):
                await message.reply("❌ У бота нет прав для кика пользователей!")
                return

            user = await self._get_target_user_from_reply(message)
            if not user:
                await message.reply("❌ Команда должна быть отправлена в ответ на сообщение пользователя!")
                return

            # ПРОВЕРКА: является ли целевой пользователь администратором
            if await self._check_target_is_admin(message, user.id):
                await message.reply(
                    f"❌ <b>Нельзя кикнуть администратора!</b>\n\n"
                    f"👤 <b>{user.full_name}</b> является администратором.\n\n"
                    f"💡 <i>Кик невозможен для этого пользователя</i>",
                    parse_mode="HTML"
                )
                return

            await self._execute_kick(message, user)

        except Exception as e:
            self.logger.error(f"Error in _process_kick_command: {e}")
            await message.reply("❌ Произошла ошибка при выполнении команды!")

    async def _execute_mute(self, message: types.Message, user: types.User, seconds: int, time_text: str):
        """Выполняет мут пользователя"""
        try:
            until_date = datetime.now() + timedelta(seconds=seconds)

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
            mute_id = f"{message.chat.id}_{user.id}"
            self.active_mutes[mute_id] = {
                'chat_id': message.chat.id,
                'user_id': user.id,
                'user_name': user.full_name,
                'expires_at': time.time() + seconds,
                'admin_id': message.from_user.id,
                'admin_name': message.from_user.full_name
            }
            self._save_active_mutes()

            # Формируем сообщение (без причины)
            text = f"🔇 {user.full_name} замьючен на {time_text}"

            await message.answer(text)
            self.logger.info(f"User {user.id} muted by {message.from_user.id} for {time_text}")

        except Exception as e:
            self.logger.error(f"Error executing mute: {e}")
            raise

    async def _execute_ban(self, message: types.Message, user: types.User, seconds: int, time_text: str):
        """Выполняет бан пользователя"""
        try:
            until_date = datetime.now() + timedelta(seconds=seconds)

            await message.chat.kick(user_id=user.id, until_date=until_date)

            # Сохраняем информацию о бане
            ban_id = f"{message.chat.id}_{user.id}"
            self.active_bans[ban_id] = {
                'chat_id': message.chat.id,
                'user_id': user.id,
                'user_name': user.full_name,
                'expires_at': time.time() + seconds,
                'admin_id': message.from_user.id,
                'admin_name': message.from_user.full_name
            }
            self._save_active_bans()

            # Формируем сообщение (без причины)
            text = f"⛔ {user.full_name} забанен на {time_text}"

            await message.answer(text)
            self.logger.info(f"User {user.id} banned by {message.from_user.id} for {time_text}")

        except Exception as e:
            self.logger.error(f"Error executing ban: {e}")
            raise

    async def _execute_kick(self, message: types.Message, user: types.User):
        """Выполняет кик пользователя"""
        try:
            await message.bot.unban_chat_member(
                chat_id=message.chat.id,
                user_id=user.id,
                only_if_banned=False
            )

            await message.answer(f"👢 {user.full_name} кикнут")
            self.logger.info(f"User {user.id} kicked by {message.from_user.id}")

        except Exception as e:
            self.logger.error(f"Error executing kick: {e}")
            raise

    # Методы для слеш-команд
    async def mute_user(self, message: types.Message):
        """Мутит пользователя (слеш-команда)"""
        await self._process_mute_command(message, 'slash')

    async def ban_user(self, message: types.Message):
        """Банит пользователя (слеш-команда)"""
        await self._process_ban_command(message, 'slash')

    async def kick_user(self, message: types.Message):
        """Кикает пользователя (слеш-команда)"""
        await self._process_kick_command(message, 'slash')

    # Методы для текстовых команд (без слеша)
    async def mute_user_text(self, message: types.Message):
        """Мутит пользователя (текстовая команда)"""
        await self._process_mute_command(message, 'text')

    async def ban_user_text(self, message: types.Message):
        """Банит пользователя (текстовая команда)"""
        await self._process_ban_command(message, 'text')

    async def kick_user_text(self, message: types.Message):
        """Кикает пользователя (текстовая команда)"""
        await self._process_kick_command(message, 'text')

    # Простые текстовые команды без аргументов
    async def simple_mute(self, message: types.Message):
        """Простая команда мута (без времени)"""
        await self._process_mute_command(message, 'text')

    async def simple_kick(self, message: types.Message):
        """Простая команда кика"""
        await self._process_kick_command(message, 'text')

    # Размут и разбан
    async def unmute_user(self, message: types.Message):
        """Снимает мут с пользователя"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            if not await self._check_bot_permissions(message):
                await message.reply("❌ У бота нет прав для снятия ограничений!")
                return

            user = await self._get_target_user_from_reply(message)
            if not user:
                await message.reply("❌ Команда должна быть отправлена в ответ на сообщение пользователя!")
                return

            await message.chat.restrict(
                user_id=user.id,
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
            mute_id = f"{message.chat.id}_{user.id}"
            if mute_id in self.active_mutes:
                del self.active_mutes[mute_id]
                self._save_active_mutes()

            await message.answer(f"🔊 {user.full_name} размучен")
            self.logger.info(f"User {user.id} unmuted by {message.from_user.id}")

        except Exception as e:
            self.logger.error(f"Error in unmute_user: {e}")
            await message.reply("❌ Произошла ошибка при снятии мута!")

    async def unban_user(self, message: types.Message):
        """Разбанивает пользователя"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            if not await self._check_bot_permissions(message):
                await message.reply("❌ У бота нет прав для разбана!")
                return

            user_id = None

            if message.reply_to_message:
                user_id = message.reply_to_message.from_user.id
            else:
                args = message.get_args().split()
                if args and len(args) >= 1:
                    try:
                        user_id = int(args[0])
                    except ValueError:
                        await message.reply("❌ Укажите ID пользователя для разбана!")
                        return

            if not user_id:
                await message.reply(
                    "❌ Команда должна быть отправлена в ответ на сообщение или с указанием ID пользователя!")
                return

            await message.chat.unban(user_id=user_id)

            # Удаляем из активных банов
            ban_id = f"{message.chat.id}_{user_id}"
            if ban_id in self.active_bans:
                del self.active_bans[ban_id]
                self._save_active_bans()

            await message.answer(f"✅ Пользователь {user_id} разбанен")
            self.logger.info(f"User {user_id} unbanned by {message.from_user.id}")

        except Exception as e:
            self.logger.error(f"Error in unban_user: {e}")
            await message.reply("❌ Произошла ошибка при разбане!")

    # Бан в боте
    async def _process_botban_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду бана в боте"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            user_id = None
            user_name = "Пользователь"

            if message.reply_to_message:
                user = message.reply_to_message.from_user
                user_id = user.id
                user_name = user.full_name
            else:
                args, full_text = self._parse_command_text(message, command_type)
                if not args:
                    await message.reply("❌ Укажите пользователя для бана в боте!")
                    return

                target = args[0]

                try:
                    user_id = int(target)
                    user_name = f"ID {user_id}"
                except ValueError:
                    if target.startswith('@'):
                        try:
                            user = await message.bot.get_chat(target)
                            user_id = user.id
                            user_name = user.full_name
                        except Exception as e:
                            await message.reply("❌ Пользователь не найден!")
                            return
                    else:
                        await message.reply("❌ Укажите ID пользователя или @username!")
                        return

            if not user_id:
                await message.reply("❌ Пользователь не найден!")
                return

            if await self._check_target_is_admin(message, user_id):
                await message.reply("❌ Нельзя банить администратора в боте!")
                return

            args, full_text = self._parse_command_text(message, command_type)
            seconds = None
            reason = "Не указана"

            if args:
                remaining_args = args[1:] if len(args) > 1 else []

                if remaining_args:
                    time_result = self.parse_time(remaining_args[0])
                    if time_result:
                        seconds = time_result['seconds']
                        time_text = time_result['text']
                        if len(remaining_args) > 1:
                            reason = ' '.join(remaining_args[1:])
                    else:
                        reason = ' '.join(remaining_args) if remaining_args else "Не указана"
                        time_text = "навсегда"
                else:
                    time_text = "навсегда"
            else:
                time_text = "навсегда"

            success = await self.bot_ban_manager.ban_user_in_bot(
                user_id=user_id,
                admin_id=message.from_user.id,
                reason=reason,
                seconds=seconds
            )

            if success:
                text = f"🚫 {user_name} забанен в боте"
                if seconds:
                    text += f" на {time_text}"
                if reason:
                    text += f"\n📝 Причина: {reason}"

                await message.answer(text)
                self.logger.info(f"User {user_id} bot-banned by {message.from_user.id}")

        except Exception as e:
            self.logger.error(f"Error in _process_botban_command: {e}")
            await message.reply("❌ Произошла ошибка при бане в боте!")

    async def _process_botunban_command(self, message: types.Message, command_type: str):
        """Обрабатывает команду разбана в боте"""
        try:
            if not await self._check_admin(message):
                await message.reply("❌ У вас нет прав администратора!")
                return

            user_id = None

            if message.reply_to_message:
                user_id = message.reply_to_message.from_user.id
            else:
                args, full_text = self._parse_command_text(message, command_type)
                if not args:
                    await message.reply("❌ Укажите пользователя для разбана в боте!")
                    return

                target = args[0]

                try:
                    user_id = int(target)
                except ValueError:
                    if target.startswith('@'):
                        try:
                            user = await message.bot.get_chat(target)
                            user_id = user.id
                        except Exception as e:
                            await message.reply("❌ Пользователь не найден!")
                            return
                    else:
                        await message.reply("❌ Укажите ID пользователя или @username!")
                        return

            if not user_id:
                await message.reply("❌ Пользователь не найден!")
                return

            success = await self.bot_ban_manager.unban_user_in_bot(user_id)

            if success:
                await message.answer(f"✅ Пользователь {user_id} разбанен в боте")
                self.logger.info(f"User {user_id} bot-unbanned by {message.from_user.id}")

        except Exception as e:
            self.logger.error(f"Error in _process_botunban_command: {e}")
            await message.reply("❌ Произошла ошибка при разбане в боте!")

    def _parse_command_text(self, message: types.Message, command_type: str) -> Tuple[List[str], str]:
        """Парсит текст команды"""
        try:
            if command_type == 'slash':
                args_text = message.get_args()
                if not args_text:
                    return [], ""

                args = args_text.split()
                return args, args_text

            else:
                text = message.text.strip()

                command_patterns = [
                    ('ботбан ', 7), ('разботбан', 9)
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

    async def check_bot_ban(self, user_id: int) -> bool:
        """Проверяет, забанен ли пользователь в боте"""
        return self.bot_ban_manager.is_user_bot_banned(user_id)

    async def get_bot_ban_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о бане пользователя в боте"""
        return self.bot_ban_manager.get_ban_info(user_id)

    async def simple_ban(self, message: types.Message):
        """Простая команда бана (без времени)"""
        await self._process_ban_command(message, 'text')

    async def restore_mutes_after_restart(self, bot):
        """Восстанавливает активные муты после перезапуска бота"""
        self.logger.info("Restoring active mutes after restart...")

        await self.bot_ban_manager.restore_bans_after_restart()

        for mute_id, mute_data in list(self.active_mutes.items()):
            try:
                chat_id = mute_data['chat_id']
                user_id = mute_data['user_id']
                expires_at = mute_data['expires_at']

                if time.time() > expires_at:
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
                    del self.active_mutes[mute_id]
                    self.logger.info(f"Removed expired mute for user {user_id} in chat {chat_id}")
                else:
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
                del self.active_mutes[mute_id]

        self._save_active_mutes()
        self.logger.info("Active mutes restoration completed")


def register_mute_ban_handlers(dp: Dispatcher):
    """Регистрирует обработчики мутов и банов"""
    manager = MuteBanManager()

    # Основные команды модерации (английские слеш-команды)
    dp.register_message_handler(manager.mute_user, Command("mute"))
    dp.register_message_handler(manager.unmute_user, Command("unmute"))
    dp.register_message_handler(manager.ban_user, Command("ban"))
    dp.register_message_handler(manager.unban_user, Command("unban"))
    dp.register_message_handler(manager.kick_user, Command("kick"))

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

    # Текстовые команды (без слеша) - ТОЛЬКО ОПРЕДЕЛЕННЫЕ ФОРМАТЫ
    dp.register_message_handler(
        manager.mute_user_text,
        lambda m: m.text and (
                m.text.lower() == 'мут' or
                re.match(r'^мут\s+\d+[smhdw]?$', m.text.lower().strip()) or
                re.match(r'^мут\s+\d+[смчдн]?$', m.text.lower().strip())
        )
    )

    dp.register_message_handler(
        manager.ban_user_text,
        lambda m: m.text and (
                m.text.lower() == 'бан' or
                re.match(r'^бан\s+\d+[smhdw]?$', m.text.lower().strip()) or
                re.match(r'^бан\s+\d+[смчдн]?$', m.text.lower().strip())
        )
    )

    dp.register_message_handler(
        manager.kick_user_text,
        lambda m: m.text and m.text.lower().strip() == 'кик'
    )

    dp.register_message_handler(
        manager.botban_user_text,
        lambda m: m.text and m.text.lower().startswith('ботбан ')
    )

    # Простые текстовые команды (просто "мут", "бан", "кик" без аргументов)
    dp.register_message_handler(manager.simple_mute, lambda m: m.text and m.text.lower().strip() == 'мут')
    dp.register_message_handler(manager.simple_ban, lambda m: m.text and m.text.lower().strip() == 'бан')
    dp.register_message_handler(manager.simple_kick, lambda m: m.text and m.text.lower().strip() == 'кик')

    # Текстовые команды для размута и разбана
    dp.register_message_handler(manager.unmute_user, lambda m: m.text and m.text.lower().startswith('размут'))
    dp.register_message_handler(manager.unban_user, lambda m: m.text and m.text.lower().startswith('разбан'))
    dp.register_message_handler(manager.botunban_user_text, lambda m: m.text and m.text.lower().startswith('разботбан'))

    print("✅ Mute/Ban обработчики зарегистрированы (с ГЛОБАЛЬНОЙ защитой от мутов)")
    return manager