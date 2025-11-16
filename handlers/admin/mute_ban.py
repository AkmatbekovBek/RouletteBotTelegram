# handlers/admin/mute_ban.py

import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from aiogram import types
from aiogram.dispatcher import Dispatcher

from database import get_db
from database.crud import ModerationLogRepository
from database.models import ModerationAction

# Используем те же ID, что и в admin.py — дублируем для независимости
# (или можно импортировать из admin, но это рискует циклическим импортом)
ADMIN_IDS: List[int] = [6090751674, 1054684037]


logger = logging.getLogger(__name__)


class MuteBanManager:
    """Менеджер модерации: mute/ban/kick с проверкой админов и логированием"""

    def __init__(self):
        self.active_mutes = {}  # chat_id -> {user_id: unmute_time}
        self.logger = logger
        self.bot = None

    async def _is_user_admin(self, user_id: int, chat_id: int = None, *args, **kwargs) -> bool:
        """Проверка: является ли пользователь админом (для совместимости с BotBanMiddleware)"""
        """
        Проверяет, является ли пользователь админом (для BotBanMiddleware).
        Поддерживает:
        - Глобальных админов (из ADMIN_IDS)
        - Админов чата (опционально)
        """
        # 1. Проверяем глобальных админов (из ADMIN_IDS)
        if user_id in ADMIN_IDS:
            return True

        # 2. (Опционально) Проверяем админов чата, если chat_id указан
        if chat_id is not None:
            try:
                chat_member = await self.bot.get_chat_member(chat_id, user_id)
                return chat_member.status in ("administrator", "creator")
            except Exception:
                pass

        return False

    def is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    async def mute_user(
        self,
        bot,
        chat_id: int,
        user_id: int,
        admin_id: int,
        duration_minutes: int = 60,
        reason: str = "Без причины"
    ) -> bool:
        try:
            until_date = datetime.utcnow() + timedelta(minutes=duration_minutes)
            permissions = types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            )
            await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)

            # Лог в БД
            db = next(get_db())
            try:
                ModerationLogRepository.add_log(
                    db=db,
                    action=ModerationAction.MUTE,
                    chat_id=chat_id,
                    user_id=user_id,
                    admin_id=admin_id,
                    reason=reason,
                    duration_minutes=duration_minutes
                )
            finally:
                db.close()

            # Сохраняем для автоматического снятия
            if chat_id not in self.active_mutes:
                self.active_mutes[chat_id] = {}
            self.active_mutes[chat_id][user_id] = until_date

            self.logger.info(f"🔇 {user_id} замучен в {chat_id} на {duration_minutes} мин админом {admin_id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка мута {user_id}: {e}")
            return False

    async def ban_user(
        self,
        bot,
        chat_id: int,
        user_id: int,
        admin_id: int,
        reason: str = "Без причины"
    ) -> bool:
        try:
            await bot.kick_chat_member(chat_id, user_id)

            db = next(get_db())
            try:
                ModerationLogRepository.add_log(
                    db=db,
                    action=ModerationAction.BAN,
                    chat_id=chat_id,
                    user_id=user_id,
                    admin_id=admin_id,
                    reason=reason
                )
            finally:
                db.close()

            self.logger.info(f"🚫 {user_id} забанен в {chat_id} админом {admin_id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка бана {user_id}: {e}")
            return False

    async def kick_user(
        self,
        bot,
        chat_id: int,
        user_id: int,
        admin_id: int,
        reason: str = "Без причины"
    ) -> bool:
        try:
            # kick = ban + unban
            await bot.kick_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)

            db = next(get_db())
            try:
                ModerationLogRepository.add_log(
                    db=db,
                    action=ModerationAction.KICK,
                    chat_id=chat_id,
                    user_id=user_id,
                    admin_id=admin_id,
                    reason=reason
                )
            finally:
                db.close()

            self.logger.info(f"📤 {user_id} кикнут из {chat_id} админом {admin_id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка кика {user_id}: {e}")
            return False

    # ===== Фоновые задачи =====

    def start_cleanup_tasks(self, bot):
        self.bot = bot
        asyncio.create_task(self._unmute_scheduler(bot))

    async def _unmute_scheduler(self, bot):
        while True:
            now = datetime.utcnow()
            to_remove = []
            for chat_id, mutes in list(self.active_mutes.items()):
                for user_id, unmute_time in list(mutes.items()):
                    if now >= unmute_time:
                        try:
                            # Восстанавливаем права
                            perms = types.ChatPermissions(
                                can_send_messages=True,
                                can_send_media_messages=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True
                            )
                            await bot.restrict_chat_member(chat_id, user_id, perms)
                            self.logger.info(f"🔈 Автоматический анмут {user_id} в {chat_id}")
                        except Exception as e:
                            self.logger.warning(f"⚠️ Не удалось размутить {user_id} в {chat_id}: {e}")
                        to_remove.append((chat_id, user_id))

            # Очистка
            for chat_id, user_id in to_remove:
                self.active_mutes[chat_id].pop(user_id, None)
                if not self.active_mutes[chat_id]:
                    self.active_mutes.pop(chat_id, None)

            await asyncio.sleep(30)

    async def restore_mutes_after_restart(self, bot):
        # Заглушка: можно реализовать через SELECT * FROM moderation_logs WHERE action = 'mute' AND ...
        self.logger.info("⏭️ Восстановление мутов после перезапуска (не реализовано)")

    async def stop_cleanup_tasks(self):
        pass  # можно добавить флаг остановки при желании


