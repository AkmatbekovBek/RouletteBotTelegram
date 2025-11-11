# services/cleanup_scheduler.py
import asyncio
import logging
import pytz
from datetime import datetime, time
from contextlib import contextmanager
from database import SessionLocal, get_db
from database.crud import TransferLimitRepository, DonateRepository, PoliceRepository

logger = logging.getLogger(__name__)


class CleanupScheduler:
    """Планировщик для ежедневной очистки данных"""

    def __init__(self):
        self.kg_tz = pytz.timezone('Asia/Bishkek')
        self._is_running = False
        self._cleanup_task = None

    @contextmanager
    def get_db_session(self):
        """Контекстный менеджер для работы с сессией БД"""
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    async def start_daily_cleanup(self):
        """Запускает ежедневную очистку в 00:00 по времени Кыргызстана"""
        self._is_running = True

        logger.info("🔄 Планировщик очистки запущен")

        try:
            while self._is_running:
                now = datetime.now(self.kg_tz)

                # Вычисляем время до следующей полуночи
                target_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if now >= target_time:
                    target_time = target_time.replace(day=target_time.day + 1)

                wait_seconds = (target_time - now).total_seconds()

                # Проверяем каждую минуту, не остановлен ли планировщик
                check_interval = min(wait_seconds, 60)  # Не более 60 секунд за раз

                logger.info(f"⏰ Следующая очистка через {wait_seconds:.0f} секунд ({wait_seconds / 3600:.1f} часов)")

                # Ждем с возможностью прерывания
                waited = 0
                while waited < wait_seconds and self._is_running:
                    await asyncio.sleep(min(check_interval, wait_seconds - waited))
                    waited += check_interval

                if self._is_running:
                    await self.run_cleanup()

        except asyncio.CancelledError:
            logger.info("⏹️ Планировщик очистки остановлен")
            raise
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в планировщике очистки: {e}")
            raise

    async def cleanup_expired_privileges(self):
        """Очищает просроченные привилегии"""
        db = next(get_db())
        try:
            from sqlalchemy import text
            result = db.execute(
                text("""
                     DELETE
                     FROM user_purchases
                     WHERE expires_at IS NOT NULL
                       AND expires_at < :now
                     """),
                {"now": datetime.now()}
            )
            db.commit()

            if result.rowcount > 0:
                self.logger.info(f"Cleaned up {result.rowcount} expired privileges")

        except Exception as e:
            self.logger.error(f"Error cleaning expired privileges: {e}")
            db.rollback()
        finally:
            db.close()

    async def cleanup_expired_arrests_periodically(self):
        """Периодическая очистка истекших арестов"""
        while True:
            try:
                db = next(get_db())
                cleaned = PoliceRepository.cleanup_expired_arrests(db)
                db.commit()
                if cleaned > 0:
                    logger.info(f"Auto-cleaned {cleaned} expired arrests")
            except Exception as e:
                logger.error(f"Error in auto-cleaning arrests: {e}")
            finally:
                await asyncio.sleep(3600)  # Каждый час

    async def run_cleanup(self):
        """Выполняет очистку данных"""
        try:
            with self.get_db_session() as db:
                # Очищаем старые трансферы
                deleted_transfers = TransferLimitRepository.clean_old_transfers(db)

                # Очищаем истекшие покупки доната
                expired_purchases = DonateRepository.cleanup_expired_purchases(db)

                current_time = datetime.now(self.kg_tz).strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"✅ Ежедневная очистка выполнена в {current_time}")
                logger.info(f"📊 Удалено записей трансферов: {deleted_transfers}")
                logger.info(f"📊 Удалено истекших покупок: {expired_purchases}")

                return {
                    'transfers': deleted_transfers,
                    'purchases': expired_purchases
                }

        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении очистки: {e}")
            return {'transfers': 0, 'purchases': 0}

    async def run_manual_cleanup(self):
        """Ручной запуск очистки (для админов)"""
        try:
            deleted_count = await self.run_cleanup()
            return f"✅ Очистка выполнена успешно. Удалено записей: {deleted_count}"
        except Exception as e:
            logger.error(f"❌ Ошибка при ручной очистке: {e}")
            return f"❌ Ошибка при очистке: {e}"

    async def stop(self):
        """Корректная остановка планировщика"""
        self._is_running = False
        logger.info("🛑 Остановка планировщика очистки...")

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Планировщик очистки остановлен")

    async def start(self):
        """Запуск планировщика и сохранение задачи"""
        self._cleanup_task = asyncio.create_task(self.start_daily_cleanup())
        return self._cleanup_task

    def is_running(self):
        """Проверка, работает ли планировщик"""
        return self._is_running and self._cleanup_task and not self._cleanup_task.done()