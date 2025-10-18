from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from typing import Tuple, Optional, Dict
from database import get_db
from database.crud import ShopRepository, RouletteLimitRepository
import database.models as models


class RouletteLimitManager:
    def __init__(self):
        self.limit_per_day = 30  # Лимит прокрутов в день

    def _get_today_date(self) -> date:
        """Возвращает сегодняшнюю дату"""
        return date.today()

    def has_roulette_limit_removed_in_chat(self, user_id: int, chat_id: int) -> bool:
        """Проверяет, купил ли пользователь снятие лимита рулетки для конкретного чата"""
        db = next(get_db())
        try:
            # Проверяем покупку снятия лимита (ID 5) в конкретном чате
            has_limit_removed = ShopRepository.has_user_purchased_in_chat(db, user_id, 5, chat_id)

            if has_limit_removed:
                print(f"✅ Пользователь {user_id} купил снятие лимита в чате {chat_id}")
            else:
                print(f"❌ Пользователь {user_id} НЕ имеет снятия лимита в чате {chat_id}")

            return has_limit_removed

        except Exception as e:
            print(f"❌ Ошибка проверки снятия лимита для чата: {e}")
            return False
        finally:
            db.close()

    def _init_user_chat_limit(self, db: Session, user_id: int, chat_id: int):
        """Инициализирует запись лимита для пользователя в конкретном чате если её нет"""
        try:
            today = self._get_today_date()

            # Используем CRUD метод для создания/получения лимита
            RouletteLimitRepository.get_or_create_limit(db, user_id, chat_id, today)
            print(f"✅ Инициализирован лимит для пользователя {user_id} в чате {chat_id} на {today}")

        except Exception as e:
            print(f"❌ Ошибка инициализации лимита для чата: {e}")
            db.rollback()

    def get_today_spin_count_in_chat(self, user_id: int, chat_id: int) -> int:
        """Возвращает количество прокрутов пользователя за сегодня в конкретном чате"""
        db = next(get_db())
        try:
            today = self._get_today_date()

            result = db.query(models.RouletteLimit).filter(
                models.RouletteLimit.user_id == user_id,
                models.RouletteLimit.chat_id == chat_id,
                models.RouletteLimit.date == today
            ).first()

            spin_count = result.spin_count if result else 0
            # УБЕРИТЕ ЛОГ ЧТОБЫ ИЗБЕЖАТЬ ДУБЛИРОВАНИЯ
            # print(f"📊 Пользователь {user_id} в чате {chat_id}: {spin_count} прокрутов сегодня")
            return spin_count

        except Exception as e:
            print(f"❌ Ошибка получения количества прокрутов: {e}")
            return 0
        finally:
            db.close()

    def can_spin_roulette_in_chat(self, user_id: int, chat_id: int) -> Tuple[bool, int]:
        """
        Проверяет, может ли пользователь крутить рулетку в конкретном чате
        Возвращает (может_ли_крутить, осталось_прокрутов)
        """
        # Если пользователь купил снятие лимита - всегда разрешаем для всех чатов
        if self.has_roulette_limit_removed_in_chat(user_id, chat_id):
            return True, -1  # -1 означает безлимит

        today_spins = self.get_today_spin_count_in_chat(user_id, chat_id)

        # Проверяем не превышен ли лимит
        if today_spins >= self.limit_per_day:
            return False, 0

        return True, self.limit_per_day - today_spins

    def record_spin_in_chat(self, user_id: int, chat_id: int) -> bool:
        """
        Записывает прокрут рулетки в конкретном чате
        Возвращает True если запись успешна, False если лимит превышен
        """
        # Если пользователь купил снятие лимита - не записываем и всегда разрешаем
        if self.has_roulette_limit_removed_in_chat(user_id, chat_id):
            print(f"🎰 Пользователь {user_id} с безлимитом в чате {chat_id} - прокрут разрешен")
            return True

        can_spin, remaining = self.can_spin_roulette_in_chat(user_id, chat_id)
        if not can_spin:
            print(f"❌ Пользователь {user_id} превысил лимит в чате {chat_id}")
            return False

        db = next(get_db())
        try:
            # Используем CRUD метод для увеличения счетчика
            success = RouletteLimitRepository.increment_spin_count(db, user_id, chat_id)

            if success:
                new_count = self.get_today_spin_count_in_chat(user_id, chat_id)
                print(f"✅ Записан прокрут для пользователя {user_id} в чате {chat_id}. Всего сегодня: {new_count}")
            else:
                print(f"❌ Ошибка записи прокрута для пользователя {user_id} в чате {chat_id}")

            return success

        except Exception as e:
            print(f"❌ Ошибка записи прокрута для чата: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_spin_info_for_chat(self, user_id: int, chat_id: int) -> str:
        """Возвращает информацию о лимитах пользователя в конкретном чате"""
        if self.has_roulette_limit_removed_in_chat(user_id, chat_id):
            return "🔐 Лимит рулетки снят в этом чате! Вы можете играть без ограничений!"

        can_spin, remaining = self.can_spin_roulette_in_chat(user_id, chat_id)
        today_spins = self.get_today_spin_count_in_chat(user_id, chat_id)

        if can_spin:
            if remaining > 0:
                return f"🎰 В этом чате осталось прокрутов: {remaining}/{self.limit_per_day} (использовано: {today_spins})"
            else:
                return f"🎰 Лимит рулетки в этом чате: {self.limit_per_day} прокрутов в день"
        else:
            return f"❌ Лимит рулетки в этом чате исчерпан! Осталось прокрутов: 0/{self.limit_per_day}"

    def get_remaining_spins_in_chat(self, user_id: int, chat_id: int) -> int:
        """Возвращает количество оставшихся прокрутов в конкретном чате"""
        if self.has_roulette_limit_removed_in_chat(user_id, chat_id):
            return -1  # Безлимит

        can_spin, remaining = self.can_spin_roulette_in_chat(user_id, chat_id)
        return remaining if can_spin else 0

    def get_user_chat_limit_stats(self, user_id: int, chat_id: int) -> Dict:
        """Возвращает полную статистику лимитов пользователя в чате"""
        db = next(get_db())
        try:
            # Проверяем существует ли метод в репозитории
            if hasattr(RouletteLimitRepository, 'get_user_chat_limit_stats'):
                stats = RouletteLimitRepository.get_user_chat_limit_stats(db, user_id, chat_id)
            else:
                # Если метода нет, создаем базовую статистику
                stats = {
                    'today_spins': self.get_today_spin_count_in_chat(user_id, chat_id),
                    'total_days_in_chat': 0,
                    'total_spins_in_chat': 0
                }

            stats.update({
                'has_limit_removed': self.has_roulette_limit_removed_in_chat(user_id, chat_id),
                'remaining_spins': self.get_remaining_spins_in_chat(user_id, chat_id),
                'limit_per_day': self.limit_per_day
            })
            return stats

        except Exception as e:
            print(f"❌ Ошибка получения статистики лимитов для чата: {e}")
            return {
                'has_limit_removed': self.has_roulette_limit_removed_in_chat(user_id, chat_id),
                'remaining_spins': self.get_remaining_spins_in_chat(user_id, chat_id),
                'limit_per_day': self.limit_per_day,
                'today_spins': 0,
                'total_days_in_chat': 0,
                'total_spins_in_chat': 0
            }
        finally:
            db.close()

    def cleanup_old_limits(self, db: Session):
        """Очищает старые записи лимитов (старше 7 дней)"""
        try:
            deleted_count = RouletteLimitRepository.cleanup_old_limits(db)
            print(f"✅ Очищены старые записи лимитов: удалено {deleted_count} записей")
            return deleted_count
        except Exception as e:
            print(f"❌ Ошибка очистки старых лимитов: {e}")
            return 0

    def can_spin_roulette_in_chat(self, user_id: int, chat_id: int) -> Tuple[bool, int]:
        """
        Проверяет, может ли пользователь крутить рулетку в конкретном чате
        Возвращает (может_ли_крутить, осталось_прокрутов)
        """
        print(f"🔍 Проверка лимита: user_id={user_id}, chat_id={chat_id}")

        # Если пользователь купил снятие лимита - всегда разрешаем для всех чатов
        has_limit_removed = self.has_roulette_limit_removed_in_chat(user_id, chat_id)
        if has_limit_removed:
            print(f"✅ Пользователь {user_id} имеет безлимит в чате {chat_id}")
            return True, -1

        today_spins = self.get_today_spin_count_in_chat(user_id, chat_id)
        print(f"📊 Сегодняшние прокруты: {today_spins}")

        # Проверяем не превышен ли лимит
        if today_spins >= self.limit_per_day:
            print(f"❌ Лимит превышен: {today_spins}/{self.limit_per_day}")
            return False, 0

        remaining = self.limit_per_day - today_spins
        print(f"✅ Можно крутить, осталось: {remaining}")
        return True, remaining

# Глобальный экземпляр менеджера лимитов
roulette_limit_manager = RouletteLimitManager()