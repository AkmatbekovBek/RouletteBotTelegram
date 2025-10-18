# bot_search_handler.py
import logging
import asyncio
from typing import List, Tuple, Optional, Dict
from datetime import datetime, timedelta
from aiogram import types, Dispatcher
from aiogram.utils.exceptions import MessageToDeleteNotFound, MessageCantBeDeleted
from database import get_db
from database.models import UserChatSearch, UserNickSearch
from database.crud import BotSearchRepository
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class BotSearchHandler:
    def __init__(self):
        self.logger = logger
        self.MAX_CHATS = 50
        self.MAX_NICKS = 20
        self.MAX_MESSAGE_LENGTH = 4000
        self.cooldown_dict = {}

        # Кэш для результатов поиска
        self.cache = {}
        self.CACHE_TTL = 300

        # Статистика
        self.stats = {
            'total_searches': 0,
            'data_logged': 0,
            'cache_hits': 0,
            'errors': 0
        }

        # История поисков
        self.search_history = {}

    def _check_cooldown(self, user_id: int, command: str) -> bool:
        """Проверка кулдауна для защиты от флуда"""
        current_time = asyncio.get_event_loop().time()
        key = f"{user_id}_{command}"

        if key in self.cooldown_dict:
            if current_time - self.cooldown_dict[key] < 3:
                return False
        self.cooldown_dict[key] = current_time
        return True

    async def _safe_delete_message(self, message: types.Message, delay: int = 0):
        """Безопасное удаление сообщения с задержкой"""
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await message.delete()
        except (MessageToDeleteNotFound, MessageCantBeDeleted):
            pass
        except Exception as e:
            self.logger.debug(f"Could not delete message: {e}")

    def _get_cached_result(self, user_id: int) -> Optional[str]:
        """Получает закэшированный результат"""
        if user_id in self.cache:
            result, timestamp = self.cache[user_id]
            current_time = asyncio.get_event_loop().time()
            if current_time - timestamp < self.CACHE_TTL:
                self.stats['cache_hits'] += 1
                return result
            else:
                del self.cache[user_id]
        return None

    def _set_cached_result(self, user_id: int, result: str):
        """Сохраняет результат в кэш"""
        self.cache[user_id] = (result, asyncio.get_event_loop().time())

    def _log_search_activity(self, searcher_id: int, target_id: int):
        """Логирует активность поиска"""
        if searcher_id not in self.search_history:
            self.search_history[searcher_id] = []

        now = datetime.now()
        # Очищаем старые записи (старше 1 часа)
        self.search_history[searcher_id] = [
            dt for dt in self.search_history[searcher_id]
            if now - dt < timedelta(hours=1)
        ]

        self.search_history[searcher_id].append(now)

    async def log_user_message(self, message: types.Message):
        """Логирует сообщения пользователя для сбора данных"""
        try:
            # Пропускаем служебные сообщения, команды и слишком короткие сообщения
            if not message.text or len(message.text.strip()) < 2:
                return

            # Пропускаем команды (расширенный список)
            text_lower = message.text.lower().strip()
            if (text_lower.startswith(('/', '!', 'бот ищи', 'бот очисти', 'бот статистика')) or
                    text_lower in ['ищи', 'очисти', 'статистика']):
                return

            user_id = message.from_user.id
            nick = message.from_user.full_name.strip()
            chat_id = message.chat.id
            chat_title = getattr(message.chat, "title", "Личные сообщения")

            # Валидация данных
            if not nick or len(nick) > 255:
                nick = "Неизвестно"

            if not chat_title or len(chat_title) > 255:
                chat_title = "Без названия"

            db = next(get_db())
            try:
                # Безопасное добавление чата пользователя
                chat_added = self._safe_add_user_chat(db, user_id, chat_id, chat_title)

                # Безопасное добавление ника пользователя
                nick_added = self._safe_add_user_nick(db, user_id, nick)

                if chat_added or nick_added:
                    db.commit()
                    self.stats['data_logged'] += 1
                    self.logger.debug(f"✅ Logged data for user {user_id} in chat {chat_id}")

            except Exception as e:
                db.rollback()
                if "unique constraint" not in str(e).lower() and "duplicate" not in str(e).lower():
                    self.logger.error(f"❌ Database error in log_user_message: {e}")
                    self.stats['errors'] += 1
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"❌ Error in log_user_message: {e}")
            self.stats['errors'] += 1

    def _safe_add_user_chat(self, db, user_id: int, chat_id: int, chat_title: str) -> bool:
        """Безопасное добавление чата пользователя"""
        try:
            # Проверяем количество записей для пользователя
            existing_count = db.query(UserChatSearch).filter(
                UserChatSearch.user_id == user_id
            ).count()

            # Если превышен лимит, удаляем несколько самых старых записей
            if existing_count >= self.MAX_CHATS:
                records_to_delete = existing_count - self.MAX_CHATS + 1
                oldest_records = db.query(UserChatSearch).filter(
                    UserChatSearch.user_id == user_id
                ).order_by(UserChatSearch.created_at.asc()).limit(records_to_delete).all()

                for record in oldest_records:
                    db.delete(record)

            # Проверяем существование записи
            existing = db.query(UserChatSearch).filter(
                UserChatSearch.user_id == user_id,
                UserChatSearch.chat_id == chat_id
            ).first()

            if not existing:
                record = UserChatSearch(
                    user_id=user_id,
                    chat_id=chat_id,
                    chat_title=chat_title
                )
                db.add(record)
                return True

            # Обновляем название чата если изменилось
            elif existing.chat_title != chat_title:
                existing.chat_title = chat_title
                return True

            return False

        except IntegrityError:
            db.rollback()
            return False
        except Exception as e:
            self.logger.error(f"❌ Error in _safe_add_user_chat: {e}")
            return False

    def _safe_add_user_nick(self, db, user_id: int, nick: str) -> bool:
        """Безопасное добавление ника пользователя"""
        try:
            # Проверяем количество записей для пользователя
            existing_count = db.query(UserNickSearch).filter(
                UserNickSearch.user_id == user_id
            ).count()

            # Если превышен лимит, удаляем несколько самых старых записей
            if existing_count >= self.MAX_NICKS:
                records_to_delete = existing_count - self.MAX_NICKS + 1
                oldest_records = db.query(UserNickSearch).filter(
                    UserNickSearch.user_id == user_id
                ).order_by(UserNickSearch.created_at.asc()).limit(records_to_delete).all()

                for record in oldest_records:
                    db.delete(record)

            # Проверяем существование записи
            existing = db.query(UserNickSearch).filter(
                UserNickSearch.user_id == user_id,
                UserNickSearch.nick == nick
            ).first()

            if not existing:
                record = UserNickSearch(
                    user_id=user_id,
                    nick=nick
                )
                db.add(record)
                return True
            return False

        except IntegrityError:
            db.rollback()
            return False
        except Exception as e:
            self.logger.error(f"❌ Error in _safe_add_user_nick: {e}")
            return False

    async def bot_search(self, message: types.Message):
        """Команда 'бот ищи' - показывает информацию о пользователе (работает без ответа)"""
        try:
            self.stats['total_searches'] += 1
            self.logger.info(f"🔍 Получена команда поиска от {message.from_user.id}: {message.text}")

            # Проверка кулдауна
            if not self._check_cooldown(message.from_user.id, "search"):
                await message.reply("⏳ Подождите 3 секунды перед следующим запросом.")
                return

            # Парсим команду для извлечения ID пользователя или username
            target_user = await self._parse_search_target(message)
            if not target_user:
                await self._show_search_help(message)
                return

            user_id = target_user.id

            # Проверки безопасности
            validation_error = await self._validate_search_request(message, target_user)
            if validation_error:
                await message.reply(validation_error)
                return

            # Проверяем кэш
            cached_result = self._get_cached_result(user_id)
            if cached_result:
                search_msg = await message.reply("⚡ Используем кэшированные данные...")
                await search_msg.edit_text(cached_result, parse_mode="HTML")
                self._log_search_activity(message.from_user.id, user_id)
                asyncio.create_task(self._safe_delete_message(message, 2))
                return

            db = next(get_db())
            try:
                # Показываем что идет поиск
                search_msg = await message.reply("🔍 <i>Ищем информацию в базе данных...</i>", parse_mode="HTML")

                # Получаем чаты пользователя
                chats = BotSearchRepository.get_user_chats(db, user_id, self.MAX_CHATS)

                # Получаем ники пользователя
                nicks = BotSearchRepository.get_user_nicks(db, user_id, self.MAX_NICKS)

                # Формируем результат
                result = self._format_search_result(target_user, chats, nicks, message.from_user.id)

                # Сохраняем в кэш
                self._set_cached_result(user_id, result)

                # Отправляем результат
                await search_msg.edit_text(result, parse_mode="HTML")

                # Логируем активность
                self._log_search_activity(message.from_user.id, user_id)

                # Удаляем исходное сообщение с командой через 2 секунды
                asyncio.create_task(self._safe_delete_message(message, 2))

            except Exception as e:
                self.logger.error(f"❌ Database error in bot_search: {e}")
                self.stats['errors'] += 1
                await message.reply("❌ Произошла ошибка при поиске информации.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"❌ Error in bot_search: {e}")
            self.stats['errors'] += 1
            await message.reply("❌ Произошла ошибка при обработке команды.")

    async def _parse_search_target(self, message: types.Message) -> Optional[types.User]:
        """Парсит цель поиска из сообщения"""
        text = message.text.lower().strip()

        # Если команда отправлена ответом на сообщение
        if message.reply_to_message:
            return message.reply_to_message.from_user

        # Парсим аргументы команды
        parts = text.split()
        if len(parts) < 2:
            return None

        # Пытаемся найти username или ID
        target_arg = parts[1].strip()

        # Если это username (начинается с @)
        if target_arg.startswith('@'):
            username = target_arg[1:]
            try:
                # Пытаемся получить пользователя по username
                # В реальном боте нужно использовать методы поиска пользователей
                # Здесь упрощенная версия
                return await self._get_user_by_username(message, username)
            except:
                return None

        # Если это числовой ID
        elif target_arg.isdigit():
            user_id = int(target_arg)
            try:
                # Пытаемся получить пользователя по ID
                return await self._get_user_by_id(message, user_id)
            except:
                return None

        return None

    async def _get_user_by_username(self, message: types.Message, username: str) -> Optional[types.User]:
        """Получает пользователя по username (упрощенная версия)"""
        # В реальном боте здесь должен быть вызов API Telegram
        # Пока возвращаем None, чтобы показать сообщение об ошибке
        return None

    async def _get_user_by_id(self, message: types.Message, user_id: int) -> Optional[types.User]:
        """Получает пользователя по ID (упрощенная версия)"""
        try:
            # Пытаемся получить информацию о пользователе
            # Это работает только если пользователь есть в чате с ботом
            chat_member = await message.bot.get_chat_member(user_id, user_id)
            return chat_member.user
        except:
            return None

    async def _validate_search_request(self, message: types.Message, target: types.User) -> Optional[str]:
        """Проверяет валидность запроса поиска"""
        bot_user = await message.bot.get_me()

        if target.id == bot_user.id:
            return "❌ Нельзя искать информацию о боте!"

        if target.id == message.from_user.id:
            return "❌ Для поиска информации о себе используйте профиль Telegram!"

        if target.is_bot:
            return "❌ Нельзя искать информацию о других ботах!"

        return None

    async def _show_search_help(self, message: types.Message):
        """Показывает справку по использованию команды"""
        help_text = (
            "🔍 <b>Как использовать команду 'бот ищи':</b>\n\n"
            "<b>Способ 1 (рекомендуемый):</b>\n"
            "Ответьте на сообщение пользователя командой:\n"
            "• <code>бот ищи</code>\n"
            "• <code>!бот ищи</code>\n\n"
            "<b>Способ 2 (в разработке):</b>\n"
            "Отправьте команду с ID пользователя:\n"
            "• <code>бот ищи 123456789</code>\n\n"
            "📊 <i>Бот покажет информацию о чатах и историю ников пользователя</i>"
        )
        await message.reply(help_text, parse_mode="HTML")

    def _format_search_result(self, target: types.User, chats: List[Tuple[str, int]], nicks: List[str],
                              searcher_id: int) -> str:
        """Форматирует результат поиска в читаемый вид"""
        result = [
            f"🔍 <b>Информация о пользователе:</b>",
            f"👤 <b>{self._escape_html(target.full_name)}</b> (ID: <code>{target.id}</code>)",
            ""
        ]

        # Добавляем username если есть
        if target.username:
            result.append(f"📱 @{target.username}")
            result.append("")

        # Добавляем информацию о чатах
        if chats:
            result.append(f"💬 <b>Чаты пользователя ({len(chats)}):</b>")
            for i, (chat_title, chat_id) in enumerate(chats[:12], 1):
                result.append(f"{i}. {self._escape_html(chat_title)} (ID: <code>{chat_id}</code>)")

            if len(chats) > 12:
                result.append(f"<i>... и еще {len(chats) - 12} чатов</i>")
        else:
            result.append("💬 <b>Чаты:</b> не найдено")

        result.append("")

        # Добавляем информацию о никах
        if nicks:
            result.append(f"📛 <b>История ников ({len(nicks)}):</b>")
            for i, nick in enumerate(nicks[:10], 1):
                result.append(f"{i}. {self._escape_html(nick)}")

            if len(nicks) > 10:
                result.append(f"<i>... и еще {len(nicks) - 10} ников</i>")
        else:
            result.append("📛 <b>Ники:</b> не найдено")

        # Добавляем статистику поисков
        search_stats = self._get_search_stats(searcher_id)
        result.extend([
            "",
            "📈 <b>Статистика поиска:</b>",
            f"• Поисков за час: {search_stats['last_hour']}",
            f"• Всего сегодня: {search_stats['today']}",
            "",
            "💡 <i>Данные собираются на основе сообщений в чатах где присутствует бот</i>",
            f"⚡ <i>Кэшировано запросов: {len(self.cache)}</i>"
        ])

        final_result = "\n".join(result)

        # Проверяем длину сообщения
        if len(final_result) > self.MAX_MESSAGE_LENGTH:
            return self._format_compact_result(target, chats, nicks, searcher_id)

        return final_result

    def _get_search_stats(self, user_id: int) -> Dict[str, int]:
        """Получает статистику поисков для пользователя"""
        if user_id not in self.search_history:
            return {'last_hour': 0, 'today': 0}

        now = datetime.now()
        searches = self.search_history[user_id]

        last_hour = len([dt for dt in searches if now - dt < timedelta(hours=1)])
        today = len([dt for dt in searches if dt.date() == now.date()])

        return {
            'last_hour': last_hour,
            'today': today
        }

    def _format_compact_result(self, target: types.User, chats: List[Tuple[str, int]], nicks: List[str],
                               searcher_id: int) -> str:
        """Компактный формат результата для слишком длинных сообщений"""
        result = [
            f"🔍 <b>Информация о пользователе (компактно):</b>",
            f"👤 <b>{self._escape_html(target.full_name)}</b> (ID: <code>{target.id}</code>)",
            f"💬 <b>Чатов:</b> {len(chats)}",
            f"📛 <b>Ников:</b> {len(nicks)}",
            ""
        ]

        # Показываем только самые свежие данные
        if chats:
            result.append("<b>Последние чаты:</b>")
            for i, (chat_title, chat_id) in enumerate(chats[:3], 1):
                result.append(f"{i}. {self._escape_html(chat_title)}")

        if nicks:
            result.append("<b>Последние ники:</b>")
            for i, nick in enumerate(nicks[:5], 1):
                result.append(f"{i}. {self._escape_html(nick)}")

        search_stats = self._get_search_stats(searcher_id)
        result.extend([
            "",
            f"📊 Поисков за час: {search_stats['last_hour']}",
            "ℹ️ <i>Показаны только последние записи. Полные данные слишком объемны.</i>"
        ])

        return "\n".join(result)

    def _escape_html(self, text: str) -> str:
        """Экранирование HTML-символов"""
        if not text:
            return ""
        return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    async def bot_search_clear(self, message: types.Message):
        """Команда для очистки данных о себе"""
        try:
            user_id = message.from_user.id
            self.logger.info(f"🧹 Запрос очистки данных от пользователя {user_id}")

            db = next(get_db())
            try:
                # Удаляем все данные пользователя
                chats_deleted = db.query(UserChatSearch).filter(
                    UserChatSearch.user_id == user_id
                ).delete()

                nicks_deleted = db.query(UserNickSearch).filter(
                    UserNickSearch.user_id == user_id
                ).delete()

                db.commit()

                # Очищаем кэш для этого пользователя
                if user_id in self.cache:
                    del self.cache[user_id]

                await message.reply(
                    f"✅ <b>Ваши данные очищены!</b>\n\n"
                    f"🗑️ Удалено:\n"
                    f"• Чатов: {chats_deleted}\n"
                    f"• Ников: {nicks_deleted}\n\n"
                    f"💡 <i>Новые данные будут собираться при следующих сообщениях</i>\n"
                    f"⚡ <i>Кэш также очищен</i>",
                    parse_mode="HTML"
                )

            except Exception as e:
                db.rollback()
                self.logger.error(f"❌ Database error in bot_search_clear: {e}")
                self.stats['errors'] += 1
                await message.reply("❌ Произошла ошибка при очистке данных.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"❌ Error in bot_search_clear: {e}")
            self.stats['errors'] += 1
            await message.reply("❌ Произошла ошибка при обработке команды.")

    async def bot_search_stats(self, message: types.Message):
        """Команда для просмотра статистики системы"""
        try:
            stats_text = (
                f"📊 <b>Статистика системы поиска:</b>\n\n"
                f"🔍 Всего поисков: {self.stats['total_searches']}\n"
                f"💾 Данных записано: {self.stats['data_logged']}\n"
                f"⚡ Кэш-попаданий: {self.stats['cache_hits']}\n"
                f"📈 Кэшировано: {len(self.cache)} запросов\n"
                f"❌ Ошибок: {self.stats['errors']}\n\n"
                f"👥 Активных пользователей: {len(self.cooldown_dict) // 2}\n"
                f"💬 Всего записей в кэше: {len(self.cache)}\n\n"
                f"💡 <i>Система работает в штатном режиме</i>"
            )

            await message.reply(stats_text, parse_mode="HTML")

        except Exception as e:
            self.logger.error(f"❌ Error in bot_search_stats: {e}")
            await message.reply("❌ Ошибка при получении статистики.")


def register_bot_search_handlers(dp: Dispatcher):
    """Регистрация обработчиков для команды 'бот ищи'"""
    handler = BotSearchHandler()

    # Логируем все текстовые сообщения для сбора данных
    dp.register_message_handler(
        handler.log_user_message,
        lambda msg: msg.text and
                    not msg.text.startswith('/') and
                    not msg.text.startswith('!') and
                    len(msg.text.strip()) >= 2,
        state="*",
        content_types=types.ContentTypes.TEXT,
        run_task=True
    )

    # Регистрируем команду "бот ищи" (работает без ответа)
    dp.register_message_handler(
        handler.bot_search,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!бот ищи") or
                msg.text.lower().startswith("/ботищи") or
                msg.text.lower().startswith("/bot_search") or
                msg.text.lower().startswith("бот ищи") or
                msg.text.lower().startswith("/бот ищи")
        ),
        state="*"
    )

    # Регистрируем команду очистки данных
    dp.register_message_handler(
        handler.bot_search_clear,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!бот очисти") or
                msg.text.lower().startswith("/боточисти") or
                msg.text.lower().startswith("/bot_clear") or
                msg.text.lower().startswith("бот очисти") or
                msg.text.lower().startswith("/бот очисти")
        ),
        state="*"
    )

    # Регистрируем команду статистики
    dp.register_message_handler(
        handler.bot_search_stats,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!бот статистика") or
                msg.text.lower().startswith("/ботстат") or
                msg.text.lower().startswith("/search_stats") or
                msg.text.lower().startswith("бот статистика") or
                msg.text.lower().startswith("/бот статистика")
        ),
        state="*"
    )

    logger.info("✅ Обработчики 'бот ищи' зарегистрированы")
    logger.info("🔍 Теперь команда работает без ответа на сообщение")