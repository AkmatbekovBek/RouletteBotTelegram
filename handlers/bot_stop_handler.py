# handlers/bot_stop_handler.py
import asyncio
import logging
from typing import Optional

from aiogram import types, Dispatcher
from aiogram.utils.exceptions import MessageToDeleteNotFound, MessageCantBeDeleted

from database import get_db
from database.crud import BotStopRepository, UserRepository, ShopRepository
from database.models import UserPurchase

logger = logging.getLogger(__name__)


class SimpleBotStopHandler:
    """Упрощенный обработчик команды 'бот стоп'"""

    def __init__(self):
        self._bot_user_id: Optional[int] = None
        # Команды которые должны пропускаться
        self.allowed_commands = [
            'start', 'help', 'menu', 'profile', 'settings', 'профиль',
            'рулетка', 'донат', 'подарки', 'магазин', 'ссылки', 'баланс',
            'топ', 'перевод', 'кража', 'полиция', 'вор', 'ищи', '!бот ищи', 'бот ищи', 'ботищи', 'кубик'
        ]
        # ID товаров защиты от бот стоп
        self.PROTECTION_ITEM_IDS = [5, 6]  # ID товаров из магазина

    async def get_bot_user_id(self, bot) -> int:
        """Получает ID бота"""
        if self._bot_user_id is None:
            bot_user = await bot.get_me()
            self._bot_user_id = bot_user.id
        return self._bot_user_id

    async def safe_delete(self, message: types.Message) -> bool:
        """Безопасное удаление сообщения"""
        try:
            await message.delete()
            logger.info(f"✅ Сообщение удалено: {message.message_id}")
            return True
        except (MessageToDeleteNotFound, MessageCantBeDeleted):
            return False
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return False

    async def send_temp_message(self, chat_id: int, bot, text: str, delete_after: int = 5):
        """Отправляет временное сообщение"""
        try:
            msg = await bot.send_message(chat_id, text)
            asyncio.create_task(self.delete_after_delay(msg, delete_after))
            return msg
        except Exception as e:
            logger.error(f"Error sending temp message: {e}")
            return None

    async def delete_after_delay(self, message: types.Message, delay: int):
        """Удаляет сообщение после задержки"""
        await asyncio.sleep(delay)
        await self.safe_delete(message)

    def is_command_message(self, message: types.Message) -> bool:
        """Проверяет, является ли сообщение командой для других обработчиков"""
        if not message.text:
            return False

        text = message.text.lower().strip()

        # Проверяем команды с префиксами
        if text.startswith('/'):
            command = text[1:].split('@')[0].split()[0]  # Берем первую часть команды
            if command in self.allowed_commands:
                return True

        # Проверяем текстовые команды
        for cmd in self.allowed_commands:
            if text.startswith(cmd) or cmd in text:
                return True

        return False

    def is_exact_bot_stop_command(self, text: str) -> bool:
        """Проверяет, является ли текст точной командой 'бот стоп'"""
        if not text:
            return False

        text_lower = text.lower().strip()

        # Точные варианты команды
        exact_commands = [
            'бот стоп',
            '!бот стоп',
            '/ботстоп',
            '/bot_stop',
            '/stopbot'
        ]

        return text_lower in exact_commands

    def has_bot_stop_protection(self, user_id: int, chat_id: int) -> bool:
        """Проверяет, есть ли у пользователя защита от 'бот стоп' - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        db = next(get_db())
        try:
            print(f"🔍 ДЕТАЛЬНАЯ ПРОВЕРКА ЗАЩИТЫ ОТ БОТ СТОП:")
            print(f"   👤 Пользователь: {user_id}")
            print(f"   💬 Чат: {chat_id}")

            # Способ 1: Проверка через has_active_purchase (глобальная)
            for item_id in self.PROTECTION_ITEM_IDS:
                if ShopRepository.has_active_purchase(db, user_id, item_id):
                    print(f"   ✅ Способ 1: Глобальная защита (товар {item_id})")
                    return True

            # Способ 2: Проверка через get_active_purchases
            active_purchases = ShopRepository.get_active_purchases(db, user_id)
            print(f"   🛍️ Все активные покупки: {active_purchases}")

            for item_id in self.PROTECTION_ITEM_IDS:
                if item_id in active_purchases:
                    print(f"   ✅ Способ 2: Защита через активные покупки (товар {item_id})")
                    return True

            # Способ 3: Прямая проверка в базе данных
            from datetime import datetime
            current_time = datetime.now()
            protection_purchases = db.query(UserPurchase).filter(
                UserPurchase.user_id == user_id,
                UserPurchase.item_id.in_(self.PROTECTION_ITEM_IDS),
            ).all()

            print(f"   📊 Найдено покупок защиты в чате: {len(protection_purchases)}")

            for purchase in protection_purchases:
                print(f"   🛒 Покупка: item_id={purchase.item_id}, expires_at={purchase.expires_at}")
                if purchase.expires_at is None or purchase.expires_at > current_time:
                    print(f"   ✅ Способ 3: Активная защита в чате (товар {purchase.item_id})")
                    return True

            print(f"   ❌ Все способы проверки: ЗАЩИТЫ НЕТ")
            return False

        except Exception as e:
            print(f"❌ Ошибка детальной проверки защиты: {e}")
            return False
        finally:
            db.close()

    async def _get_protection_info(self, user_id: int, chat_id: int) -> str:
        """Получает информацию о защите пользователя"""
        db = next(get_db())
        try:
            from datetime import datetime
            current_time = datetime.now()

            # Ищем активные покупки защиты
            active_protections = db.query(UserPurchase).filter(
                UserPurchase.user_id == user_id,
                UserPurchase.item_id.in_(self.PROTECTION_ITEM_IDS),
                UserPurchase.chat_id == chat_id
            ).all()

            protection_items = []
            for purchase in active_protections:
                if purchase.expires_at is None or purchase.expires_at > current_time:
                    if purchase.item_id == 5:
                        protection_items.append("'Защита от !бот стоп'")
                    elif purchase.item_id == 6:
                        protection_items.append("'Защита от !!мут и !бот стоп'")

            if protection_items:
                return f"приобрел {', '.join(protection_items)}"
            else:
                return "имеет защиту от бот стоп"

        except Exception as e:
            logger.error(f"Error getting protection info: {e}")
            return "имеет защиту от бот стоп"
        finally:
            db.close()

    async def handle_bot_stop_command(self, message: types.Message):
        """Обработчик команды бот стоп"""
        try:
            # Проверяем что это ответ на сообщение
            if not message.reply_to_message:
                await self.send_temp_message(
                    message.chat.id,
                    message.bot,
                    "❗ Команду нужно отправить в ответ на сообщение пользователя.",
                    5
                )
                return

            # Проверяем права бота
            bot_id = await self.get_bot_user_id(message.bot)
            try:
                bot_member = await message.chat.get_member(bot_id)
                if not bot_member.is_chat_admin() or not bot_member.can_delete_messages:
                    await self.send_temp_message(
                        message.chat.id,
                        message.bot,
                        "❌ Бот должен быть администратором с правом удаления сообщений.",
                        5
                    )
                    return
            except Exception as e:
                logger.error(f"Error checking bot permissions: {e}")
                return

            user1 = message.from_user
            user2 = message.reply_to_message.from_user

            # Проверки
            if user1.id == user2.id:
                await self.send_temp_message(
                    message.chat.id, message.bot, "❌ Нельзя заблокировать самого себя!", 5
                )
                return

            if user2.id == bot_id:
                await self.send_temp_message(
                    message.chat.id, message.bot, "❌ Нельзя заблокировать бота!", 5
                )
                return

            # ПРОВЕРКА ЗАЩИТЫ: если у пользователя user2 есть защита от бот стоп
            if self.has_bot_stop_protection(user2.id, message.chat.id):
                protection_info = await self._get_protection_info(user2.id, message.chat.id)

                protection_msg = await message.reply(
                    f"🛡️ <b>Пользователь защищен от команды 'бот стоп'!</b>\n\n"
                    f"👤 <b>{user2.full_name}</b> {protection_info}\n\n"
                    f"💡 <i>Вы не можете заблокировать этого пользователя</i>",
                    parse_mode="HTML"
                )

                await self.safe_delete(message)
                # Удаляем сообщение о защите через 8 секунд
                asyncio.create_task(self.delete_after_delay(protection_msg, 8))
                return

            # Убеждаемся, что пользователи существуют в БД
            db = next(get_db())
            try:
                # Создаем пользователей если их нет
                if not UserRepository.get_user_by_telegram_id(db, user1.id):
                    UserRepository.create_user_safe(db, user1.id, user1.first_name, user1.username, user1.last_name)
                if not UserRepository.get_user_by_telegram_id(db, user2.id):
                    UserRepository.create_user_safe(db, user2.id, user2.first_name, user2.username, user2.last_name)
                db.commit()
            except Exception as e:
                logger.error(f"Error ensuring users exist: {e}")
                db.rollback()
            finally:
                db.close()

            # Работа с БД для блокировки
            db = next(get_db())
            try:
                existing = BotStopRepository.get_block_record(db, user1.id, user2.id)

                if existing:
                    # Разблокировка
                    BotStopRepository.delete_block_record(db, user1.id, user2.id)
                    db.commit()
                    logger.info(f"🔓 UNBLOCKED: {user1.id} -> {user2.id}")
                    response_text = f"✅ {user1.full_name} разрешил {user2.full_name} отвечать на свои сообщения."
                else:
                    # Блокировка
                    BotStopRepository.create_block_record(db, user1.id, user2.id)
                    db.commit()
                    logger.info(f"🔒 BLOCKED: {user1.id} -> {user2.id}")
                    response_text = f"🚫 {user1.full_name} запретил {user2.full_name} отвечать на свои сообщения."

                response_msg = await message.reply(response_text)
                await self.safe_delete(message)
                # Удаляем сообщение о результате через 8 секунд
                asyncio.create_task(self.delete_after_delay(response_msg, 8))

            except Exception as e:
                db.rollback()
                logger.error(f"Database error: {e}")
                await self.send_temp_message(
                    message.chat.id, message.bot, "❌ Ошибка базы данных", 5
                )
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in bot_stop: {e}")

    async def check_reply_restrictions(self, message: types.Message):
        """Проверяет только ответы на блокировку - НЕ ПЕРЕХВАТЫВАЕТ ДРУГИЕ КОМАНДЫ"""
        try:
            # ТОЛЬКО ответы на сообщения
            if not message.reply_to_message:
                return

            # ТОЛЬКО группы
            if message.chat.type not in ['group', 'supergroup']:
                return

            # ТОЛЬКО не боты
            if not message.from_user or message.from_user.is_bot:
                return

            # ТОЛЬКО ответы на пользователей
            if not message.reply_to_message.from_user:
                return

            # Пропускаем команды для других обработчиков
            if self.is_command_message(message):
                logger.info(f"⏩ Пропускаем команду: {getattr(message, 'text', '')}")
                return

            replied_user_id = message.reply_to_message.from_user.id
            current_user_id = message.from_user.id

            # Пропускаем ответы самому себе
            if replied_user_id == current_user_id:
                return

            # ПРОВЕРКА ЗАЩИТЫ: если у пользователя есть защита от бот стоп, пропускаем проверку блокировки
            if self.has_bot_stop_protection(current_user_id, message.chat.id):
                logger.info(f"🛡️ PROTECTED REPLY: {current_user_id} -> {replied_user_id}, user has protection")
                return

            # Проверяем блокировку в БД
            db = next(get_db())
            try:
                # ИСПРАВЛЕННАЯ ЛОГИКА:
                # Когда user1 блокирует user2, создается запись (user1, user2)
                # Это означает: "user1 заблокировал user2"
                # Когда user2 отвечает на user1, проверяем: "user1 заблокировал user2?" = ДА → удаляем
                is_blocked = BotStopRepository.get_block_record(db, replied_user_id, current_user_id) is not None

                if is_blocked:
                    logger.info(
                        f"🚫 BLOCKED REPLY: {current_user_id} -> {replied_user_id}, text: '{getattr(message, 'text', '')}'")
                    # Просто удаляем без уведомлений
                    await self.safe_delete(message)
                else:
                    logger.info(
                        f"✅ ALLOWED REPLY: {current_user_id} -> {replied_user_id}, text: '{getattr(message, 'text', '')}'")

            except Exception as e:
                logger.error(f"Database error in reply check: {e}")
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in reply check: {e}")

    async def debug_protection_command(self, message: types.Message):
        """Команда для отладки защиты от бот стоп"""
        user_id = message.from_user.id
        chat_id = message.chat.id

        # Проверяем защиту
        has_protection = self.has_bot_stop_protection(user_id, chat_id)

        # Получаем детальную информацию
        db = next(get_db())
        try:
            # Все покупки пользователя
            all_purchases = db.query(UserPurchase).filter(
                UserPurchase.user_id == user_id
            ).all()

            # Покупки защиты от бот стоп
            protection_purchases = db.query(UserPurchase).filter(
                UserPurchase.user_id == user_id,
                UserPurchase.item_id.in_(self.PROTECTION_ITEM_IDS)
            ).all()

            # Активные покупки через ShopRepository
            active_purchases = ShopRepository.get_active_purchases(db, user_id)

            debug_info = (
                f"🔍 <b>Отладка защиты от бот стоп:</b>\n\n"
                f"👤 User ID: {user_id}\n"
                f"💬 Chat ID: {chat_id}\n"
                f"🛡️ Защита активна: {'✅ ДА' if has_protection else '❌ НЕТ'}\n"
                f"🛒 ID защиты: {self.PROTECTION_ITEM_IDS}\n\n"
                f"📊 <b>Статистика покупок:</b>\n"
                f"• Всего покупок: {len(all_purchases)}\n"
                f"• Покупок защиты: {len(protection_purchases)}\n"
                f"• Активных покупок: {len(active_purchases)}\n"
                f"• Активные ID: {active_purchases}\n\n"
                f"🛒 <b>Покупки защиты от бот стоп:</b>\n"
            )

            if protection_purchases:
                for purchase in protection_purchases:
                    from datetime import datetime
                    status = "✅ АКТИВНА" if (
                                purchase.expires_at is None or purchase.expires_at > datetime.now()) else "❌ ИСТЕКЛА"
                    debug_info += f"• ID {purchase.item_id} в чате {purchase.chat_id} - {status}\n"
                    debug_info += f"  Срок: {purchase.expires_at}\n"
            else:
                debug_info += "• Нет покупок защиты\n"

            await message.reply(debug_info, parse_mode="HTML")

        except Exception as e:
            await message.reply(f"❌ Ошибка отладки: {e}")
        finally:
            db.close()

    async def debug_active_blocks(self, message: types.Message):
        """Команда для отладки - показывает активные блокировки"""
        try:
            db = next(get_db())
            try:
                from database import models
                # Получаем все активные блокировки
                all_blocks = db.query(models.BotStop).all()

                if not all_blocks:
                    await message.answer("❌ Нет активных блокировок")
                    return

                response = "🔍 АКТИВНЫЕ БЛОКИРОВКИ:\n\n"
                for block in all_blocks:
                    response += f"👤 {block.user_id} 🚫→ 👤 {block.blocked_user_id}\n"
                    response += f"   📅 {block.created_at}\n\n"

                await message.answer(response)

            except Exception as e:
                logger.error(f"Debug error: {e}")
                await message.answer(f"❌ Ошибка: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in debug command: {e}")


def register_bot_stop_handlers(dp: Dispatcher):
    """Регистрация обработчиков - ТОЛЬКО для ответов"""
    handler = SimpleBotStopHandler()

    # Команды бот стоп - ВЫСОКИЙ ПРИОРИТЕТ
    dp.register_message_handler(
        handler.handle_bot_stop_command,
        commands=['ботстоп', 'bot_stop', 'stopbot'],
        chat_type=['group', 'supergroup'],
        state="*"
    )

    # Текстовые команды бот стоп - ТОЛЬКО ТОЧНЫЕ СОВПАДЕНИЯ
    dp.register_message_handler(
        handler.handle_bot_stop_command,
        lambda msg: msg.text and handler.is_exact_bot_stop_command(msg.text),
        chat_type=['group', 'supergroup'],
        state="*"
    )

    # Проверка ОТВЕТОВ - НИЗКИЙ ПРИОРИТЕТ (регистрируется последним)
    dp.register_message_handler(
        handler.check_reply_restrictions,
        chat_type=['group', 'supergroup'],
        content_types=types.ContentTypes.ANY,
        state="*"
    )

    # Команды для отладки
    dp.register_message_handler(
        handler.debug_protection_command,
        commands=['debug_botstop'],
        chat_type=['private']
    )

    dp.register_message_handler(
        handler.debug_active_blocks,
        commands=['debug_blocks'],
        chat_type=['private']
    )

    logger.info("✅ Обработчики 'бот стоп' зарегистрированы (с исправленной логикой и защитой)")