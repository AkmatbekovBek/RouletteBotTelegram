# handlers/police/service.py
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from database import get_db
from database.crud import PoliceRepository, ShopRepository


class PoliceService:
    MAX_ARREST_MINUTES = 1440  # 24 часа
    MIN_ARREST_MINUTES = 1
    DEFAULT_ARREST_MINUTES = 180  # 3 часа
    POLICE_COOLDOWN_HOURS = 3
    POLICE_PRIVILEGE_ID = 2
    THIEF_PRIVILEGE_ID = 1

    @staticmethod
    def parse_arrest_time(text: str) -> int:
        """Парсит 'арест 1д 2ч 30м' → минуты (макс. 1440)"""
        text = text.lower()
        total = 0
        patterns = [
            (r'(\d+)\s*д[ень]*', 1440),
            (r'(\d+)\s*ч[ас]*', 60),
            (r'(\d+)\s*м[ин]*', 1),
        ]
        for pat, mult in patterns:
            for m in re.finditer(pat, text):
                total += int(m.group(1)) * mult
        if total == 0:
            return PoliceService.DEFAULT_ARREST_MINUTES
        return max(PoliceService.MIN_ARREST_MINUTES, min(total, PoliceService.MAX_ARREST_MINUTES))

    @staticmethod
    def check_police_permission(user_id: int) -> bool:
        db = next(get_db())
        try:
            purchases = ShopRepository.get_user_purchases(db, user_id)
            return PoliceService.POLICE_PRIVILEGE_ID in purchases
        finally:
            db.close()

    @staticmethod
    def check_thief_permission(user_id: int) -> bool:
        db = next(get_db())
        try:
            purchases = ShopRepository.get_user_purchases(db, user_id)
            return PoliceService.THIEF_PRIVILEGE_ID in purchases
        finally:
            db.close()

    @staticmethod
    def check_police_cooldown(police_id: int) -> Tuple[bool, Optional[datetime]]:
        db = next(get_db())
        try:
            last = PoliceRepository.get_last_arrest_by_police(db, police_id)
            if not last:
                return True, None
            end = last.arrested_at + timedelta(hours=PoliceService.POLICE_COOLDOWN_HOURS)
            now = datetime.now()
            return now >= end, (end if now < end else None)
        finally:
            db.close()

    @staticmethod
    def is_user_arrested(user_id: int) -> bool:
        db = next(get_db())
        try:
            arrest = PoliceRepository.get_user_arrest(db, user_id)
            if not arrest:
                return False
            if arrest.release_time <= datetime.now():
                PoliceRepository.unarrest_user(db, user_id)
                db.commit()
                return False
            return True
        finally:
            db.close()

    @staticmethod
    def arrest_user(police_id: int, thief_id: int, minutes: int) -> Tuple[bool, str]:
        db = next(get_db())
        try:
            if PoliceService.is_user_arrested(thief_id):
                return False, "⚠️ Пользователь уже арестован!"

            release = datetime.now() + timedelta(minutes=minutes)
            PoliceRepository.arrest_user(db, thief_id, police_id, release)
            db.commit()
            return True, f"✅ Арест на {minutes} мин"
        except Exception as e:
            db.rollback()
            return False, f"❌ Ошибка БД: {e}"
        finally:
            db.close()

    @staticmethod
    def _get_user_arrest_raw(db, user_id: int):
        """Получает запись об аресте без очистки (для check_arrest)"""
        from database.models import UserArrest
        try:
            return db.query(UserArrest).filter(UserArrest.user_id == user_id).first()
        except:
            return None