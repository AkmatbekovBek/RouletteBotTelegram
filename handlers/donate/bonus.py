# handlers/donate/bonus.py

import logging
import time
from typing import Dict, Any, Tuple, List
from contextlib import contextmanager
from datetime import datetime, timedelta
from aiogram import types
from sqlalchemy import text
from .config import BONUS_AMOUNT, BONUS_COOLDOWN_HOURS, THIEF_BONUS_AMOUNT, POLICE_BONUS_AMOUNT, \
    PRIVILEGE_BONUS_COOLDOWN_HOURS
from database import get_db
from database.crud import UserRepository, DonateRepository

logger = logging.getLogger(__name__)


class BonusManager:
    """Класс для управления бонусами с автоматическим начислением"""

    def __init__(self):
        self._init_bonus_table()

    def _init_bonus_table(self):
        """Создает таблицу для бонусов если ее нет и добавляет недостающие колонки"""
        with self._db_session() as db:
            try:
                # Создаем таблицу если ее нет
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

                # Проверяем и добавляем недостающие колонки
                self._add_missing_columns(db)

                db.commit()
                logger.info("✅ Таблица user_bonuses создана/проверена")
            except Exception as e:
                logger.error(f"❌ Ошибка создания таблицы бонусов: {e}")
                db.rollback()

    def _add_missing_columns(self, db):
        """Добавляет недостающие колонки в таблицу"""
        try:
            # Проверяем существование колонки last_auto_bonus_time
            result = db.execute(text("""
                                     SELECT column_name
                                     FROM information_schema.columns
                                     WHERE table_name = 'user_bonuses'
                                       AND column_name = 'last_auto_bonus_time'
                                     """)).fetchone()

            if not result:
                db.execute(text("ALTER TABLE user_bonuses ADD COLUMN last_auto_bonus_time BIGINT DEFAULT 0"))
                logger.info("✅ Добавлена колонка last_auto_bonus_time")

        except Exception as e:
            logger.error(f"❌ Ошибка добавления колонок: {e}")
            raise

    @contextmanager
    def _db_session(self):
        """Контекстный менеджер для безопасной работы с БД"""
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

    async def process_automatic_bonuses(self):
        """Автоматическое начисление бонусов всем пользователям"""
        with self._db_session() as db:
            try:
                current_time = int(time.time())
                cooldown_seconds = BONUS_COOLDOWN_HOURS * 3600

                # Получаем всех пользователей из таблицы telegram_users
                users = db.execute(
                    text("SELECT telegram_id FROM telegram_users")
                ).fetchall()

                processed_count = 0
                bonus_given_count = 0

                logger.info(f"🔍 Начинаем обработку {len(users)} пользователей")

                for user_tuple in users:
                    user_id = user_tuple[0]
                    processed_count += 1

                    # Получаем информацию о бонусе пользователя
                    bonus_info = db.execute(
                        text("SELECT last_auto_bonus_time FROM user_bonuses WHERE telegram_id = :user_id"),
                        {"user_id": user_id}
                    ).fetchone()

                    last_bonus_time = bonus_info[0] if bonus_info else 0

                    # Проверяем, прошел ли кулдаун
                    if current_time - last_bonus_time >= cooldown_seconds:
                        # Получаем активные привилегии пользователя
                        user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                        purchased_ids = [p.item_id for p in user_purchases]
                        has_thief = 1 in purchased_ids
                        has_police = 2 in purchased_ids

                        logger.info(
                            f"🔍 Пользователь {user_id}: вор={has_thief}, полицейский={has_police}, покупки={purchased_ids}")

                        # Начисляем бонусы в зависимости от привилегий
                        user = UserRepository.get_user_by_telegram_id(db, user_id)
                        if user:
                            bonus_amount = 0
                            bonuses_claimed = []

                            # ОТЛАДКА: Логируем текущий баланс
                            old_balance = user.coins

                            # ВСЕ пользователи получают обычный бонус 50к
                            user.coins += BONUS_AMOUNT
                            bonus_amount += BONUS_AMOUNT
                            bonuses_claimed.append("daily")
                            logger.info(f"💰 Начислен обычный бонус {BONUS_AMOUNT} пользователю {user_id}")

                            # Дополнительные бонусы за привилегии
                            if has_thief:
                                user.coins += THIEF_BONUS_AMOUNT
                                bonus_amount += THIEF_BONUS_AMOUNT
                                bonuses_claimed.append("thief")
                                logger.info(f"💰 Начислен бонус Вора {THIEF_BONUS_AMOUNT} пользователю {user_id}")

                            if has_police:
                                user.coins += POLICE_BONUS_AMOUNT
                                bonus_amount += POLICE_BONUS_AMOUNT
                                bonuses_claimed.append("police")
                                logger.info(
                                    f"💰 Начислен бонус Полицейского {POLICE_BONUS_AMOUNT} пользователю {user_id}")

                            # Если нет платных привилегий, даем обычный бонус
                            if not has_thief and not has_police:
                                user.coins += BONUS_AMOUNT
                                bonus_amount += BONUS_AMOUNT
                                bonuses_claimed.append("daily")
                                logger.info(f"💰 Начислен обычный бонус {BONUS_AMOUNT} пользователю {user_id}")

                            # ОТЛАДКА: Логируем изменение баланса
                            new_balance = user.coins
                            logger.info(
                                f"💰 Баланс пользователя {user_id}: {old_balance} -> {new_balance} (+{bonus_amount})")

                            # Обновляем время последнего автоматического бонуса
                            db.execute(
                                text("""
                                     INSERT INTO user_bonuses (telegram_id, last_auto_bonus_time)
                                     VALUES (:user_id, :time) ON CONFLICT (telegram_id)
                                    DO
                                     UPDATE SET last_auto_bonus_time = EXCLUDED.last_auto_bonus_time
                                     """),
                                {"user_id": user_id, "time": current_time}
                            )

                            bonus_given_count += 1
                            logger.info(
                                f"✅ Автоматический бонус пользователю {user_id}: {bonus_amount} монет, типы: {bonuses_claimed}")
                        else:
                            logger.warning(f"⚠️ Пользователь {user_id} не найден в БД")
                    else:
                        # ОТЛАДКА: Логируем пользователей, которые еще не получили бонус
                        time_left = (cooldown_seconds - (current_time - last_bonus_time)) / 3600
                        logger.info(f"⏰ Пользователь {user_id} еще не готов к бонусу. Осталось: {time_left:.1f} часов")

                db.commit()
                logger.info(
                    f"🎯 Автоматические бонусы обработаны: {processed_count} пользователей, {bonus_given_count} получили бонусы")
                return bonus_given_count

            except Exception as e:
                logger.error(f"❌ Ошибка автоматического начисления бонусов: {e}")
                db.rollback()
                return 0

    async def check_expiring_privileges(self):
        """Проверяет истекающие привилегии и отправляет уведомления"""
        with self._db_session() as db:
            try:
                current_time = int(time.time())
                one_day_in_seconds = 24 * 3600

                logger.info("🔍 Начинаем проверку истекающих привилегий...")

                # Находим привилегии, которые истекают через 1 день
                expiring_soon = db.execute(
                    text("""
                         SELECT user_id, item_id, expires_at
                         FROM user_purchases
                         WHERE expires_at IS NOT NULL
                           AND expires_at BETWEEN :soon_start AND :soon_end
                         """),
                    {
                        "soon_start": datetime.fromtimestamp(current_time + one_day_in_seconds - 3600),
                        "soon_end": datetime.fromtimestamp(current_time + one_day_in_seconds + 3600)
                    }
                ).fetchall()

                # Находим привилегии, которые уже истекли
                expired = db.execute(
                    text("""
                         SELECT user_id, item_id
                         FROM user_purchases
                         WHERE expires_at IS NOT NULL
                           AND expires_at <= :current_time
                         """),
                    {"current_time": datetime.now()}
                ).fetchall()

                logger.info(f"📊 Найдено истекающих через 1 день: {len(expiring_soon)}")
                logger.info(f"📊 Найдено уже истекших: {len(expired)}")

                return expiring_soon, expired

            except Exception as e:
                logger.error(f"❌ Ошибка проверки истекающих привилегий: {e}")
                return [], []

    async def deactivate_expired_privileges(self, expired_privileges):
        """Деактивирует истекшие привилегии"""
        with self._db_session() as db:
            try:
                for privilege in expired_privileges:
                    user_id, item_id = privilege

                    # Удаляем истекшую привилегию
                    db.execute(
                        text("DELETE FROM donate_purchases WHERE user_id = :user_id AND item_id = :item_id"),
                        {"user_id": user_id, "item_id": item_id}
                    )

                    logger.info(f"🔚 Привилегия {item_id} удалена для пользователя {user_id}")

                db.commit()
                return len(expired_privileges)

            except Exception as e:
                logger.error(f"❌ Ошибка деактивации привилегий: {e}")
                db.rollback()
                return 0

    async def debug_user_privileges(self, user_id: int):
        """Отладочная информация о привилегиях пользователя"""
        with self._db_session() as db:
            try:
                # Проверяем все возможные таблицы с привилегиями
                debug_info = {
                    'user_id': user_id,
                    'donate_purchases': [],
                    'user_purchases': [],
                    'active_privileges': []
                }

                # Проверяем donate_purchases
                try:
                    donate_purchases = db.execute(text("""
                                                       SELECT item_id, item_name, expires_at
                                                       FROM donate_purchases
                                                       WHERE user_id = :user_id
                                                       """), {"user_id": user_id}).fetchall()
                    debug_info['donate_purchases'] = donate_purchases
                except Exception as e:
                    logger.warning(f"Таблица donate_purchases не найдена: {e}")

                # Проверяем user_purchases
                try:
                    user_purchases = db.execute(text("""
                                                     SELECT item_id, item_name, expires_at
                                                     FROM user_purchases
                                                     WHERE user_id = :user_id
                                                     """), {"user_id": user_id}).fetchall()
                    debug_info['user_purchases'] = user_purchases
                except Exception as e:
                    logger.warning(f"Таблица user_purchases не найдена: {e}")

                # Получаем активные привилегии через DonateRepository
                active_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                debug_info['active_privileges'] = [{
                    'item_id': p.item_id,
                    'item_name': p.item_name,
                    'expires_at': p.expires_at
                } for p in active_purchases]

                return debug_info

            except Exception as e:
                logger.error(f"❌ Ошибка отладки привилегий: {e}")
                return {'error': str(e)}

    # Методы для обратной совместимости с ручными запросами
    async def check_daily_bonus(self, user_id: int) -> Dict[str, Any]:
        """Проверяет доступность ежедневного бонуса (для ручного запроса)"""
        with self._db_session() as db:
            try:
                result = db.execute(
                    text("SELECT last_auto_bonus_time FROM user_bonuses WHERE telegram_id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()

                current_time = int(time.time())
                if not result:
                    return {"available": True, "hours_left": 0, "minutes_left": 0}

                last_bonus_time = result[0] or 0
                time_since_last_bonus = current_time - last_bonus_time
                cooldown_seconds = BONUS_COOLDOWN_HOURS * 3600

                if time_since_last_bonus >= cooldown_seconds:
                    return {"available": True, "hours_left": 0, "minutes_left": 0}
                else:
                    remaining_seconds = cooldown_seconds - time_since_last_bonus
                    hours_left = remaining_seconds // 3600
                    minutes_left = (remaining_seconds % 3600) // 60
                    return {
                        "available": False,
                        "hours_left": int(hours_left),
                        "minutes_left": int(minutes_left)
                    }
            except Exception as e:
                logger.error(f"❌ Ошибка проверки ежедневного бонуса: {e}")
                return {"available": True, "hours_left": 0, "minutes_left": 0}

    async def check_privilege_bonus(self, user_id: int) -> Dict[str, Any]:
        """Проверяет доступность бонусов за привилегии (для ручного запроса)"""
        with self._db_session() as db:
            try:
                # Получаем активные привилегии пользователя
                user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                purchased_ids = [p.item_id for p in user_purchases]
                has_thief = 1 in purchased_ids
                has_police = 2 in purchased_ids

                # Используем ту же логику, что и для автоматического бонуса
                bonus_info = await self.check_daily_bonus(user_id)

                return {
                    "available": bonus_info["available"],
                    "hours_left": bonus_info["hours_left"],
                    "minutes_left": bonus_info["minutes_left"],
                    "has_thief": has_thief,
                    "has_police": has_police
                }

            except Exception as e:
                logger.error(f"❌ Ошибка проверки бонусов за привилегии: {e}")
                return {
                    "available": False,
                    "hours_left": 0,
                    "minutes_left": 0,
                    "has_thief": False,
                    "has_police": False
                }