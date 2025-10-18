import asyncio
import logging
from aiogram import types, Dispatcher
from aiogram.utils.exceptions import MessageToDeleteNotFound, MessageCantBeDeleted, CantRestrictChatOwner, \
    ChatAdminRequired
from database import get_db
from database.crud import BotStopRepository

logger = logging.getLogger(__name__)


class BotStopHandler:
    def __init__(self):
        self.logger = logger
        self.cooldown_dict = {}  # Защита от флуда
        self.active_chats = set()  # Кэш активных чатов

    def _check_cooldown(self, user_id: int, chat_id: int) -> bool:
        """Проверка кулдауна для защиты от флуда с учетом чата"""
        current_time = asyncio.get_event_loop().time()
        key = f"{chat_id}_{user_id}"

        if key in self.cooldown_dict:
            if current_time - self.cooldown_dict[key] < 3:  # 3 секунды кулдаун
                return False
        self.cooldown_dict[key] = current_time
        return True

    async def _check_bot_permissions(self, chat: types.Chat, bot_user_id: int) -> tuple:
        """Проверяет права бота в чате с улучшенной обработкой ошибок"""
        try:
            # Для личных чатов всегда возвращаем успех
            if chat.type in ['private']:
                return True, None

            try:
                bot_member = await chat.get_member(bot_user_id)
            except Exception as e:
                self.logger.warning(f"Could not get bot member info in chat {chat.id}: {e}")
                return False, "❌ Не удалось получить информацию о правах бота"

            # Для каналов и супергрупп проверяем права администратора
            if chat.type in ['channel', 'supergroup', 'group']:
                if not bot_member.is_chat_admin():
                    return False, "❌ Бот не является администратором чата"

                # Проверяем конкретные права для удаления сообщений
                if not bot_member.can_delete_messages:
                    return False, "❌ У бота нет прав на удаление сообщений"

            return True, None

        except Exception as e:
            self.logger.error(f"Error checking bot permissions in chat {chat.id}: {e}")
            return False, f"❌ Ошибка проверки прав: {e}"

    async def _has_bot_permissions_cached(self, chat_id: int, bot_user_id: int) -> bool:
        """Проверяет права бота с кэшированием"""
        if chat_id in self.active_chats:
            return True

        try:
            chat = await self._get_chat(chat_id)
            has_perms, _ = await self._check_bot_permissions(chat, bot_user_id)
            if has_perms:
                self.active_chats.add(chat_id)
            return has_perms
        except:
            return False

    async def bot_stop(self, message: types.Message):
        """Обработчик команды 'бот стоп' - запрещает отвечать на сообщения"""
        try:
            # Проверка кулдауна
            if not self._check_cooldown(message.from_user.id, message.chat.id):
                return

            # Проверяем, что команда отправлена не в личном чате
            if message.chat.type == 'private':
                await message.reply(
                    "❌ Эта команда работает только в группах, супергруппах и каналах.\n"
                    "В личных сообщениях эта функция не нужна."
                )
                return

            # Проверяем права бота
            bot_user = await message.bot.get_me()
            has_permissions, error_msg = await self._check_bot_permissions(message.chat, bot_user.id)
            if not has_permissions:
                await message.reply(
                    f"{error_msg}\n\n"
                    "📋 Для работы команды 'бот стоп' необходимо:\n"
                    "• Сделать бота администратором\n"
                    "• Дать право на удаление сообщений\n"
                    "• В каналах - права администратора"
                )
                return

            if not message.reply_to_message:
                await message.reply(
                    "❗ Команду нужно отправить **в ответ** на сообщение пользователя.\n\n"
                    "**Как использовать:**\n"
                    "1. Найдите сообщение пользователя\n"
                    "2. Ответьте на него командой 'бот стоп'\n"
                    "3. Теперь этому пользователю будет запрещено отвечать на ваши сообщения"
                )
                return

            user1 = message.from_user  # Тот, кто использует команду
            user2 = message.reply_to_message.from_user  # Тот, кого блокируют

            # Проверяем, не пытается ли пользователь заблокировать самого себя
            if user1.id == user2.id:
                await message.reply("❌ Нельзя заблокировать самого себя!")
                return

            # Проверяем, не пытается ли заблокировать бота
            if user2.id == bot_user.id:
                await message.reply("❌ Нельзя заблокировать бота!")
                return

            # Проверяем, не является ли user2 создателем чата
            try:
                chat_member = await message.chat.get_member(user2.id)
                if chat_member.status == 'creator':
                    await message.reply("❌ Нельзя заблокировать создателя чата!")
                    return
            except Exception as e:
                self.logger.debug(f"Could not check user status: {e}")

            db = next(get_db())
            try:
                # Проверяем существование записи о блокировке
                existing_record = BotStopRepository.get_block_record(db, user1.id, user2.id)

                if existing_record:
                    # 🔓 Разблокировка - удаляем запись
                    BotStopRepository.delete_block_record(db, user1.id, user2.id)
                    db.commit()

                    self.logger.info(
                        f"User {user1.id} unblocked user {user2.id} from replying in chat {message.chat.id}")

                    response = await message.reply(
                        f"✅ {user1.full_name} разрешил {user2.full_name} отвечать на свои сообщения.\n\n"
                        f"Теперь {user2.full_name} может свободно отвечать на ваши сообщения."
                    )

                else:
                    # 🔒 Блокировка - создаем запись
                    BotStopRepository.create_block_record(db, user1.id, user2.id)
                    db.commit()

                    self.logger.info(f"User {user1.id} blocked user {user2.id} from replying in chat {message.chat.id}")

                    response = await message.reply(
                        f"🚫 {user1.full_name} запретил {user2.full_name} отвечать на свои сообщения.\n\n"
                        f"📝 **Что это значит:**\n"
                        f"• Бот будет автоматически удалять ответы {user2.full_name} на ваши сообщения\n"
                        f"• Заблокированный пользователь получит уведомление\n"
                        f"• Ограничение действует во всех чатах\n"
                        f"• Для снятия блокировки используйте команду снова\n\n"
                        f"⚙️ Для отмены: ответьте 'бот стоп' на любое сообщение {user2.full_name}"
                    )

                # Удаляем исходную команду через 10 секунд для чистоты чата
                await asyncio.sleep(10)
                try:
                    await message.delete()
                    await asyncio.sleep(5)
                    await response.delete()
                except Exception as e:
                    self.logger.debug(f"Could not delete messages: {e}")

            except Exception as e:
                db.rollback()
                self.logger.error(f"Database error in bot_stop: {e}")
                await message.reply("❌ Произошла ошибка при выполнении команды. Попробуйте позже.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in bot_stop: {e}")
            await message.reply("❌ Произошла непредвиденная ошибка. Попробуйте позже.")

    async def check_reply_restrictions(self, message: types.Message):
        """Проверяет и удаляет сообщения, которые являются ответами на запрещенные сообщения"""
        try:
            # Пропускаем команды и служебные сообщения
            if message.text and (message.text.startswith(('/', '!', 'бот стоп', 'бот старт'))):
                return

            # Проверяем, что находимся не в личном чате
            if message.chat.type == 'private':
                return

            # Проверяем, является ли сообщение ответом на другое сообщение
            if not message.reply_to_message:
                return

            replied_user_id = message.reply_to_message.from_user.id
            current_user_id = message.from_user.id

            # Если пользователь отвечает самому себе - пропускаем
            if replied_user_id == current_user_id:
                return

            # Получаем ID бота
            bot_user = await message.bot.get_me()

            # Пропускаем сообщения от бота
            if current_user_id == bot_user.id:
                return

            db = next(get_db())
            try:
                # Проверяем, запрещено ли текущему пользователю отвечать на сообщения того пользователя
                is_blocked = BotStopRepository.is_reply_blocked(db, current_user_id, replied_user_id)

                if is_blocked:
                    # Проверяем права бота перед удалением
                    has_permissions, _ = await self._check_bot_permissions(message.chat, bot_user.id)

                    if has_permissions:
                        # Удаляем сообщение и уведомляем
                        try:
                            await message.delete()
                            self.logger.info(
                                f"Deleted reply from {current_user_id} to {replied_user_id} in chat {message.chat.id}")

                            # Отправляем предупреждение пользователю
                            warning_msg = await message.answer(
                                f"🚫 {message.from_user.full_name}, вам запрещено отвечать на сообщения этого пользователя.\n"
                                f"❌ Ваше сообщение было удалено."
                            )
                            # Удаляем предупреждение через 8 секунд
                            await asyncio.sleep(8)
                            try:
                                await warning_msg.delete()
                            except Exception as e:
                                self.logger.debug(f"Could not delete warning message: {e}")

                        except (MessageToDeleteNotFound, MessageCantBeDeleted) as e:
                            self.logger.warning(f"Could not delete message in chat {message.chat.id}: {e}")
                            # Если не удалось удалить, отправляем предупреждение
                            warning = await message.reply(
                                f"🚫 {message.from_user.full_name}, вам запрещено отвечать на сообщения этого пользователя.\n"
                                f"⚠️ Сообщение не было удалено (недостаточно прав бота)"
                            )
                            await asyncio.sleep(8)
                            try:
                                await warning.delete()
                            except Exception as e:
                                self.logger.debug(f"Could not delete warning: {e}")

                        except Exception as delete_error:
                            self.logger.error(f"Error deleting blocked reply in chat {message.chat.id}: {delete_error}")
                    else:
                        # Бот не имеет прав для удаления, но уведомляем о нарушении
                        warning = await message.reply(
                            f"⚠️ {message.from_user.full_name}, вам запрещено отвечать на сообщения этого пользователя.\n"
                            f"📢 Нарушение зафиксировано, но бот не может удалить сообщение (недостаточно прав)"
                        )
                        await asyncio.sleep(10)
                        try:
                            await warning.delete()
                        except Exception as e:
                            self.logger.debug(f"Could not delete warning: {e}")

            except Exception as e:
                self.logger.error(f"Database error in check_reply_restrictions: {e}")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in check_reply_restrictions: {e}")

    async def check_bot_admin_middleware(self, message: types.Message):
        """Middleware для проверки прав бота при старте в чате"""
        try:
            if message.chat.type == 'private':
                return

            if message.new_chat_members:
                bot_user = await message.bot.get_me()
                for new_member in message.new_chat_members:
                    if new_member.id == bot_user.id:
                        # Бот добавлен в чат, проверяем права
                        has_permissions, error_msg = await self._check_bot_permissions(message.chat, bot_user.id)

                        if has_permissions:
                            self.active_chats.add(message.chat.id)
                            await message.answer(
                                "✅ Бот успешно добавлен!\n\n"
                                "🔧 **Доступные функции:**\n"
                                "• Блокировка ответов между пользователями\n"
                                "• Автоматическое удаление запрещенных ответов\n\n"
                                "📝 **Использование:**\n"
                                "Ответьте 'бот стоп' на сообщение пользователя, "
                                "чтобы запретить ему отвечать на ваши сообщения"
                            )
                        else:
                            await message.answer(
                                f"⚠️ {error_msg}\n\n"
                                "📋 **Необходимые права:**\n"
                                "• Администратор чата\n"
                                "• Удаление сообщений\n\n"
                                "⚙️ Без этих прав функция блокировки ответов работать не будет."
                            )
        except Exception as e:
            self.logger.error(f"Error in check_bot_admin_middleware: {e}")

    async def handle_bot_removed(self, message: types.Message):
        """Обработчик удаления бота из чата"""
        if message.left_chat_member:
            bot_user = await message.bot.get_me()
            if message.left_chat_member.id == bot_user.id:
                self.active_chats.discard(message.chat.id)
                self.logger.info(f"Bot removed from chat {message.chat.id}")


