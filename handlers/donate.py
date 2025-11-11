import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Enum

from aiogram import Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import text

from database import get_db
from database.crud import UserRepository, DonateRepository

# Конфигурация донат-товаров (сохраняем оригинальную структуру)
DONATE_ITEMS = [
    {
        "id": 1,
        "name": "👑 Вор в законе",
        "price": "3000 руб",
        "duration": "30 дней",
        "description": "👑 Вор в законе - 3000 руб 30 дней",
        "benefit": "🎯 Можете красть монеты у других игроков!\n💰 Ежедневный бонус: 100,000 монет"
    },
    {
        "id": 2,
        "name": "👮‍♂️ Полицейский",
        "price": "1500 руб",
        "duration": "30 дней",
        "description": "👮‍♂️ Полицейский - 1500 руб 30 дней",
        "benefit": "⚖️ Можете арестовывать воров!\n💰 Ежедневный бонус: 50,000 монет"
    },
    {
        "id": 3,
        "name": "🔐 Снятие лимита перевода",
        "price": "100 руб",
        "duration": "навсегда",
        "description": "🔐 Снятие лимита перевода - 100 руб",
        "benefit": "💸 Можете переводить неограниченные суммы!"
    }
]

# Константы
BONUS_AMOUNT = 5000
BONUS_COOLDOWN_HOURS = 24
THIEF_BONUS_AMOUNT = 100000
POLICE_BONUS_AMOUNT = 50000
PRIVILEGE_BONUS_COOLDOWN_HOURS = 24
SUPPORT_USERNAME = "EXEZ_Kassa"


class BonusType(Enum):
    DAILY = "daily"
    THIEF = "thief"
    POLICE = "police"


