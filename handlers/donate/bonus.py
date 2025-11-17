# handlers/donate/bonus.py

import logging
import time
from typing import Dict, Any, Tuple, List
from contextlib import contextmanager
from datetime import datetime, timedelta
from aiogram import types
from sqlalchemy import text
from .config import BONUS_AMOUNT, BONUS_COOLDOWN_HOURS, THIEF_BONUS_AMOUNT, POLICE_BONUS_AMOUNT, PRIVILEGE_BONUS_COOLDOWN_HOURS
from database import get_db # Импортируем get_db для контекстного менеджера
from database.crud import UserRepository, DonateRepository # Предполагаем, что DonateRepository содержит логику покупок

logger = logging.getLogger(__name__)

class BonusManager:
    """Класс для управления бонусами (ежедневный и за привилегии)"""

    def __init__(self):
        self._init_bonus_table()

    def _init_bonus_table(self):
        """Создает таблицу для бонусов если ее нет"""
        with self._db_session() as db: # Используем внутренний метод
            try:
                db.execute(text('''
                    CREATE TABLE IF NOT EXISTS user_bonuses(
                        id SERIAL PRIMARY KEY,
                        telegram_id BIGINT UNIQUE NOT NULL,
                        last_bonus_time BIGINT DEFAULT 0,
                        bonus_count INTEGER DEFAULT 0,
                        last_thief_bonus_time BIGINT DEFAULT 0,
                        last_police_bonus_time BIGINT DEFAULT 0,
                        thief_bonus_count INTEGER DEFAULT 0,
                        police_bonus_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
                db.commit()
                logger.info("✅ Таблица user_bonuses создана/проверена")
            except Exception as e:
                logger.error(f"❌ Ошибка создания таблицы бонусов: {e}")
                db.rollback()

    # --- Внутренний контекстный менеджер ---
    @contextmanager
    def _db_session(self):
        """Контекстный менеджер для безопасной работы с БД (аналогично AdminHandler)"""
        session = None
        try:
            session = next(get_db())
            yield session
        except Exception as e:
            logger.error(f"Database connection error in BonusManager: {e}")
            if session:
                session.rollback()
            raise
        finally:
            if session:
                session.close()

    # --- Методы проверки бонусов ---
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
                    # Если записи нет, пользователь может получить бонус
                    return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": 0}

                last_bonus_time, bonus_count = result
                time_since_last_bonus = current_time - last_bonus_time
                cooldown_seconds = BONUS_COOLDOWN_HOURS * 3600

                if time_since_last_bonus >= cooldown_seconds:
                    return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": bonus_count or 0}
                else:
                    remaining_seconds = cooldown_seconds - time_since_last_bonus
                    hours_left = remaining_seconds / 3600
                    minutes_left = int((hours_left - int(hours_left)) * 60)
                    return {
                        "available": False,
                        "hours_left": int(hours_left),
                        "minutes_left": minutes_left,
                        "bonus_count": bonus_count or 0
                    }
            except Exception as e:
                logger.error(f"❌ Ошибка проверки ежедневного бонуса: {e}")
                return {"available": True, "hours_left": 0, "minutes_left": 0, "bonus_count": 0}

    async def check_privilege_bonus(self, user_id: int, has_thief: bool = False, has_police: bool = False) -> Dict[str, Any]:
        """
        Проверяет доступность бонусов за привилегии.
        Принимает флаги has_thief и has_police извне.
        """
        with self._db_session() as db:
            try:
                result = db.execute(
                    text("SELECT last_thief_bonus_time, last_police_bonus_time, thief_bonus_count, police_bonus_count FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                current_time = int(time.time())
                thief_bonus_count = 0
                police_bonus_count = 0

                if result:
                    last_thief_time, last_police_time, thief_bonus_count, police_bonus_count = result
                else:
                    # Создаем запись, если её нет
                    last_thief_time = 0
                    last_police_time = 0
                    # Значения по умолчанию уже 0

                # Проверяем, доступен ли бонус за Вора
                thief_available = False
                if has_thief:
                    time_since_thief_bonus = current_time - (last_thief_time or 0)
                    if time_since_thief_bonus >= PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600:
                        thief_available = True

                # Проверяем, доступен ли бонус за Полицейского
                police_available = False
                if has_police:
                    time_since_police_bonus = current_time - (last_police_time or 0)
                    if time_since_police_bonus >= PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600:
                        police_available = True

                # Бонус доступен, если есть привилегия и прошло достаточно времени
                available = thief_available or police_available

                # Если доступен, возвращаем 0 времени
                if available:
                    return {
                        "available": True,
                        "hours_left": 0,
                        "minutes_left": 0,
                        "has_thief": has_thief,
                        "has_police": has_police,
                        "thief_bonus_count": thief_bonus_count,
                        "police_bonus_count": police_bonus_count
                    }

                # Если не доступен, вычисляем оставшееся время
                # Берём минимальное время из оставшихся для активных привилегий
                remaining_times = []
                if has_thief and last_thief_time:
                    time_since = current_time - last_thief_time
                    remaining_for_thief = (PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600) - time_since
                    if remaining_for_thief > 0:
                        remaining_times.append(remaining_for_thief)
                if has_police and last_police_time:
                    time_since = current_time - last_police_time
                    remaining_for_police = (PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600) - time_since
                    if remaining_for_police > 0:
                        remaining_times.append(remaining_for_police)

                if remaining_times:
                    min_remaining = min(remaining_times)
                    hours_left = min_remaining / 3600
                    minutes_left = int((hours_left - int(hours_left)) * 60)
                else:
                    # Если привилегий нет, возвращаем 0, но доступен = False
                    hours_left, minutes_left = 0, 0

                return {
                    "available": False,
                    "hours_left": int(hours_left),
                    "minutes_left": minutes_left,
                    "has_thief": has_thief,
                    "has_police": has_police,
                    "thief_bonus_count": thief_bonus_count,
                    "police_bonus_count": police_bonus_count
                }

            except Exception as e:
                logger.error(f"❌ Ошибка проверки бонусов за привилегии: {e}")
                return {
                    "available": False,
                    "hours_left": 0,
                    "minutes_left": 0,
                    "has_thief": False,
                    "has_police": False,
                    "thief_bonus_count": 0,
                    "police_bonus_count": 0
                }

    # --- Методы выдачи бонусов ---
    async def claim_daily_bonus(self, user_id: int, username: str = "", first_name: str = "User") -> bool:
        """Выдает ежедневный бонус пользователю"""
        with self._db_session() as db:
            try:
                bonus_info = await self.check_daily_bonus(user_id)
                if not bonus_info["available"]:
                    return False

                user = UserRepository.get_or_create_user(db=db, telegram_id=user_id, username=username, first_name=first_name)
                if not user:
                    return False

                user.coins += BONUS_AMOUNT
                current_time = int(time.time())

                # Обновляем или создаём запись в user_bonuses
                result = db.execute(
                    text("SELECT bonus_count FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                new_bonus_count = (result[0] if result else 0) + 1

                db.execute(
                    text("""
                        INSERT INTO user_bonuses (telegram_id, last_bonus_time, bonus_count)
                        VALUES (:user_id, :last_time, :count)
                        ON CONFLICT (telegram_id)
                        DO UPDATE SET
                            last_bonus_time = :last_time,
                            bonus_count = :count
                    """),
                    {"user_id": user_id, "last_time": current_time, "count": new_bonus_count}
                )

                db.commit()
                logger.info(f"✅ Ежедневный бонус выдан пользователю {user_id}")
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка выдачи ежедневного бонуса пользователю {user_id}: {e}")
                db.rollback()
                return False

    async def claim_privilege_bonus(self, user_id: int, username: str = "", first_name: str = "User") -> Tuple[bool, List[str]]:
        """
        Выдает бонусы за привилегии пользователю.
        Проверяет наличие привилегий и прошёл ли кулдаун для каждой.
        """
        with self._db_session() as db:
            try:
                # Получаем активные покупки (привилегии) пользователя
                user_purchases = DonateRepository.get_user_active_purchases(db, user_id) # Используем CRUD
                purchased_ids = [p.item_id for p in user_purchases]

                has_thief = 1 in purchased_ids
                has_police = 2 in purchased_ids

                # Сначала проверяем доступность, передав флаги has_thief/has_police
                bonus_info = await self.check_privilege_bonus(user_id, has_thief, has_police)
                if not bonus_info["available"]:
                    return False, []

                user = UserRepository.get_or_create_user(db=db, telegram_id=user_id, username=username, first_name=first_name)
                if not user:
                    return False, []

                bonuses_claimed = []
                current_time = int(time.time())

                # --- Ключевое изменение: проверяем кулдаун и наличие привилегии ПЕРЕД выдачей ---
                # Получаем время последнего бонуса для каждого типа
                result = db.execute(
                    text("SELECT last_thief_bonus_time, last_police_bonus_time FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                last_thief_time = result[0] if result else 0
                last_police_time = result[1] if result else 0

                # Проверяем Вора
                if has_thief:
                    time_since_thief_bonus = current_time - last_thief_time
                    if time_since_thief_bonus >= PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600:
                        user.coins += THIEF_BONUS_AMOUNT
                        bonuses_claimed.append("thief")

                # Проверяем Полицейского
                if has_police:
                    time_since_police_bonus = current_time - last_police_time
                    if time_since_police_bonus >= PRIVILEGE_BONUS_COOLDOWN_HOURS * 3600:
                        user.coins += POLICE_BONUS_AMOUNT
                        bonuses_claimed.append("police")

                # Если ни один бонус не был начислен (например, кулдаун не прошёл для имеющихся привилегий)
                if not bonuses_claimed:
                    return False, []

                # Обновляем или создаём запись в user_bonuses
                result = db.execute(
                    text("SELECT thief_bonus_count, police_bonus_count FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                current_thief_count = result[0] if result else 0
                current_police_count = result[1] if result else 0

                new_thief_count = current_thief_count + (1 if "thief" in bonuses_claimed else 0)
                new_police_count = current_police_count + (1 if "police" in bonuses_claimed else 0)

                # Подготовим значения для обновления времени
                # Обновляем время ТОЛЬКО если бонус был начислен
                new_thief_time = current_time if "thief" in bonuses_claimed else last_thief_time
                new_police_time = current_time if "police" in bonuses_claimed else last_police_time

                db.execute(
                    text("""
                        INSERT INTO user_bonuses (telegram_id, last_thief_bonus_time, thief_bonus_count, last_police_bonus_time, police_bonus_count)
                        VALUES (:user_id, :thief_time, :thief_count, :police_time, :police_count)
                        ON CONFLICT (telegram_id)
                        DO UPDATE SET
                            last_thief_bonus_time = :thief_time,
                            thief_bonus_count = :thief_count,
                            last_police_bonus_time = :police_time,
                            police_bonus_count = :police_count
                    """),
                    {
                        "user_id": user_id,
                        "thief_time": new_thief_time,
                        "thief_count": new_thief_count,
                        "police_time": new_police_time,
                        "police_count": new_police_count
                    }
                )

                db.commit()
                logger.info(f"✅ Бонусы за привилегии выданы пользователю {user_id}: {bonuses_claimed}")
                return True, bonuses_claimed

            except Exception as e:
                logger.error(f"❌ Ошибка выдачи бонусов за привилегии пользователю {user_id}: {e}")
                db.rollback()
                return False, []