# ===== ХЭНДЛЕРЫ — регистрируются при импорте =====

# Глобальный экземпляр (как в твоём стиле)
mute_ban_manager = MuteBanManager()


async def cmd_mute(message: types.Message):
    if not mute_ban_manager.is_admin(message.from_user.id):
        return

    # /mute 30m @user или /mute 30m reply
    args = message.text.split()[1:]
    if not args:
        await message.answer("📌 Использование: /mute 5m [ответ или @username]")
        return

    # Парсим длительность: 5m, 1h, 30m и т.д.
    duration_str = args[0].lower()
    match = re.match(r"^(\d+)([mh])$", duration_str)
    if not match:
        await message.answer("⚠️ Неверный формат времени. Пример: 5m, 1h")
        return

    amount, unit = int(match.group(1)), match.group(2)
    minutes = amount if unit == "m" else amount * 60

    # Определяем целевого пользователя
    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif len(args) > 1:
        username = args[1].lstrip("@")
        # Здесь можно добавить поиск по username в БД, но для простоты — только reply
        await message.answer("📌 Укажите пользователя ответом на его сообщение.")
        return

    if not target_user:
        await message.answer("📌 Ответьте командой на сообщение пользователя.")
        return

    if target_user.id in ADMIN_IDS:
        await message.answer("🛡️ Нельзя применять к администраторам.")
        return

    success = await mute_ban_manager.mute_user(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=target_user.id,
        admin_id=message.from_user.id,
        duration_minutes=minutes,
        reason="Модерация"
    )

    if success:
        await message.answer(f"🔇 @{target_user.username or target_user.id} замучен на {minutes} мин.")
    else:
        await message.answer("❌ Не удалось замутить пользователя.")


async def cmd_ban(message: types.Message):
    if not mute_ban_manager.is_admin(message.from_user.id):
        return

    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        await message.answer("📌 Ответьте командой на сообщение пользователя.")
        return

    if target_user.id in ADMIN_IDS:
        await message.answer("🛡️ Нельзя банить администраторов.")
        return

    success = await mute_ban_manager.ban_user(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=target_user.id,
        admin_id=message.from_user.id,
        reason="Модерация"
    )

    if success:
        await message.answer(f"🚫 @{target_user.username or target_user.id} забанен.")
    else:
        await message.answer("❌ Не удалось забанить пользователя.")


async def cmd_kick(message: types.Message):
    if not mute_ban_manager.is_admin(message.from_user.id):
        return

    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        await message.answer("📌 Ответьте командой на сообщение пользователя.")
        return

    if target_user.id in ADMIN_IDS:
        await message.answer("🛡️ Нельзя кикать администраторов.")
        return

    success = await mute_ban_manager.kick_user(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=target_user.id,
        admin_id=message.from_user.id,
        reason="Модерация"
    )

    if success:
        await message.answer(f"📤 @{target_user.username or target_user.id} кикнут.")
    else:
        await message.answer("❌ Не удалось кикнуть пользователя.")


# ===== Регистрация хэндлеров при импорте =====
# (работает как раньше — без вызова register_* из main.py)

def setup_handlers(dp: Dispatcher):
    dp.register_message_handler(cmd_mute, commands=["mute"])
    dp.register_message_handler(cmd_ban, commands=["ban"])
    dp.register_message_handler(cmd_kick, commands=["kick"])


# Выполняется при импорте — как в твоём стиле
from config import dp
setup_handlers(dp)