class DonateHandler:
    """Класс для обработки операций доната"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._init_bonus_table()

    @contextmanager
    def _db_session(self):
        """Контекстный менеджер для работы с БД"""
        session = None
        try:
            session = next(get_db())
            yield session
        except Exception as e:
            self.logger.error(f"Database connection error: {e}")
            if session:
                session.rollback()
            raise
        finally:
            if session:
                session.close()

    def _init_bonus_table(self):
        """Создает таблицу для бонусов если ее нет"""
        with self._db_session() as db:
            try:
                db.execute(text('''
                                CREATE TABLE IF NOT EXISTS user_bonuses
                                (
                                    id
                                    SERIAL
                                    PRIMARY
                                    KEY,
                                    telegram_id
                                    BIGINT
                                    UNIQUE
                                    NOT
                                    NULL,
                                    last_bonus_time
                                    BIGINT
                                    DEFAULT
                                    0,
                                    bonus_count
                                    INTEGER
                                    DEFAULT
                                    0,
                                    last_thief_bonus_time
                                    BIGINT
                                    DEFAULT
                                    0,
                                    last_police_bonus_time
                                    BIGINT
                                    DEFAULT
                                    0,
                                    thief_bonus_count
                                    INTEGER
                                    DEFAULT
                                    0,
                                    police_bonus_count
                                    INTEGER
                                    DEFAULT
                                    0,
                                    created_at
                                    TIMESTAMP
                                    DEFAULT
                                    CURRENT_TIMESTAMP
                                )
                                '''))
                db.commit()
                self.logger.info("✅ Таблица user_bonuses создана/проверена")

            except Exception as e:
                self.logger.error(f"❌ Ошибка создания таблицы бонусов: {e}")
                db.rollback()

    def _create_donate_keyboard(self, user_id: int = None) -> InlineKeyboardMarkup:
        """Создает клавиатуру доната с учетом купленных привилегий"""
        keyboard = InlineKeyboardMarkup(row_width=1)

        with self._db_session() as db:
            try:
                # Получаем все покупки пользователя
                user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                purchased_ids = [p.item_id for p in user_purchases]

                # Кнопки для всех товаров доната
                for item in DONATE_ITEMS:
                    if item["id"] in purchased_ids:
                        # Привилегия уже куплена - ИСПОЛЬЗУЕМ СТАРЫЙ ФОРМАТ callback
                        button_text = f"✅ {item['name']} (куплено)"
                        callback_data = f"donate_already_bought_{item['id']}"
                    else:
                        # Привилегия доступна для покупки - ИСПОЛЬЗУЕМ СТАРЫЙ ФОРМАТ callback
                        button_text = f"{item['name']} - {item['price']}"
                        callback_data = f"donate_buy_{item['id']}"

                    keyboard.add(InlineKeyboardButton(
                        text=button_text,
                        callback_data=callback_data
                    ))

                # Кнопка "Бонус"
                keyboard.add(InlineKeyboardButton(
                    text=f"🎁 Бонус ({BONUS_AMOUNT} монет / {BONUS_COOLDOWN_HOURS}ч)",
                    callback_data="daily_bonus"
                ))

                # Кнопка "Бонусы за привилегии"
                keyboard.add(InlineKeyboardButton(
                    text="💰 Бонусы за привилегии",
                    callback_data="privilege_bonus"
                ))

            except Exception as e:
                self.logger.error(f"Error creating donate keyboard: {e}")

        return keyboard

    def _get_donate_message_text(self) -> str:
        """Форматирует текст сообщения для доната"""
        text = (
            "💎 <b>Донат магазин</b>\n\n"
            "✨ <b>Доступные привилегии:</b>\n"
        )

        # Добавляем все товары в описание
        for item in DONATE_ITEMS:
            text += f"• {item['description']}\n"

        text += f"\n🎁 <b>Ежедневный бонус:</b> {BONUS_AMOUNT} монет каждые {BONUS_COOLDOWN_HOURS} часа\n"
        text += f"👑 <b>Бонус Вора:</b> {THIEF_BONUS_AMOUNT:,} монет каждые {PRIVILEGE_BONUS_COOLDOWN_HOURS} часа\n"
        text += f"👮‍♂️ <b>Бонус Полицейского:</b> {POLICE_BONUS_AMOUNT:,} монет каждые {PRIVILEGE_BONUS_COOLDOWN_HOURS} часа\n\n"
        text += f"💬 <b>По вопросам покупки:</b> @{SUPPORT_USERNAME}"

        return text

    async def _ensure_private_chat(self, message: types.Message) -> bool:
        """Проверяет, что команда вызвана в личных сообщениях"""
        if message.chat.type != "private":
            bot_username = (await message.bot.get_me()).username
            bot_link = f"https://t.me/{bot_username}"

            await message.reply(
                f"💎 <b>Донат магазин</b>\n"
                f"Команда работает только в <a href='{bot_link}'>личных сообщениях</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return False
        return True

    # Основные команды (сохраняем оригинальные названия методов)
    async def donate_command(self, message: types.Message):
        """Обработчик команды доната"""
        if not await self._ensure_private_chat(message):
            return

        donate_text = self._get_donate_message_text()
        keyboard = self._create_donate_keyboard(message.from_user.id)

        await message.answer(
            donate_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    async def bonus_command(self, message: types.Message):
        """Обработчик команды бонуса"""
        await self._handle_bonus_request(message)

    async def privilege_bonus_command(self, message: types.Message):
        """Обработчик команды бонусов за привилегии"""
        await self._handle_privilege_bonus_request(message)

    async def _handle_bonus_request(self, message: types.Message):
        """Обрабатывает запрос на бонус"""
        if not await self._ensure_private_chat(message):
            return

        user_id = message.from_user.id
        bonus_info = await self.check_daily_bonus(user_id)

        if bonus_info["available"]:
            success = await self.claim_daily_bonus(
                user_id=user_id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or "User"
            )

            if success:
                updated_bonus_info = await self.check_daily_bonus(user_id)

                await message.answer(
                    f"🎉 <b>Бонус получен!</b>\n\n"
                    f"💰 Вам начислено: <b>{BONUS_AMOUNT} монет</b>\n"
                    f"📊 Всего получено бонусов: <b>{updated_bonus_info['bonus_count']}</b>\n\n"
                    f"⏰ Следующий бонус через <b>{BONUS_COOLDOWN_HOURS} часа</b>",
                    reply_markup=self._get_bonus_keyboard(),
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "❌ <b>Ошибка!</b>\n\nНе удалось выдать бонус. Попробуйте позже.",
                    reply_markup=self._get_bonus_keyboard(),
                    parse_mode="HTML"
                )
        else:
            time_left = self._format_time_left(bonus_info['hours_left'], bonus_info['minutes_left'])

            await message.answer(
                f"⏳ <b>Бонус еще не доступен</b>\n\n"
                f"🕐 До следующего бонуса: <b>{time_left}</b>\n"
                f"📊 Всего получено бонусов: <b>{bonus_info['bonus_count']}</b>\n\n"
                f"💫 Приходите позже!",
                reply_markup=self._get_bonus_keyboard(),
                parse_mode="HTML"
            )

    async def _handle_privilege_bonus_request(self, message: types.Message):
        """Обрабатывает запрос на бонусы за привилегии"""
        if not await self._ensure_private_chat(message):
            return

        user_id = message.from_user.id
        privilege_bonus_info = await self.check_privilege_bonus(user_id)

        if privilege_bonus_info["available"]:
            success, bonuses_claimed = await self.claim_privilege_bonus(
                user_id=user_id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or "User"
            )

            if success:
                updated_bonus_info = await self.check_privilege_bonus(user_id)

                bonus_text = "🎉 <b>Бонусы за привилегии получены!</b>\n\n"
                total_bonus = 0

                if "thief" in bonuses_claimed:
                    bonus_text += f"👑 Бонус Вора: <b>{THIEF_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += THIEF_BONUS_AMOUNT
                if "police" in bonuses_claimed:
                    bonus_text += f"👮‍♂️ Бонус Полицейского: <b>{POLICE_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += POLICE_BONUS_AMOUNT

                bonus_text += f"\n💰 Всего получено: <b>{total_bonus:,} монет</b>\n"
                bonus_text += f"📊 Всего бонусов Вора: <b>{updated_bonus_info['thief_bonus_count']}</b>\n"
                bonus_text += f"📊 Всего бонусов Полицейского: <b>{updated_bonus_info['police_bonus_count']}</b>\n\n"
                bonus_text += f"⏰ Следующие бонусы через <b>{PRIVILEGE_BONUS_COOLDOWN_HOURS} часа</b>"

                await message.answer(
                    bonus_text,
                    reply_markup=self._get_privilege_bonus_keyboard(),
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "❌ <b>Ошибка!</b>\n\nНе удалось выдать бонусы. Попробуйте позже.",
                    reply_markup=self._get_privilege_bonus_keyboard(),
                    parse_mode="HTML"
                )
        else:
            time_left = self._format_time_left(privilege_bonus_info['hours_left'], privilege_bonus_info['minutes_left'])

            bonus_text = "⏳ <b>Бонусы за привилегии еще не доступны</b>\n\n"

            if privilege_bonus_info['has_thief']:
                bonus_text += f"👑 Вор в законе: бонус доступен через <b>{time_left}</b>\n"
            if privilege_bonus_info['has_police']:
                bonus_text += f"👮‍♂️ Полицейский: бонус доступен через <b>{time_left}</b>\n"

            bonus_text += f"\n📊 Всего бонусов Вора: <b>{privilege_bonus_info['thief_bonus_count']}</b>\n"
            bonus_text += f"📊 Всего бонусов Полицейского: <b>{privilege_bonus_info['police_bonus_count']}</b>\n\n"
            bonus_text += "💫 Приходите позже!"

            await message.answer(
                bonus_text,
                reply_markup=self._get_privilege_bonus_keyboard(),
                parse_mode="HTML"
            )

    # Методы проверки бонусов (сохраняем оригинальные названия)
    async def check_daily_bonus(self, user_id: int) -> Dict[str, Any]:
        """Проверяет доступность ежедневного бонуса"""
        with self._db_session() as db:
            try:
                result = db.execute(
                    text("SELECT last_bonus_time, bonus_count FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                current_time = int(time.time())

                if not result:
                    return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": 0}

                last_bonus_time, bonus_count = result

                if not last_bonus_time or last_bonus_time == 0:
                    return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": bonus_count or 0}

                time_since_last_bonus = current_time - last_bonus_time
                hours_since_last_bonus = time_since_last_bonus / 3600

                if hours_since_last_bonus >= BONUS_COOLDOWN_HOURS:
                    return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": bonus_count or 0}
                else:
                    hours_left = BONUS_COOLDOWN_HOURS - hours_since_last_bonus
                    minutes_left = int((hours_left - int(hours_left)) * 60)
                    return {
                        "available": False,
                        "hours_left": int(hours_left),
                        "minutes_left": minutes_left,
                        "bonus_count": bonus_count or 0
                    }

            except Exception as e:
                self.logger.error(f"❌ Ошибка проверки бонуса: {e}")
                return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": 0}

    async def check_privilege_bonus(self, user_id: int) -> Dict[str, Any]:
        """Проверяет доступность бонусов за привилегии"""
        with self._db_session() as db:
            try:
                user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                purchased_ids = [p.item_id for p in user_purchases]

                has_thief = 1 in purchased_ids
                has_police = 2 in purchased_ids

                if not has_thief and not has_police:
                    return {
                        "available": False,
                        "hours_left": 0,
                        "minutes_left": 0,
                        "has_thief": False,
                        "has_police": False,
                        "thief_bonus_count": 0,
                        "police_bonus_count": 0
                    }

                result = db.execute(
                    text("SELECT 1 FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                if not result:
                    return {
                        "available": True,
                        "hours_left": 0,
                        "minutes_left": 0,
                        "has_thief": has_thief,
                        "has_police": has_police,
                        "thief_bonus_count": 0,
                        "police_bonus_count": 0
                    }

                result = db.execute(
                    text("""
                         SELECT last_thief_bonus_time,
                                last_police_bonus_time,
                                thief_bonus_count,
                                police_bonus_count
                         FROM user_bonuses
                         WHERE telegram_id = :user_id
                         """),
                    {"user_id": user_id}
                ).fetchone()

                current_time = int(time.time())
                any_bonus_available = False
                hours_left = 0

                if result:
                    last_thief_time, last_police_time, thief_count, police_count = result

                    # Проверяем бонус за Вора
                    if has_thief:
                        if not last_thief_time or last_thief_time == 0:
                            any_bonus_available = True
                        else:
                            time_since_thief_bonus = current_time - last_thief_time
                            hours_since_thief_bonus = time_since_thief_bonus / 3600

                            if hours_since_thief_bonus >= PRIVILEGE_BONUS_COOLDOWN_HOURS:
                                any_bonus_available = True
                            else:
                                thief_hours_left = PRIVILEGE_BONUS_COOLDOWN_HOURS - hours_since_thief_bonus
                                hours_left = max(hours_left, thief_hours_left)

                    # Проверяем бонус за Полицейского
                    if has_police:
                        if not last_police_time or last_police_time == 0:
                            any_bonus_available = True
                        else:
                            time_since_police_bonus = current_time - last_police_time
                            hours_since_police_bonus = time_since_police_bonus / 3600

                            if hours_since_police_bonus >= PRIVILEGE_BONUS_COOLDOWN_HOURS:
                                any_bonus_available = True
                            else:
                                police_hours_left = PRIVILEGE_BONUS_COOLDOWN_HOURS - hours_since_police_bonus
                                hours_left = max(hours_left, police_hours_left)

                else:
                    any_bonus_available = has_thief or has_police
                    thief_count = 0
                    police_count = 0

                minutes_left = int((hours_left - int(hours_left)) * 60) if hours_left > 0 else 0

                return {
                    "available": any_bonus_available,
                    "hours_left": int(hours_left),
                    "minutes_left": minutes_left,
                    "has_thief": has_thief,
                    "has_police": has_police,
                    "thief_bonus_count": thief_count if result else 0,
                    "police_bonus_count": police_count if result else 0
                }

            except Exception as e:
                self.logger.error(f"❌ Ошибка проверки бонусов за привилегии: {e}")
                return {
                    "available": False,
                    "hours_left": 0,
                    "minutes_left": 0,
                    "has_thief": False,
                    "has_police": False,
                    "thief_bonus_count": 0,
                    "police_bonus_count": 0
                }

    # Методы выдачи бонусов (сохраняем оригинальные названия)
    async def claim_daily_bonus(self, user_id: int, username: str = "", first_name: str = "User") -> bool:
        """Выдает ежедневный бонус пользователю"""
        with self._db_session() as db:
            try:
                bonus_info = await self.check_daily_bonus(user_id)

                if not bonus_info["available"]:
                    return False

                user = UserRepository.get_or_create_user(
                    db=db,
                    telegram_id=user_id,
                    username=username,
                    first_name=first_name
                )

                if not user:
                    return False

                current_time = int(time.time())
                user.coins += BONUS_AMOUNT

                if bonus_info["bonus_count"] > 0:
                    db.execute(text('''
                                    UPDATE user_bonuses
                                    SET last_bonus_time = :current_time,
                                        bonus_count     = bonus_count + 1
                                    WHERE telegram_id = :user_id
                                    '''), {"user_id": user_id, "current_time": current_time})
                else:
                    db.execute(text('''
                                    INSERT INTO user_bonuses (telegram_id, last_bonus_time, bonus_count)
                                    VALUES (:user_id, :current_time, 1)
                                    '''), {"user_id": user_id, "current_time": current_time})

                db.commit()
                self.logger.info(f"✅ Бонус выдан пользователю {user_id}")
                return True

            except Exception as e:
                self.logger.error(f"❌ Ошибка выдачи бонуса пользователю {user_id}: {e}")
                db.rollback()
                return False

    async def claim_privilege_bonus(self, user_id: int, username: str = "", first_name: str = "User") -> Tuple[
        bool, List[str]]:
        """Выдает бонусы за привилегии пользователю"""
        with self._db_session() as db:
            try:
                bonus_info = await self.check_privilege_bonus(user_id)

                if not bonus_info["available"]:
                    return False, []

                user = UserRepository.get_or_create_user(
                    db=db,
                    telegram_id=user_id,
                    username=username,
                    first_name=first_name
                )

                if not user:
                    return False, []

                user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                purchased_ids = [p.item_id for p in user_purchases]

                has_thief = 1 in purchased_ids
                has_police = 2 in purchased_ids

                bonuses_claimed = []
                current_time = int(time.time())

                # Начисляем бонус за Вора
                if has_thief and bonus_info["has_thief"]:
                    last_thief_time = await self._get_last_thief_bonus_time(user_id)
                    if not last_thief_time or current_time - last_thief_time >= PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600:
                        user.coins += THIEF_BONUS_AMOUNT
                        bonuses_claimed.append("thief")

                # Начисляем бонус за Полицейского
                if has_police and bonus_info["has_police"]:
                    last_police_time = await self._get_last_police_bonus_time(user_id)
                    if not last_police_time or current_time - last_police_time >= PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600:
                        user.coins += POLICE_BONUS_AMOUNT
                        bonuses_claimed.append("police")

                if not bonuses_claimed:
                    return False, []

                # Обновляем записи в БД
                bonus_record_exists = db.execute(
                    text("SELECT 1 FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                if bonus_record_exists:
                    update_query = "UPDATE user_bonuses SET "
                    params = {"user_id": user_id}
                    updates = []

                    if "thief" in bonuses_claimed:
                        updates.append("last_thief_bonus_time = :thief_time")
                        updates.append("thief_bonus_count = thief_bonus_count + 1")
                        params["thief_time"] = current_time

                    if "police" in bonuses_claimed:
                        updates.append("last_police_bonus_time = :police_time")
                        updates.append("police_bonus_count = police_bonus_count + 1")
                        params["police_time"] = current_time

                    if updates:
                        update_query += ", ".join(updates)
                        update_query += " WHERE telegram_id = :user_id"
                        db.execute(text(update_query), params)
                else:
                    insert_query = """
                                   INSERT INTO user_bonuses
                                   (telegram_id, last_thief_bonus_time, thief_bonus_count, last_police_bonus_time, \
                                    police_bonus_count)
                                   VALUES (:user_id, :thief_time, :thief_count, :police_time, :police_count) \
                                   """
                    params = {"user_id": user_id}

                    if "thief" in bonuses_claimed:
                        params["thief_time"] = current_time
                        params["thief_count"] = 1
                    else:
                        params["thief_time"] = 0
                        params["thief_count"] = 0

                    if "police" in bonuses_claimed:
                        params["police_time"] = current_time
                        params["police_count"] = 1
                    else:
                        params["police_time"] = 0
                        params["police_count"] = 0

                    db.execute(text(insert_query), params)

                db.commit()
                self.logger.info(f"✅ Бонусы за привилегии выданы пользователю {user_id}: {bonuses_claimed}")
                return True, bonuses_claimed

            except Exception as e:
                self.logger.error(f"❌ Ошибка выдачи бонусов за привилегии пользователю {user_id}: {e}")
                db.rollback()
                return False, []

    async def _get_last_thief_bonus_time(self, user_id: int) -> int:
        """Получает время последнего бонуса за Вора"""
        with self._db_session() as db:
            try:
                result = db.execute(
                    text("SELECT last_thief_bonus_time FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()
                return result[0] if result and result[0] else 0
            except Exception as e:
                self.logger.warning(f"Не удалось получить время бонуса Вора для {user_id}: {e}")
                return 0

    async def _get_last_police_bonus_time(self, user_id: int) -> int:
        """Получает время последнего бонуса за Полицейского"""
        with self._db_session() as db:
            try:
                result = db.execute(
                    text("SELECT last_police_bonus_time FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()
                return result[0] if result and result[0] else 0
            except Exception as e:
                self.logger.warning(f"Не удалось получить время бонуса Полицейского для {user_id}: {e}")
                return 0

    def _format_time_left(self, hours: int, minutes: int) -> str:
        """Форматирует оставшееся время"""
        if hours > 0 and minutes > 0:
            return f"{hours}ч {minutes}м"
        elif hours > 0:
            return f"{hours}ч"
        elif minutes > 0:
            return f"{minutes}м"
        else:
            return "менее минуты"

    def _get_bonus_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура для раздела бонусов"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("💰 Бонусы за привилегии", callback_data="privilege_bonus"),
            InlineKeyboardButton("⬅️ Назад в донат", callback_data="back_to_donate")
        )
        return keyboard

    def _get_privilege_bonus_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура для раздела бонусов за привилегии"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🎁 Обычный бонус", callback_data="daily_bonus"),
            InlineKeyboardButton("⬅️ Назад в донат", callback_data="back_to_donate")
        )
        return keyboard

    def _get_purchase_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура для покупки товара"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🛒 Купить", url=f"https://t.me/{SUPPORT_USERNAME}"),
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_donate")
        )
        return keyboard

    def _get_back_keyboard(self) -> InlineKeyboardMarkup:
        """Простая клавиатура с кнопкой назад"""
        return InlineKeyboardMarkup().add(
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_donate")
        )

    # Callback обработчики (сохраняем оригинальную структуру)
    async def donate_callback_handler(self, callback: types.CallbackQuery):
        """Обработчик нажатий на кнопки доната"""
        if callback.message.chat.type != "private":
            await callback.answer("💎 Команда работает только в личных сообщениях", show_alert=True)
            return

        action = callback.data
        user_id = callback.from_user.id

        try:
            if action == "daily_bonus":
                await self._handle_daily_bonus_callback(callback, user_id)
            elif action == "privilege_bonus":
                await self._handle_privilege_bonus_callback(callback, user_id)
            elif action.startswith("donate_buy_"):
                await self._handle_purchase_selection(callback)
            elif action.startswith("donate_already_bought_"):
                await self._handle_already_bought(callback)
            elif action == "back_to_donate":
                await self._handle_back_to_donate(callback)

        except Exception as e:
            self.logger.error(f"Error in donate callback handler: {e}")
            await self._handle_error(callback)

    async def _handle_daily_bonus_callback(self, callback: types.CallbackQuery, user_id: int):
        """Обрабатывает запрос на ежедневный бонус"""
        bonus_info = await self.check_daily_bonus(user_id)

        if bonus_info["available"]:
            success = await self.claim_daily_bonus(
                user_id=user_id,
                username=callback.from_user.username or "",
                first_name=callback.from_user.first_name or "User"
            )

            if success:
                updated_bonus_info = await self.check_daily_bonus(user_id)
                await callback.message.edit_text(
                    f"🎉 <b>Бонус получен!</b>\n\n"
                    f"💰 Вам начислено: <b>{BONUS_AMOUNT} монет</b>\n"
                    f"📊 Всего получено бонусов: <b>{updated_bonus_info['bonus_count']}</b>\n\n"
                    f"⏰ Следующий бонус через <b>{BONUS_COOLDOWN_HOURS} часа</b>",
                    reply_markup=self._get_bonus_keyboard(),
                    parse_mode="HTML"
                )
                await callback.answer("🎁 Бонус успешно получен!")
            else:
                await callback.message.edit_text(
                    "❌ <b>Ошибка!</b>\n\nНе удалось выдать бонус. Попробуйте позже.",
                    reply_markup=self._get_bonus_keyboard(),
                    parse_mode="HTML"
                )
                await callback.answer("⚠️ Ошибка при получении бонуса")
        else:
            time_left = self._format_time_left(bonus_info['hours_left'], bonus_info['minutes_left'])
            await callback.message.edit_text(
                f"⏳ <b>Бонус еще не доступен</b>\n\n"
                f"🕐 До следующего бонуса: <b>{time_left}</b>\n"
                f"📊 Всего получено бонусов: <b>{bonus_info['bonus_count']}</b>\n\n"
                f"💫 Приходите позже!",
                reply_markup=self._get_bonus_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer(f"⏰ Бонус будет доступен через {time_left}")

    async def _handle_privilege_bonus_callback(self, callback: types.CallbackQuery, user_id: int):
        """Обрабатывает запрос на бонусы за привилегии"""
        privilege_bonus_info = await self.check_privilege_bonus(user_id)

        if privilege_bonus_info["available"]:
            success, bonuses_claimed = await self.claim_privilege_bonus(
                user_id=user_id,
                username=callback.from_user.username or "",
                first_name=callback.from_user.first_name or "User"
            )

            if success:
                updated_bonus_info = await self.check_privilege_bonus(user_id)
                bonus_text = "🎉 <b>Бонусы за привилегии получены!</b>\n\n"
                total_bonus = 0

                if "thief" in bonuses_claimed:
                    bonus_text += f"👑 Бонус Вора: <b>{THIEF_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += THIEF_BONUS_AMOUNT
                if "police" in bonuses_claimed:
                    bonus_text += f"👮‍♂️ Бонус Полицейского: <b>{POLICE_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += POLICE_BONUS_AMOUNT

                bonus_text += f"\n💰 Всего получено: <b>{total_bonus:,} монет</b>\n"
                bonus_text += f"📊 Всего бонусов Вора: <b>{updated_bonus_info['thief_bonus_count']}</b>\n"
                bonus_text += f"📊 Всего бонусов Полицейского: <b>{updated_bonus_info['police_bonus_count']}</b>\n\n"
                bonus_text += f"⏰ Следующие бонусы через <b>{PRIVILEGE_BONUS_COOLDOWN_HOURS} часа</b>"

                await callback.message.edit_text(
                    bonus_text,
                    reply_markup=self._get_privilege_bonus_keyboard(),
                    parse_mode="HTML"
                )
                await callback.answer("💰 Бонусы успешно получены!")
            else:
                await callback.message.edit_text(
                    "❌ <b>Ошибка!</b>\n\nНе удалось выдать бонусы. Попробуйте позже.",
                    reply_markup=self._get_privilege_bonus_keyboard(),
                    parse_mode="HTML"
                )
                await callback.answer("⚠️ Ошибка при получении бонусов")
        else:
            time_left = self._format_time_left(privilege_bonus_info['hours_left'], privilege_bonus_info['minutes_left'])
            bonus_text = "⏳ <b>Бонусы за привилегии еще не доступны</b>\n\n"

            if privilege_bonus_info['has_thief']:
                bonus_text += f"👑 Вор в законе: бонус доступен через <b>{time_left}</b>\n"
            if privilege_bonus_info['has_police']:
                bonus_text += f"👮‍♂️ Полицейский: бонус доступен через <b>{time_left}</b>\n"

            bonus_text += f"\n📊 Всего бонусов Вора: <b>{privilege_bonus_info['thief_bonus_count']}</b>\n"
            bonus_text += f"📊 Всего бонусов Полицейского: <b>{privilege_bonus_info['police_bonus_count']}</b>\n\n"
            bonus_text += "💫 Приходите позже!"

            await callback.message.edit_text(
                bonus_text,
                reply_markup=self._get_privilege_bonus_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer(f"⏰ Бонусы будут доступны через {time_left}")

    async def _handle_purchase_selection(self, callback: types.CallbackQuery):
        """Обрабатывает выбор товара для покупки"""
        item_id = int(callback.data.split("_")[2])
        item = next((i for i in DONATE_ITEMS if i["id"] == item_id), None)

        if item:
            await callback.message.edit_text(
                f"💳 <b>Покупка донат-привилегии</b>\n\n"
                f"📦 Товар: <b>{item['name']}</b>\n"
                f"💰 Цена: <b>{item['price']}</b>\n"
                f"⏱️ Срок: <b>{item['duration']}</b>\n\n"
                f"🎯 <b>Преимущество:</b>\n"
                f"{item['benefit']}\n\n"
                f"💬 <b>Для покупки обратитесь:</b>\n"
                f"👤 @{SUPPORT_USERNAME}",
                reply_markup=self._get_purchase_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer(f"🛒 {item['name']}")

    async def _handle_already_bought(self, callback: types.CallbackQuery):
        """Обрабатывает нажатие на уже купленную привилегию"""
        item_id = int(callback.data.split("_")[3])
        item = next((i for i in DONATE_ITEMS if i["id"] == item_id), None)

        if item:
            await callback.message.edit_text(
                f"✅ <b>Привилегия уже куплена</b>\n\n"
                f"📦 Товар: <b>{item['name']}</b>\n"
                f"💰 Цена: <b>{item['price']}</b>\n"
                f"⏱️ Срок: <b>{item['duration']}</b>\n\n"
                f"🎯 <b>Преимущество:</b>\n"
                f"{item['benefit']}\n\n"
                f"💡 Эта привилегия уже активна в вашем профиле!",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer("✅ Уже куплено")

    async def _handle_back_to_donate(self, callback: types.CallbackQuery):
        """Возвращает в главное меню доната"""
        donate_text = self._get_donate_message_text()
        keyboard = self._create_donate_keyboard(callback.from_user.id)

        await callback.message.edit_text(
            donate_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer("⬅️ Возврат в меню")

    async def _handle_error(self, callback: types.CallbackQuery):
        """Обрабатывает общие ошибки"""
        await callback.message.edit_text(
            "❌ <b>Произошла ошибка!</b>\n\n"
            "Пожалуйста, попробуйте позже или обратитесь к администратору.",
            reply_markup=self._get_back_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer("⚠️ Произошла ошибка")


def register_donate_handlers(dp: Dispatcher):
    """Регистрация обработчиков доната"""
    handler = DonateHandler()

    # Регистрация команд доната
    dp.register_message_handler(
        handler.donate_command,
        commands=["донат", "donate"],
        state="*"
    )
    dp.register_message_handler(
        handler.donate_command,
        lambda m: m.text and m.text.lower() in ["донат", "donate"],
        state="*"
    )

    # Регистрация команд бонуса
    dp.register_message_handler(
        handler.bonus_command,
        commands=["бонус", "bonus"],
        state="*"
    )
    dp.register_message_handler(
        handler.bonus_command,
        lambda m: m.text and m.text.lower() in ["бонус", "bonus"],
        state="*"
    )

    # Регистрация команд бонусов за привилегии
    dp.register_message_handler(
        handler.privilege_bonus_command,
        commands=["привилегиябонус", "privilegebonus"],
        state="*"
    )
    dp.register_message_handler(
        handler.privilege_bonus_command,
        lambda m: m.text and m.text.lower() in ["привилегиябонус", "privilegebonus", "бонусы"],
        state="*"
    )

    # Регистрация callback обработчиков

    donate_callbacks = [
        "donate_buy_", "donate_already_bought_", "daily_bonus", "privilege_bonus", "back_to_donate"
    ]

    dp.register_callback_query_handler(
        handler.donate_callback_handler,
        lambda c: any(c.data.startswith(prefix) for prefix in donate_callbacks),
        state="*"
    )

    logging.info("✅ Донат обработчики зарегистрированы (с бонусами за привилегии)")