def register_bot_stop_handlers(dp: Dispatcher):
    """Регистрация обработчиков для команды 'бот стоп'"""
    handler = BotStopHandler()

    # Регистрируем команду "бот стоп" с улучшенными фильтрами
    dp.register_message_handler(
        handler.bot_stop,
        lambda msg: msg.chat.type in ['group', 'supergroup'] and  # Только группы
                    msg.text and (
                            msg.text.lower().startswith("!бот стоп") or
                            msg.text.lower().startswith("/ботстоп") or
                            msg.text.lower().startswith("/bot_stop") or
                            msg.text.lower() == "бот стоп" or
                            msg.text.lower().startswith("/бот стоп")
                    ),
        state="*"
    )

    # Регистрируем проверку ограничений ответов
    dp.register_message_handler(
        handler.check_reply_restrictions,
        lambda msg: msg.chat.type in ['group', 'supergroup'] and  # Только группы
                    msg.reply_to_message is not None and  # Только ответы
                    not (msg.text and msg.text.startswith(('/', '!'))),  # Не команды
        state="*",
        content_types=types.ContentTypes.ANY,
        run_task=True
    )

    # Регистрируем middleware для проверки прав при добавлении бота
    dp.register_message_handler(
        handler.check_bot_admin_middleware,
        content_types=types.ContentTypes.ANY,
        state="*",
        run_task=True
    )

    logger.info("✅ Обработчики 'бот стоп' зарегистрированы с улучшенной конфигурацией")