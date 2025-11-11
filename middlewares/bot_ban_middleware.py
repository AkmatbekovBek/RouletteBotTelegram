# middlewares/bot_ban_middleware.py
import logging
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler


class BotBanMiddleware(BaseMiddleware):
    def __init__(self, mute_ban_manager):
        super().__init__()
        self.mute_ban_manager = mute_ban_manager
        self.logger = logging.getLogger(__name__)
        self.recently_unbanned = set()  # Храним ID пользователей, которым уже отправили уведомление

    async def on_pre_process_message(self, message: types.Message, data: dict):
        # Пропускаем служебные сообщения
        if not message.text and not message.caption:
            return

        user_id = message.from_user.id

        # Проверяем, не был ли пользователь только что разбанен
        if user_id in self.recently_unbanned:
            # Отправляем уведомление о разбане только в ЛС
            if message.chat.type == 'private':
                try:
                    await message.answer(
                        "✅ Ваш бан в боте закончился!\n\n"
                        "Теперь вы снова можете использовать все команды бота. "
                        "Пожалуйста, соблюдайте правила, чтобы избежать повторных ограничений."
                    )
                    self.logger.info(f"Sent unban notification to user {user_id} in private chat")
                except Exception as e:
                    self.logger.error(f"Error sending unban notification: {e}")

            # Удаляем из временного списка после отправки уведомления
            self.recently_unbanned.remove(user_id)
            return

        # Пропускаем команды от администраторов
        if await self.mute_ban_manager._is_user_admin(user_id, message.chat.id if message.chat else None,
                                                      message.bot):
            return

        # Проверяем, забанен ли пользователь в боте
        if await self.mute_ban_manager.check_bot_ban(user_id):
            self.logger.info(f"Blocked command from bot-banned user {user_id}")

            # Если это ЛС с ботом - отправляем сообщение о бане
            if message.chat.type == 'private':
                # Получаем информацию о бане
                ban_info = await self.mute_ban_manager.get_bot_ban_info(user_id)
                if ban_info:
                    reason = ban_info.get('reason', 'Не указана')
                    banned_at = ban_info.get('banned_at_text', 'Неизвестно')
                    expires_at = ban_info.get('expires_at_text')

                    if expires_at:
                        response_text = (
                            f"🚫 Вы забанены в боте!\n\n"
                            f"📝 Причина: {reason}\n"
                            f"🕒 Забанен: {banned_at}\n"
                            f"⏰ Срок: до {expires_at}\n\n"
                            f"⚠️ Вы не можете использовать команды бота до окончания бана."
                        )
                    else:
                        response_text = (
                            f"🚫 Вы забанены в боте навсегда!\n\n"
                            f"📝 Причина: {reason}\n"
                            f"🕒 Забанен: {banned_at}\n\n"
                            f"⚠️ Вы не можете использовать команды бота."
                        )
                else:
                    response_text = "🚫 Вы забанены в боте и не можете использовать команды."

                try:
                    await message.answer(response_text)
                except Exception as e:
                    self.logger.error(f"Error sending ban message: {e}")

            # В чатах молчим и просто блокируем команды
            # Останавливаем обработку сообщения
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        user_id = callback_query.from_user.id

        # Проверяем, не был ли пользователь только что разбанен
        if user_id in self.recently_unbanned:
            # Для колбэков тоже показываем уведомление о разбане
            try:
                await callback_query.answer(
                    "✅ Ваш бан закончился! Теперь вы можете использовать функции бота.",
                    show_alert=True
                )
                self.logger.info(f"Sent unban notification to user {user_id} via callback")
            except Exception as e:
                self.logger.error(f"Error sending unban notification in callback: {e}")

            # Удаляем из временного списка
            self.recently_unbanned.remove(user_id)
            return

        # Пропускаем колбэки от администраторов
        if await self.mute_ban_manager._is_user_admin(user_id,
                                                      callback_query.message.chat.id if callback_query.message else None,
                                                      callback_query.bot):
            return

        # Проверяем, забанен ли пользователь в боте
        if await self.mute_ban_manager.check_bot_ban(user_id):
            self.logger.info(f"Blocked callback from bot-banned user {user_id}")

            # Для колбэков всегда показываем уведомление
            try:
                await callback_query.answer("🚫 Вы забанены в боте и не можете использовать эту функцию.",
                                            show_alert=True)
            except Exception as e:
                self.logger.error(f"Error answering callback: {e}")

            # Останавливаем обработку колбэка
            raise CancelHandler()

    def add_recently_unbanned(self, user_id: int):
        """Добавляет пользователя в список недавно разбаненных"""
        self.recently_unbanned.add(user_id)
        self.logger.info(f"Added user {user_id} to recently unbanned list")