# donate_product/police_handler.py
import logging
import re
from datetime import datetime, timedelta
from aiogram import types, Dispatcher
from database import get_db
from database.crud import PoliceRepository, ShopRepository, UserRepository

logger = logging.getLogger(__name__)


class PoliceHandler:
    def __init__(self):
        self.logger = logger
        self.MAX_ARREST_MINUTES = 1440  # Максимум 24 часа
        self.MIN_ARREST_MINUTES = 1  # Минимум 1 минута
        self.DEFAULT_ARREST_MINUTES = 180  # По умолчанию 5 минут
        self.POLICE_PRIVILEGE_ID = 2  # ID привилегии Полицейский
        self.THIEF_PRIVILEGE_ID = 1   # ID привилегии Вор в законе

    async def _ensure_table_exists(self):
        """Проверяет существование таблицы и создает если нужно"""
        from database import Base, engine

        try:
            # Создаем все таблицы, которые еще не созданы
            Base.metadata.create_all(bind=engine)
            self.logger.info("✅ Все таблицы проверены/созданы")

        except Exception as e:
            self.logger.error(f"Ошибка при создании таблиц: {e}")

    async def _check_police_permission(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя права полицейского"""
        db = next(get_db())
        try:
            user_purchases = ShopRepository.get_user_purchases(db, user_id)

            if self.POLICE_PRIVILEGE_ID in user_purchases:
                return await self._check_privilege_expiry(db, user_id, self.POLICE_PRIVILEGE_ID)

            return False
        except Exception as e:
            self.logger.error(f"Error checking police permission: {e}")
            return False
        finally:
            db.close()

    async def _check_thief_permission(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя права Вора в законе"""
        db = next(get_db())
        try:
            user_purchases = ShopRepository.get_user_purchases(db, user_id)

            if self.THIEF_PRIVILEGE_ID in user_purchases:
                return await self._check_privilege_expiry(db, user_id, self.THIEF_PRIVILEGE_ID)

            return False
        except Exception as e:
            self.logger.error(f"Error checking thief permission: {e}")
            return False
        finally:
            db.close()

    async def _check_privilege_expiry(self, db, user_id: int, privilege_id: int) -> bool:
        """Проверяет, не истекла ли привилегия"""
        try:
            from sqlalchemy import text
            result = db.execute(
                text("""
                     SELECT expires_at
                     FROM user_purchases
                     WHERE user_id = :user_id
                       AND item_id = :item_id
                     """),
                {"user_id": user_id, "item_id": privilege_id}
            ).fetchone()

            if result and result[0]:
                # Если есть срок действия, проверяем его
                return result[0] > datetime.now()

            # Если срока нет, привилегия действует вечно
            return True

        except Exception as e:
            self.logger.error(f"Error checking privilege expiry: {e}")
            return True

    def _parse_arrest_time(self, text: str) -> int:
        """Парсит время ареста из текста команды"""
        try:
            # Приводим к нижнему регистру и убираем лишние пробелы
            text = text.lower().strip()

            # Если команда состоит только из слова "арест" или похожих вариантов
            if text in ['арест', '!арест', '/арест', '/arrest', 'арестовать']:
                return self.DEFAULT_ARREST_MINUTES  # 180 минут (3 часа)

            # Ищем паттерны времени
            time_match = re.search(r'(\d+)\s*(м|мин|минут|ч|час|часов|чс|д|день|дней|дня)', text)
            if time_match:
                number = int(time_match.group(1))
                unit = time_match.group(2)

                # Конвертируем в минуты
                if unit in ['ч', 'час', 'часов', 'чс']:
                    minutes = number * 60
                elif unit in ['д', 'день', 'дней', 'дня']:
                    minutes = number * 24 * 60
                else:
                    minutes = number
            else:
                # Если нет указания времени, ищем просто числа
                numbers = re.findall(r'\d+', text)
                if numbers:
                    minutes = int(numbers[-1])
                else:
                    minutes = self.DEFAULT_ARREST_MINUTES

            # Ограничиваем время ареста
            minutes = max(self.MIN_ARREST_MINUTES, min(minutes, self.MAX_ARREST_MINUTES))
            return minutes

        except (ValueError, IndexError):
            return self.DEFAULT_ARREST_MINUTES

    def _format_time_delta(self, delta: timedelta) -> str:
        """Форматирует временной интервал в читаемый вид"""
        total_seconds = int(delta.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        parts = []
        if days > 0:
            parts.append(f"{days}д")
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")

        return " ".join(parts) if parts else "0м"

    def _format_time_left(self, minutes: int) -> str:
        """Форматирует оставшееся время ареста"""
        if minutes >= 1440:  # 24 часа
            days = minutes // 1440
            hours = (minutes % 1440) // 60
            if hours > 0:
                return f"{days}д {hours}ч"
            return f"{days}д"
        elif minutes >= 60:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            if remaining_minutes > 0:
                return f"{hours}ч {remaining_minutes}м"
            return f"{hours}ч"
        else:
            return f"{minutes}м"

    async def _check_user_exists(self, user_id: int) -> bool:
        """Проверяет, существует ли пользователь в базе"""
        db = next(get_db())
        try:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            return user is not None
        except Exception as e:
            self.logger.error(f"Error checking user existence: {e}")
            return False
        finally:
            db.close()

    async def arrest_user(self, message: types.Message):
        """Команда 'арест' - арестовывает пользователя"""
        try:
            # Проверяем и создаем таблицу если нужно
            await self._ensure_table_exists()

            # Проверяем права доступа полицейского
            if not await self._check_police_permission(message.from_user.id):
                await message.reply(
                    "🚫 Эта команда доступна только для <b>Полицейских</b>!\n\n"
                    "💎 Для получения привилегии обратитесь к администратору:\n"
                    "👉 /admin_help",
                    parse_mode="HTML"
                )
                return

            if not message.reply_to_message:
                await message.reply("❗ Ответь на сообщение пользователя, чтобы арестовать его.")
                return

            police = message.from_user
            target = message.reply_to_message.from_user

            # Проверяем, не пытается ли пользователь арестовать самого себя
            if police.id == target.id:
                await message.reply("❌ Нельзя арестовать самого себя!")
                return

            # Проверяем, не пытается ли арестовать бота
            bot_user = await message.bot.get_me()
            if target.id == bot_user.id:
                await message.reply("❌ Нельзя арестовать бота!")
                return

            # Проверяем, существует ли пользователь в базе
            if not await self._check_user_exists(target.id):
                await message.reply("❌ Пользователь не найден в базе данных!")
                return

            # ПРОВЕРЯЕМ, ЕСТЬ ЛИ У ЦЕЛИ ПРИВИЛЕГИЯ "ВОР В ЗАКОНЕ"
            if not await self._check_thief_permission(target.id):
                await message.reply(
                    "🚫 <b>Невозможно арестовать!</b>\n\n"
                    f"👤 Пользователь <b>{target.full_name}</b> не имеет привилегии <b>«Вор в законе»</b>\n\n"
                    "💎 Арестовать можно только пользователей с привилегией <b>«Вор в законе»</b>\n"
                    "🔒 Обычные пользователи не подлежат аресту",
                    parse_mode="HTML"
                )
                return

            # Парсим время ареста
            minutes = self._parse_arrest_time(message.text)
            release_time = datetime.now() + timedelta(minutes=minutes)

            db = next(get_db())
            try:
                # Проверяем, не арестован ли уже пользователь
                existing_arrest = PoliceRepository.get_user_arrest(db, target.id)
                if existing_arrest:
                    time_left = existing_arrest.release_time - datetime.now()
                    time_left_str = self._format_time_delta(time_left)

                    await message.reply(
                        f"⚠️ {target.full_name} уже арестован!\n"
                        f"⏳ Освобождение через: {time_left_str}\n"
                        f"🕐 Время освобождения: {existing_arrest.release_time.strftime('%H:%M')}"
                    )
                    return

                # Арестовываем пользователя
                PoliceRepository.arrest_user(db, target.id, police.id, release_time)
                db.commit()

                time_str = self._format_time_left(minutes)

                await message.reply(
                    f"🚔 <b>АРЕСТ ВОРА В ЗАКОНЕ</b>\n\n"
                    f"👮 Полицейский: {police.full_name}\n"
                    f"🎯 Вор в законе: {target.full_name}\n"
                    f"⏰ Срок: {time_str}\n"
                    f"🕐 Освобождение: {release_time.strftime('%H:%M')}\n\n"
                    f"<i>Для проверки ареста используй /проверить</i>",
                    parse_mode="HTML"
                )

                self.logger.info(f"Police {police.id} arrested thief {target.id} for {minutes} minutes")

            except Exception as e:
                db.rollback()
                self.logger.error(f"Database error in arrest_user: {e}")
                await message.reply("❌ Произошла ошибка при аресте. Попробуйте позже.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in arrest_user: {e}")
            await message.reply("❌ Произошла ошибка при обработке команды.")

    async def unarrest_user(self, message: types.Message):
        """Команда 'разжаловать' - снимает арест с пользователя"""
        try:
            # Проверяем и создаем таблицу если нужно
            await self._ensure_table_exists()

            if not await self._check_police_permission(message.from_user.id):
                await message.reply(
                    "🚫 Эта команда доступна только для <b>Полицейских</b>!\n\n"
                    "💎 Для получения привилегии обратитесь к администратору:\n"
                    "👉 /admin_help",
                    parse_mode="HTML"
                )
                return

            if not message.reply_to_message:
                await message.reply("❗ Ответь на сообщение пользователя, чтобы снять арест.")
                return

            police = message.from_user
            target = message.reply_to_message.from_user

            # Проверяем, не пытается ли снять арест с бота
            bot_user = await message.bot.get_me()
            if target.id == bot_user.id:
                await message.reply("❌ Бот не может быть арестован!")
                return

            db = next(get_db())
            try:
                # Проверяем, арестован ли пользователь
                existing_arrest = PoliceRepository.get_user_arrest(db, target.id)

                if not existing_arrest:
                    await message.reply(f"ℹ️ {target.full_name} не арестован.")
                    return

                # Снимаем арест
                result = PoliceRepository.unarrest_user(db, target.id)
                db.commit()

                if result:
                    await message.reply(
                        f"✅ <b>СНЯТИЕ АРЕСТА С ВОРА</b>\n\n"
                        f"👮 Полицейский: {police.full_name}\n"
                        f"🎯 Вор в законе: {target.full_name}\n"
                        f"🎉 Арест снят! Вор снова на свободе!",
                        parse_mode="HTML"
                    )
                    self.logger.info(f"Police {police.id} unarrested thief {target.id}")
                else:
                    await message.reply("❌ Не удалось снять арест.")

            except Exception as e:
                db.rollback()
                self.logger.error(f"Database error in unarrest_user: {e}")
                await message.reply("❌ Произошла ошибка при снятии ареста.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in unarrest_user: {e}")
            await message.reply("❌ Произошла ошибка при обработке команды.")

    async def check_arrest(self, message: types.Message):
        """Команда 'проверить' - проверяет арест пользователя"""
        try:
            # Проверяем и создаем таблицу если нужно
            await self._ensure_table_exists()

            target_user = message.from_user

            # Если команда отправлена в ответ на сообщение, проверяем того пользователя
            if message.reply_to_message:
                target_user = message.reply_to_message.from_user

            db = next(get_db())
            try:
                arrest = PoliceRepository.get_user_arrest(db, target_user.id)

                if arrest and arrest.release_time > datetime.now():
                    time_left = arrest.release_time - datetime.now()
                    time_left_str: str = self._format_time_delta(time_left)

                    # Получаем информацию о полицейском, который арестовал
                    arresting_police = UserRepository.get_user_by_telegram_id(db, arrest.arrested_by)
                    police_name = arresting_police.first_name if arresting_police else "Неизвестный полицейский"

                    # Проверяем, есть ли у пользователя привилегия Вора
                    is_thief = await self._check_thief_permission(target_user.id)
                    user_type = "🔒 Вор в законе" if is_thief else "👤 Пользователь"

                    await message.reply(
                        f"🔒 <b>СТАТУС: АРЕСТОВАН</b>\n\n"
                        f"{user_type}: {target_user.full_name}\n"
                        f"👮 Арестовал: {police_name}\n"
                        f"⏳ Освобождение через: {time_left_str}\n"
                        f"🕐 Время освобождения: {arrest.release_time.strftime('%H:%M')}\n"
                        f"📅 Дата: {arrest.release_time.strftime('%d.%m.%Y')}",
                        parse_mode="HTML"
                    )
                else:
                    # Если арест истек, очищаем его
                    if arrest:
                        PoliceRepository.unarrest_user(db, target_user.id)
                        db.commit()

                    # Проверяем, есть ли у пользователя привилегия Вора
                    is_thief = await self._check_thief_permission(target_user.id)
                    user_type = "🎭 Вор в законе" if is_thief else "👤 Пользователь"

                    await message.reply(
                        f"✅ <b>СТАТУС: СВОБОДЕН</b>\n\n"
                        f"{user_type}: {target_user.full_name}\n"
                        f"🎉 Не арестован и может свободно действовать!",
                        parse_mode="HTML"
                    )

            except Exception as e:
                self.logger.error(f"Database error in check_arrest: {e}")
                await message.reply("❌ Произошла ошибка при проверке ареста.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in check_arrest: {e}")
            await message.reply("❌ Произошла ошибка при обработке команды.")

    async def police_stats(self, message: types.Message):
        """Показывает статистику полицейского"""
        try:
            # Проверяем и создаем таблицу если нужно
            await self._ensure_table_exists()

            user_id = message.from_user.id

            if not await self._check_police_permission(user_id):
                await message.reply(
                    "🚫 Эта команда доступна только для <b>Полицейских</b>!\n\n"
                    "💎 Для получения привилегии обратитесь к администратору:\n"
                    "👉 /admin_help",
                    parse_mode="HTML"
                )
                return

            db = next(get_db())
            try:
                # Получаем активные аресты
                active_arrests = PoliceRepository.get_all_active_arrests(db)

                # Получаем аресты этого полицейского
                my_arrests = PoliceRepository.get_arrests_by_police(db, user_id)
                my_active_arrests = [a for a in my_arrests if a.release_time > datetime.now()]

                # Подсчитываем только воров среди активных арестов
                thieves_arrested = 0
                for arrest in my_active_arrests:
                    if await self._check_thief_permission(arrest.user_id):
                        thieves_arrested += 1

                result = (
                    f"👮 <b>СТАТИСТИКА ПОЛИЦЕЙСКОГО</b>\n\n"
                    f"📛 Имя: {message.from_user.full_name}\n"
                    f"🔒 Арестовано воров: {thieves_arrested}\n"
                    f"🔒 Всего активных арестов в системе: {len(active_arrests)}\n\n"
                )

                if my_active_arrests:
                    result += "🔒 <b>Мои текущие аресты воров:</b>\n"
                    count = 0
                    for arrest in my_active_arrests:
                        # Показываем только арестованных воров
                        if await self._check_thief_permission(arrest.user_id):
                            try:
                                user = UserRepository.get_user_by_telegram_id(db, arrest.user_id)
                                if user:
                                    time_left = arrest.release_time - datetime.now()
                                    time_left_str = self._format_time_delta(time_left)
                                    result += f"• {user.first_name} - {time_left_str}\n"
                                    count += 1
                                    if count >= 5:  # Ограничиваем список 5 записями
                                        break
                            except:
                                continue

                await message.reply(result, parse_mode="HTML")

            except Exception as e:
                self.logger.error(f"Database error in police_stats: {e}")
                await message.reply("❌ Произошла ошибка при получении статистики.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in police_stats: {e}")
            await message.reply("❌ Произошла ошибка при обработке команды.")

    async def cleanup_arrests(self, message: types.Message):
        """Очистка истекших арестов (только для админов)"""
        try:
            # Проверяем права администратора
            db = next(get_db())
            user = UserRepository.get_user_by_telegram_id(db, message.from_user.id)
            if not user or not user.is_admin:
                await message.reply("🚫 Эта команда доступна только администраторам!")
                return

            cleaned_count = PoliceRepository.cleanup_expired_arrests(db)
            db.commit()

            await message.reply(f"✅ Очищено истекших арестов: {cleaned_count}")

        except Exception as e:
            self.logger.error(f"Error in cleanup_arrests: {e}")
            await message.reply("❌ Произошла ошибка при очистке арестов.")
        finally:
            db.close()


def register_police_handlers(dp: Dispatcher):
    """Регистрация обработчиков для команд полиции"""
    handler = PoliceHandler()

    # Регистрируем команду "арест"
    dp.register_message_handler(
        handler.arrest_user,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!арест") or
                msg.text.lower().startswith("/арест") or
                msg.text.lower().startswith("/arrest") or
                msg.text.lower().startswith("арест")
        ),
        state="*"
    )

    # Регистрируем команду "разжаловать"
    dp.register_message_handler(
        handler.unarrest_user,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!разжаловать") or
                msg.text.lower().startswith("/разжаловать") or
                msg.text.lower().startswith("/unarrest") or
                msg.text.lower().startswith("!снятьарест") or
                msg.text.lower().startswith("/снятьарест") or
                msg.text.lower().startswith("разжаловать")
        ),
        state="*"
    )

    # Регистрируем команду "проверить"
    dp.register_message_handler(
        handler.check_arrest,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!проверить") or
                msg.text.lower().startswith("/проверить") or
                msg.text.lower().startswith("/check") or
                msg.text.lower().startswith("!арест?") or
                msg.text.lower().startswith("/арест?") or
                msg.text.lower().startswith("проверить")
        ),
        state="*"
    )

    # Регистрируем команду "полиция" для статистики
    dp.register_message_handler(
        handler.police_stats,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!полиция") or
                msg.text.lower().startswith("/полиция") or
                msg.text.lower().startswith("/police") or
                msg.text.lower().startswith("полиция")
        ),
        state="*"
    )

    # Регистрируем команду очистки арестов (для админов)
    dp.register_message_handler(
        handler.cleanup_arrests,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!очисткаарестов") or
                msg.text.lower().startswith("/очисткаарестов") or
                msg.text.lower().startswith("/cleanarrests")
        ),
        state="*"
    )

    logger.info("✅ Обработчики 'полиция' зарегистрированы (только для воров)")