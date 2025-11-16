# handlers/thief/service.py
from datetime import datetime, timedelta
from typing import Optional, Tuple
from decimal import Decimal
from database import get_db
from database.crud import ShopRepository, UserRepository


class ThiefService:
    MAX_DAILY = 3
    ROB_PERCENT = Decimal('0.1')  # ← БЫЛО 0.1 (float), СТАЛО Decimal('0.1')
    THIEF_PRIVILEGE_ID = 1
    POLICE_PRIVILEGE_ID = 2

    @staticmethod
    def check_thief_permission(user_id: int) -> bool:
        db = next(get_db())
        try:
            purchases = ShopRepository.get_user_purchases(db, user_id)
            return ThiefService.THIEF_PRIVILEGE_ID in purchases
        finally:
            db.close()

    @staticmethod
    def is_police(user_id: int) -> bool:
        db = next(get_db())
        try:
            purchases = ShopRepository.get_user_purchases(db, user_id)
            return ThiefService.POLICE_PRIVILEGE_ID in purchases
        finally:
            db.close()

    @staticmethod
    def is_user_arrested(user_id: int) -> bool:
        from handlers.police.service import PoliceService
        return PoliceService.is_user_arrested(user_id)

    @staticmethod
    def _reset_rob_if_needed(user):
        now = datetime.utcnow()
        reset_time = user.last_robbery_reset or now
        if (now - reset_time).total_seconds() >= 86400:
            user.robberies_today = 0
            user.last_robbery_reset = now
            return True
        return False

    @staticmethod
    def rob_user(thief_id: int, victim_id: int) -> Tuple[bool, str, Optional[float]]:
        db = next(get_db())
        try:
            thief = UserRepository.get_user_by_telegram_id(db, thief_id)
            victim = UserRepository.get_user_by_telegram_id(db, victim_id)
            print(f"🔍 [DEBUG] thief type: {type(thief)}")
            if thief:
                print(f"🔍 [DEBUG] robberies_today = {getattr(thief, 'robberies_today', 'MISSING')}")
                print(f"🔍 [DEBUG] has attr 'last_robbery_reset': {hasattr(thief, 'last_robbery_reset')}")
            else:
                print("🔍 [DEBUG] thief is None!")
            if not thief or not victim:
                return False, "❌ Пользователь не найден", None

            if not ThiefService.check_thief_permission(thief_id):
                return False, "🎭 Нужна привилегия «Вор в законе»", None

            if thief_id == victim_id:
                return False, "🚫 Нельзя грабить себя", None

            if ThiefService.is_police(victim_id):
                return False, "🚓 Нельзя грабить полицейского!", None

            if ThiefService.is_user_arrested(thief_id):
                return False, "🔒 Вы арестованы!", None

            ThiefService._reset_rob_if_needed(thief)
            if thief.robberies_today >= ThiefService.MAX_DAILY:
                return False, f"⏳ Лимит: {ThiefService.MAX_DAILY} раз/день", None

            amount = int(victim.coins * ThiefService.ROB_PERCENT)
            if amount <= 0:
                return False, "📉 У жертвы нет денег", None

            victim.coins -= amount
            thief.coins += amount
            thief.robberies_today += 1
            db.commit()

            return True, f"💰 Украдено {amount}₽", amount


        except Exception as e:
            db.rollback()
            return False, f"❌ Ошибка: {e}", None
        finally:
            db.close()