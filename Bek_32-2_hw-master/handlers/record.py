# handlers/record.py
from aiogram import types, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_db
from database.crud import UserRepository, DailyRecordRepository, ChatRepository
from typing import Tuple, Optional
import re
from datetime import datetime, date
from sqlalchemy import func


class RecordHandler:
    def __init__(self):
        # Список ID администраторов бота
        self.BOT_ADMIN_IDS = [1054684037]  # Замените на реальные ID админов бота

    async def _check_admin_rights(self, message_or_callback) -> bool:
        """Проверяет, является ли пользователь администратором группы или бота"""
        try:
            if isinstance(message_or_callback, types.Message):
                user_id = message_or_callback.from_user.id
                chat_id = message_or_callback.chat.id
            else:  # types.CallbackQuery
                user_id = message_or_callback.from_user.id
                chat_id = message_or_callback.message.chat.id

            # Проверяем админов бота
            if user_id in self.BOT_ADMIN_IDS:
                return True

            # Проверяем админов из БД
            db = next(get_db())
            try:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if user and user.is_admin:
                    return True
            finally:
                db.close()

            # Проверяем администраторов группы
            if chat_id < 0:  # Это группа/супергруппа
                try:
                    chat_member = await message_or_callback.bot.get_chat_member(chat_id, user_id)
                    return chat_member.status in ['administrator', 'creator']
                except Exception:
                    return False

            return False

        except Exception as e:
            print(f"❌ Ошибка в _check_admin_rights: {e}")
            return False

    async def _send_not_admin_message(self, message_or_callback):
        """Отправляет сообщение об отсутствии прав"""
        text = "❌ Эта команда доступна только администраторам группы или бота"
        if isinstance(message_or_callback, types.Message):
            await message_or_callback.answer(text)
        else:  # types.CallbackQuery
            await message_or_callback.answer(text, show_alert=True)

    async def ensure_user_registered(self, db, user_id: int, chat_id: int, username: str = None,
                                     first_name: str = None):
        """Автоматически регистрирует пользователя в чате"""
        ChatRepository.add_user_to_chat(db, user_id, chat_id, username, first_name)

    async def show_top_menu(self, message: types.Message, limit: int = 10):
        """Показывает меню выбора топа как на фото с указанным лимитом"""
        # Проверяем права администратора
        if not await self._check_admin_rights(message):
            await self._send_not_admin_message(message)
            return

        keyboard = InlineKeyboardMarkup(row_width=1)  # Одна кнопка в строке

        buttons = [
            InlineKeyboardButton("💰 Топ богатеев", callback_data=f"top_rich_{limit}"),
            InlineKeyboardButton("🎯 Выиграно", callback_data=f"top_wins_{limit}"),
            InlineKeyboardButton("💸 Проиграно", callback_data=f"top_losses_{limit}"),
            InlineKeyboardButton("🏆 Макс. выигрыш", callback_data=f"top_maxwin_{limit}"),
            InlineKeyboardButton("📉 Макс. проигрыш", callback_data=f"top_maxloss_{limit}"),
            InlineKeyboardButton("🎲 Макс. ставка", callback_data=f"top_maxbet_{limit}"),
            InlineKeyboardButton("🔙 Назад", callback_data="top_back"),
        ]

        for button in buttons:
            keyboard.add(button)

        await message.reply(
            f"Какой топ {limit} Вас интересует?",
            reply_markup=keyboard
        )

    async def handle_top_callback(self, callback_query: types.CallbackQuery):
        """Обработчик callback'ов для топов - убирает кнопки после выбора"""
        # Проверяем права администратора
        if not await self._check_admin_rights(callback_query):
            await self._send_not_admin_message(callback_query)
            return

        db = next(get_db())
        try:
            chat_id = callback_query.message.chat.id
            user_id = callback_query.from_user.id
            username = callback_query.from_user.username
            first_name = callback_query.from_user.first_name

            # Автоматическая регистрация пользователя
            await self.ensure_user_registered(db, user_id, chat_id, username, first_name)

            callback_data = callback_query.data

            if callback_data == "top_back":
                # Просто удаляем сообщение с кнопками
                await callback_query.message.delete()
                await callback_query.answer()
                return

            # Парсим callback_data: формат "top_type_limit"
            if callback_data.startswith('top_'):
                parts = callback_data.split('_')

                if len(parts) >= 3 and parts[2].isdigit():
                    top_type = parts[1]  # wins, losses, maxwin, maxloss, maxbet
                    limit = int(parts[2])

                    # Маппинг обратно на исходные типы для базы данных
                    type_mapping = {
                        "maxwin": "max_win",
                        "maxloss": "max_loss",
                        "maxbet": "max_bet"
                    }

                    db_top_type = type_mapping.get(top_type, top_type)

                    if db_top_type == "rich":
                        await self._show_rich_top_internal(callback_query, db, chat_id, user_id, limit)
                    elif db_top_type in ["wins", "losses", "max_win", "max_loss", "max_bet"]:
                        await self._show_stats_top_internal(callback_query, db, chat_id, user_id, db_top_type, limit)
                    else:
                        await callback_query.answer("❌ Неизвестный тип топа", show_alert=True)
                    return
                else:
                    await callback_query.answer("❌ Ошибка: не указан лимит", show_alert=True)
                    return

            await callback_query.answer("❌ Ошибка обработки запроса", show_alert=True)

        except Exception as e:
            print(f"❌ Ошибка в handle_top_callback: {e}")
            await callback_query.answer("❌ Ошибка при получении топа", show_alert=True)
        finally:
            db.close()

    async def _show_rich_top_internal(self, callback_query: types.CallbackQuery, db, chat_id: int, user_id: int,
                                      limit: int):
        """Внутренний метод для показа топа богатеев - БЕЗ КНОПОК"""
        try:
            top_users = ChatRepository.get_top_rich_in_chat(db, chat_id, limit)

            if not top_users:
                await callback_query.message.edit_text(
                    f"🏆 Пока нет богатеев в этом чате.",
                    reply_markup=None  # Убираем кнопки
                )
                await callback_query.answer()
                return

            user_position = ChatRepository.get_user_rank_in_chat(db, chat_id, user_id)
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            user_coins = user.coins if user else 0

            reply_text = f"[Топ {limit} богатеев]\n\n"
            for i, (telegram_id, username, first_name, coins) in enumerate(top_users, start=1):
                display_name = first_name if first_name else username or "Аноним"
                reply_text += f"{i}. {display_name} — {coins:,} монет\n"

            reply_text += "¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯¯\n"

            current_user_name = callback_query.from_user.first_name or callback_query.from_user.username or "Аноним"
            reply_text += f"{user_position or '?'}. {current_user_name} — {user_coins:,} монет"

            # Редактируем сообщение БЕЗ КНОПОК (reply_markup=None)
            await callback_query.message.edit_text(
                reply_text,
                parse_mode=types.ParseMode.HTML,
                reply_markup=None  # Убираем кнопки полностью
            )
            await callback_query.answer()

        except Exception as e:
            print(f"❌ Ошибка в _show_rich_top_internal: {e}")
            await callback_query.answer("❌ Ошибка при получении топа богатеев", show_alert=True)

    async def _show_stats_top_internal(self, callback_query: types.CallbackQuery, db, chat_id: int, user_id: int,
                                       top_type: str, limit: int):
        """Внутренний метод для показа статистических топов - БЕЗ КНОПОК"""
        try:
            # Определяем заголовок и данные в зависимости от типа топа
            headers = {
                "wins": f"[Топ {limit} по выигранным ставкам]\n\n",
                "losses": f"[Топ {limit} по проигранным ставкам]\n\n",
                "max_win": f"[Топ {limit} по максимальному выигрышу]\n\n",
                "max_loss": f"[Топ {limit} по максимальному проигрышу]\n\n",
                "max_bet": f"[Топ {limit} по максимальной ставке]\n\n",
            }

            top_methods = {
                "wins": ChatRepository.get_top_wins,
                "losses": ChatRepository.get_top_losses,
                "max_win": ChatRepository.get_top_max_win,
                "max_loss": ChatRepository.get_top_max_loss,
                "max_bet": ChatRepository.get_top_max_bet,
            }

            header = headers.get(top_type, f"[Топ {limit}]\n\n")
            top_method = top_methods.get(top_type)

            if not top_method:
                await callback_query.answer("❌ Неизвестный тип топа", show_alert=True)
                return

            top_data = top_method(db, chat_id, limit)

            if not top_data:
                await callback_query.message.edit_text(
                    f"🏆 Пока нет данных для этого топа в этом чате.",
                    reply_markup=None  # Убираем кнопки
                )
                await callback_query.answer()
                return

            # Получаем позицию пользователя
            user_position = ChatRepository.get_user_stats_rank(db, chat_id, user_id, top_type)

            reply_text = header
            for i, (telegram_id, display_name, value) in enumerate(top_data, start=1):
                reply_text += f"{i}. {display_name} — {value:,}\n"

            # Добавляем позицию пользователя
            user_stats = ChatRepository.get_user_stats(db, user_id, top_type)
            if user_stats is not None:
                current_user_name = callback_query.from_user.first_name or callback_query.from_user.username or "Аноним"
                reply_text += f"\n{user_position or '?'}. {current_user_name} — {user_stats:,}"

            # Редактируем сообщение БЕЗ КНОПОК (reply_markup=None)
            await callback_query.message.edit_text(
                reply_text,
                parse_mode=types.ParseMode.HTML,
                reply_markup=None  # Убираем кнопки полностью
            )
            await callback_query.answer()

        except Exception as e:
            print(f"❌ Ошибка в _show_stats_top_internal: {e}")
            await callback_query.answer("❌ Ошибка при получении топа статистики", show_alert=True)

    async def check_daily_record(self, message: types.Message):
        """Обработчик команды 'рекорд дня' - показывает глобальный топ 3: 2 выигрыша + 1 проигрыш"""
        # Эта команда доступна всем пользователям
        db = next(get_db())
        try:
            user_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name

            # Автоматическая регистрация пользователя (chat_id=0 для глобального)
            await self.ensure_user_registered(db, user_id, 0, username, first_name)

            # Получаем глобальный топ 2 рекорда выигрышей за сегодня
            top_wins = self._get_global_top_wins_today(db, 2)

            # Получаем глобальный топ 1 рекорд проигрышей за сегодня
            top_losses = self._get_global_top_losses_today(db, 1)

            reply_text = "💰 Глобальный рекорд дня (топ 3):\n\n"

            # Показываем первые два места - рекорд выигрышей
            medals = ["🥇", "🥈"]
            for i, (record_user_id, display_name, amount) in enumerate(top_wins):
                if i < len(medals):
                    medal = medals[i]
                    reply_text += f"{medal} {display_name} — {amount:,} монет (рекорд выигрыша)\n"

            # Показываем третье место - рекорд проигрышей
            if top_losses:
                loss_user_id, loss_display_name, loss_amount = top_losses[0]
                reply_text += f"🥉 {loss_display_name} — {loss_amount:,} монет (рекорд проигрыша)\n"
            else:
                reply_text += "🥉 Пока нет рекорда проигрышей\n"

            # Добавляем информацию о позиции текущего пользователя
            user_win_record = self._get_user_daily_record_global(db, user_id)
            user_loss_record = self._get_user_loss_record(db, user_id)

            current_user_name = first_name or username or "Аноним"

            if user_win_record:
                user_amount = user_win_record.amount
                win_position = self._get_user_global_rank_today(db, user_id)
                reply_text += f"\n🎯 Ваш рекорд выигрыша: {win_position or '?'}. {current_user_name} — {user_amount:,} монет"

            if user_loss_record:
                loss_amount = user_loss_record.defeat_coins
                loss_position = self._get_user_loss_rank_today(db, user_id)
                reply_text += f"\n💸 Ваш рекорд проигрыша: {loss_position or '?'}. {current_user_name} — {loss_amount:,} монет"

            await message.reply(reply_text, parse_mode=types.ParseMode.HTML)

        except Exception as e:
            print(f"❌ Ошибка в check_daily_record: {e}")
            await message.reply("❌ Ошибка при получении рекордов.")
        finally:
            db.close()

    def _get_global_top_wins_today(self, db, limit: int):
        """Получает глобальный топ рекордов выигрышей за сегодня"""
        from database.models import DailyRecord, TelegramUser

        today = date.today()

        try:
            top_records = (db.query(
                DailyRecord.user_id,
                func.coalesce(TelegramUser.first_name, TelegramUser.username, 'Аноним').label('display_name'),
                DailyRecord.amount
            )
                           .join(TelegramUser, TelegramUser.telegram_id == DailyRecord.user_id)
                           .filter(DailyRecord.record_date == today)
                           .order_by(DailyRecord.amount.desc())
                           .limit(limit)
                           .all())

            return [(record.user_id, record.display_name, record.amount) for record in top_records]
        except Exception as e:
            print(f"❌ Ошибка в _get_global_top_wins_today: {e}")
            return []

    def _get_global_top_losses_today(self, db, limit: int):
        """Получает глобальный топ рекордов проигрышей за сегодня"""
        from database.models import TelegramUser

        today = date.today()

        try:
            # Ищем пользователей с самыми большими проигрышами
            top_losses = (db.query(
                TelegramUser.telegram_id,
                func.coalesce(TelegramUser.first_name, TelegramUser.username, 'Аноним').label('display_name'),
                TelegramUser.defeat_coins
            )
                          .filter(TelegramUser.defeat_coins > 0)
                          .order_by(TelegramUser.defeat_coins.desc())
                          .limit(limit)
                          .all())

            return [(record.telegram_id, record.display_name, record.defeat_coins) for record in top_losses]
        except Exception as e:
            print(f"❌ Ошибка в _get_global_top_losses_today: {e}")
            return []

    def _get_user_global_rank_today(self, db, user_id: int):
        """Получает глобальную позицию пользователя в рекордах выигрышей"""
        from database.models import DailyRecord

        today = date.today()

        try:
            # Получаем МАКСИМАЛЬНЫЙ рекорд пользователя за сегодня (если несколько записей)
            user_record = (db.query(func.max(DailyRecord.amount))
                           .filter(
                DailyRecord.user_id == user_id,
                DailyRecord.record_date == today
            )
                           .scalar())  # Используем scalar() для получения одного значения

            if not user_record:
                return None

            # Считаем количество пользователей с рекордом ВЫШЕ (учитывая только максимальные рекорды за день)
            # Подзапрос для получения максимальных рекордов каждого пользователя за сегодня
            subquery = (db.query(
                DailyRecord.user_id,
                func.max(DailyRecord.amount).label('max_amount')
            )
                        .filter(DailyRecord.record_date == today)
                        .group_by(DailyRecord.user_id)
                        .subquery())

            # Считаем ранг среди уникальных пользователей
            rank = (db.query(func.count(subquery.c.user_id))
                    .filter(subquery.c.max_amount > user_record)
                    .scalar())

            return rank + 1 if rank is not None else 1

        except Exception as e:
            print(f"❌ Ошибка в _get_user_global_rank_today: {e}")
            return None

    def _get_user_loss_rank_today(self, db, user_id: int):
        """Получает глобальную позицию пользователя в рекордах проигрышей"""
        from database.models import TelegramUser

        try:
            # Получаем проигрыш пользователя
            user_loss = (db.query(TelegramUser.defeat_coins)
                         .filter(TelegramUser.telegram_id == user_id)
                         .scalar())

            if not user_loss or user_loss <= 0:
                return None

            # Считаем количество пользователей с проигрышем выше
            rank = (db.query(func.count(TelegramUser.telegram_id))
                    .filter(TelegramUser.defeat_coins > user_loss)
                    .scalar())

            return rank + 1 if rank is not None else 1
        except Exception as e:
            print(f"❌ Ошибка в _get_user_loss_rank_today: {e}")
            return None

    def _get_user_daily_record_global(self, db, user_id: int):
        """Получает глобальный рекорд пользователя за сегодня (максимальный, если несколько)"""
        from database.models import DailyRecord

        today = date.today()

        try:
            # Получаем запись с МАКСИМАЛЬНЫМ рекордом пользователя за сегодня
            user_record = (db.query(DailyRecord)
                           .filter(
                DailyRecord.user_id == user_id,
                DailyRecord.record_date == today
            )
                           .order_by(DailyRecord.amount.desc())
                           .first())  # Берем первую (самую большую) запись

            return user_record
        except Exception as e:
            print(f"❌ Ошибка в _get_user_daily_record_global: {e}")
            return None

    def _get_user_loss_record(self, db, user_id: int):
        """Получает рекорд проигрыша пользователя"""
        from database.models import TelegramUser

        try:
            user_record = (db.query(TelegramUser)
                           .filter(TelegramUser.telegram_id == user_id)
                           .first())

            return user_record if user_record and user_record.defeat_coins > 0 else None
        except Exception as e:
            print(f"❌ Ошибка в _get_user_loss_record: {e}")
            return None

    async def show_rich_top(self, message: types.Message):
        """Обработчик команды 'топ богатеев' с поддержкой динамического лимита"""
        # Проверяем права администратора
        if not await self._check_admin_rights(message):
            await self._send_not_admin_message(message)
            return

        try:
            command_text = message.text.lower().strip()

            # Извлекаем лимит из команды
            limit_match = re.search(r'топ\s*(\d+)', command_text)
            if limit_match:
                limit = int(limit_match.group(1))
                # Показываем меню выбора топа с указанным лимит
                await self.show_top_menu(message, limit)
                return
            elif command_text == "топ 100":
                await self.show_top_menu(message, 100)
                return
            else:
                # Если просто "топ" - показываем меню выбора с лимитом 10 по умолчанию
                await self.show_top_menu(message, 10)
                return

        except Exception as e:
            print(f"❌ Ошибка в show_rich_top: {e}")
            await message.reply("❌ Ошибка при получении топа богатеев.")

    async def show_stats_top(self, message: types.Message):
        """Обработчик различных топов статистики"""
        # Проверяем права администратора
        if not await self._check_admin_rights(message):
            await self._send_not_admin_message(message)
            return

        db = next(get_db())
        try:
            chat_id = message.chat.id
            user_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name
            command_text = message.text.lower().strip()

            # Автоматическая регистрация пользователя
            await self.ensure_user_registered(db, user_id, chat_id, username, first_name)

            # Определяем тип топа и лимит
            limit_match = re.search(r'топ\s*(\d+)', command_text)
            limit = int(limit_match.group(1)) if limit_match else 10

            top_type = None
            header = ""

            if "выиграно" in command_text or "выигрыш" in command_text:
                top_type = "wins"
                header = f"[Топ {limit} по выигранным ставкам]\n\n"
                top_data = ChatRepository.get_top_wins(db, chat_id, limit)
            elif "проиграно" in command_text or "проигрыш" in command_text:
                top_type = "losses"
                header = f"[Топ {limit} по проигранным ставкам]\n\n"
                top_data = ChatRepository.get_top_losses(db, chat_id, limit)
            elif "макс выигрыш" in command_text:
                top_type = "max_win"
                header = f"[Топ {limit} по максимальному выигрышу]\n\n"
                top_data = ChatRepository.get_top_max_win(db, chat_id, limit)
            elif "макс проигрыш" in command_text:
                top_type = "max_loss"
                header = f"[Топ {limit} по максимальному проигрышу]\n\n"
                top_data = ChatRepository.get_top_max_loss(db, chat_id, limit)
            elif "макс ставка" in command_text or "ставка" in command_text:
                top_type = "max_bet"
                header = f"[Топ {limit} по максимальной ставке]\n\n"
                top_data = ChatRepository.get_top_max_bet(db, chat_id, limit)
            else:
                await message.reply(
                    "❌ Неизвестный тип топа. Доступные: выиграно, проиграно, макс выигрыш, макс проигрыш, макс ставка")
                return

            if not top_data:
                await message.reply(f"🏆 Пока нет данных для этого топа в этом чате.")
                return

            # Получаем позицию пользователя
            user_position = ChatRepository.get_user_stats_rank(db, chat_id, user_id, top_type)

            reply_text = header
            for i, (telegram_id, display_name, value) in enumerate(top_data, start=1):
                reply_text += f"{i}. {display_name} — {value:,}\n"

            # Добавляем позицию пользователя
            user_stats = ChatRepository.get_user_stats(db, user_id, top_type)
            if user_stats is not None:
                current_user_name = first_name or username or "Аноним"
                reply_text += f"\n{user_position or '?'}. {current_user_name} — {user_stats:,}"

            await message.reply(reply_text, parse_mode=types.ParseMode.HTML)

        except Exception as e:
            print(f"❌ Ошибка в show_stats_top: {e}")
            await message.reply("❌ Ошибка при получении топа статистики.")
        finally:
            db.close()

    async def add_score(self, user_id: int, amount: int, chat_id: int = None, username: str = None,
                        first_name: str = None):
        """Добавление рекорда с валидацией chat_id"""
        db = next(get_db())
        try:
            if chat_id is None:
                chat_id = 0
            elif isinstance(chat_id, str):
                try:
                    chat_id = int(chat_id)
                except (ValueError, TypeError):
                    print(f"⚠️ Некорректный chat_id: {chat_id}, использую 0")
                    chat_id = 0

            # Автоматически регистрируем пользователя
            await self.ensure_user_registered(db, user_id, chat_id, username, first_name)

            # ВАЖНО: Обновляем баланс пользователя
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if user:
                # Обновляем баланс
                user.coins += amount
                db.commit()
                print(f"✅ Баланс пользователя {user_id} обновлен на {amount}, текущий баланс: {user.coins}")

            # Добавляем или обновляем рекорд
            record = DailyRecordRepository.add_or_update_daily_record(
                db=db,
                user_id=user_id,
                username=username or "",
                first_name=first_name or "",
                amount=amount,
                chat_id=chat_id
            )

            if record:
                print(f"✅ Рекорд дня для пользователя {user_id} установлен: {amount} монет")
            else:
                print(f"❌ Не удалось установить рекорд для пользователя {user_id}")

            return record
        except Exception as e:
            print(f"❌ Ошибка в add_score: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    async def add_score_legacy(self, *args):
        """Совместимость со старыми вызовами"""
        if len(args) == 2:
            return await self.add_score(user_id=args[0], amount=args[1])
        elif len(args) >= 3:
            return await self.add_score(
                user_id=args[0],
                amount=args[1],
                chat_id=args[2] if len(args) > 2 else None,
                username=args[3] if len(args) > 3 else None,
                first_name=args[4] if len(args) > 4 else None
            )

    async def add_loss_record(self, user_id: int, loss_amount: int, username: str = None, first_name: str = None):
        """Добавление записи о проигрыше"""
        db = next(get_db())
        try:
            # Автоматически регистрируем пользователя
            await self.ensure_user_registered(db, user_id, 0, username, first_name)

            # Обновляем счетчик проигрышей пользователя
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if user:
                user.defeat_coins = max(user.defeat_coins or 0, loss_amount)
                db.commit()
                print(f"✅ Рекорд проигрыша для пользователя {user_id} установлен: {loss_amount} монет")
                return user
            return None
        except Exception as e:
            print(f"❌ Ошибка в add_loss_record: {e}")
            db.rollback()
            return None
        finally:
            db.close()


def register_record_handlers(dp: Dispatcher):
    """Регистрация всех обработчиков записей"""
    handler = RecordHandler()

    # Обработчики рекорда дня (доступны всем)
    dp.register_message_handler(
        handler.check_daily_record,
        commands=['record', 'рекорд_дня', 'рекорддня'],
        commands_prefix='!/'
    )

    dp.register_message_handler(
        handler.check_daily_record,
        lambda m: m.text and re.match(r'^(рекорд(\s*дня)?|record)$', m.text.lower().strip())
    )

    # Обработчики топа (только для админов)
    dp.register_message_handler(
        handler.show_rich_top,
        commands=['top'],
        commands_prefix='!/'
    )

    dp.register_message_handler(
        handler.show_rich_top,
        lambda m: m.text and re.match(r'^топ(\s*\d+)?$', m.text.lower().strip())
    )

    # Обработчики статистических топов (только для админов)
    dp.register_message_handler(
        handler.show_stats_top,
        lambda m: m.text and any(word in m.text.lower() for word in [
            'выиграно', 'проиграно', 'макс выигрыш', 'макс проигрыш', 'макс ставка'
        ])
    )

    # Обработчики callback'ов для интерактивных кнопок (только для админов)
    dp.register_callback_query_handler(
        handler.handle_top_callback,
        lambda c: c.data.startswith('top_')
    )

    print("✅ Обработчики записей зарегистрированы")