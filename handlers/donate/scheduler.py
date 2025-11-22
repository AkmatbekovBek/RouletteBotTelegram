# handlers/donate/scheduler.py

import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot
from .bonus import BonusManager
from .config import SUPPORT_USERNAME

logger = logging.getLogger(__name__)


class DonateScheduler:
    """Планировщик для автоматических задач доната"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.bonus_manager = BonusManager()
        self.is_running = False

    async def start_scheduler(self):
        """Запускает планировщик автоматических задач"""
        self.is_running = True
        logger.info("🚀 Запуск планировщика донат-задач")

        # Тестовый режим: запускаем сразу при старте
        await self._process_daily_tasks()

        while self.is_running:
            try:
                # В тестовом режиме проверяем каждые 5 минут
                await asyncio.sleep(300)
                await self._process_daily_tasks()

            except Exception as e:
                logger.error(f"❌ Ошибка в планировщике: {e}")
                await asyncio.sleep(300)

    async def stop_scheduler(self):
        """Останавливает планировщик"""
        self.is_running = False
        logger.info("🛑 Остановка планировщика донат-задач")

    async def _process_daily_tasks(self):
        """Выполняет ежедневные задачи"""
        try:
            logger.info("📅 Выполнение ежедневных задач")

            # 1. Начисляем автоматические бонусы
            bonus_count = await self.bonus_manager.process_automatic_bonuses()
            logger.info(f"🎁 Начислено автоматических бонусов: {bonus_count}")

            # 2. Проверяем истекающие привилегии
            expiring_soon, expired = await self.bonus_manager.check_expiring_privileges()

            # 3. Отправляем уведомления о скором истечении
            for privilege in expiring_soon:
                user_id, item_id, expires_at = privilege
                await self._send_expiration_warning(user_id, item_id, expires_at)

            # 4. Деактивируем истекшие привилегии
            if expired:
                deactivated_count = await self.bonus_manager.deactivate_expired_privileges(expired)
                logger.info(f"🔚 Деактивировано привилегий: {deactivated_count}")

                # Отправляем уведомления об истечении
                for privilege in expired:
                    user_id, item_id = privilege
                    await self._send_privilege_expired(user_id, item_id)

        except Exception as e:
            logger.error(f"❌ Ошибка выполнения ежедневных задач: {e}")

    async def _send_expiration_warning(self, user_id: int, item_id: int, expires_at: int):
        """Отправляет предупреждение об истечении привилегии"""
        try:
            privilege_names = {
                1: "👑 Вор в законе",
                2: "👮‍♂️ Полицейский",
                3: "🔐 Снятие лимита перевода"
            }

            privilege_name = privilege_names.get(item_id, "Привилегия")

            message = (
                f"⚠️ <b>Внимание!</b>\n"
                f"Ваш статус <b>{privilege_name}</b> истекает завтра!\n"
                f"Чтобы продлить, обратитесь к @{SUPPORT_USERNAME}"
            )

            await self.bot.send_message(user_id, message, parse_mode="HTML")
            logger.info(f"📢 Отправлено предупреждение об истечении пользователю {user_id}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки предупреждения пользователю {user_id}: {e}")

    async def _send_privilege_expired(self, user_id: int, item_id: int):
        """Отправляет уведомление об истечении привилегии"""
        try:
            privilege_names = {
                1: "👑 Вор в законе",
                2: "👮‍♂️ Полицейский",
                3: "🔐 Снятие лимита перевода"
            }

            privilege_name = privilege_names.get(item_id, "Привилегия")

            message = (
                f"🔚 <b>Статус истек</b>\n"
                f"Ваш статус <b>{privilege_name}</b> закончился.\n"
                f"Вы возвращены к обычному бонусу.\n"
                f"Для покупки: @{SUPPORT_USERNAME}"
            )

            await self.bot.send_message(user_id, message, parse_mode="HTML")
            logger.info(f"📢 Отправлено уведомление об истечении пользователю {user_id}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления об истечении пользователю {user_id}: {e}")