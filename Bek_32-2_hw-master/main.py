# main.py
import asyncio
import logging
import signal
import sys
from datetime import time
import time

from sqlalchemy import text

from aiogram import executor, Dispatcher
from aiogram.types import AllowedUpdates
from middlewares.bot_ban_middleware import BotBanMiddleware
from middlewares.throttling import setup_throttling

from handlers.cleanup_scheduler import CleanupScheduler
from config import dp
from database import engine, SessionLocal
from database.models import Base

# Импорты обработчиков
HANDLERS = [
    ("start", "register_start_handler"),
    ("admin", "register_admin_handlers"),
    ("mute_ban", "register_mute_ban_handlers"),
    ("shop", "register_shop_handlers"),
    ("donate", "register_donate_handlers"),
    ("callback", "register_callback_handlers"),
    ("reference", "register_reference_handlers"),
    ("transfer", "register_transfer_handlers"),
    ("history_service", "register_history_handlers"),
    ("record", "register_record_handlers"),
    ("gifts", "register_gift_handlers"),
    ("marriage_handler", "register_marriage_handlers"),

    ("roulette", "register_roulette_handlers"),
    ("police_handler", "register_police_handlers"),
    ("thief_handler", "register_thief_handlers"),
    ("bot_search_handler", "register_bot_search_handlers"),
    ("chat_handlers", "register_chat_handlers"),
    ("bot_stop_handler", "register_bot_stop_handlers"),
]

# Список команд для антифлуда
THROTTLED_COMMANDS = [
    'start',    # /start
    'help',     # /help
    'menu',     # /menu
    'profile',  # /profile
    'settings', # /settings
    'б',        # текстовые команды
    'Б',        # текстовые команды
    'профиль',  # текстовые команды
    'рулетка',  # текстовые команды
    'донат',    # текстовые команды
    'подарки',  # текстовые команды
    'магазин',  # текстовые команды
    'ссылки',   # текстовые команды
    'баланс',   # текстовые команды
    'топ',      # текстовые команды
    'перевод',  # текстовые команды
]

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные
cleanup_scheduler = None
mute_ban_manager = None


def setup_database() -> bool:
    """Настройка базы данных (синхронная)"""
    try:
        # Создаем таблицы
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Все таблицы базы данных созданы")

        # Проверяем подключение (синхронно) с использованием text()
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db.commit()
            logger.info("✅ Подключение к базе данных установлено")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Ошибка проверки подключения к БД: {e}")
            return False
        finally:
            db.close()

    except Exception as e:
        logger.error(f"❌ Ошибка настройки БД: {e}")
        return False


def cleanup_old_limits() -> None:
    """Очистка старых записей лимитов (синхронная)"""
    try:
        from database.crud import TransferLimitRepository

        db = SessionLocal()
        try:
            deleted_count = TransferLimitRepository.clean_old_transfers(db)
            if deleted_count > 0:
                logger.info(f"✅ Очищено {deleted_count} старых записей лимитов")
            else:
                logger.info("✅ Старые записи лимитов не найдены")
        except Exception as e:
            logger.error(f"❌ Ошибка при очистке лимитов: {e}")
            db.rollback()
        finally:
            db.close()

    except Exception as e:
        logger.error(f"❌ Ошибка инициализации очистки лимитов: {e}")


async def setup_middleware_first():
    """Настройка middleware ДО регистрации обработчиков - ЭТО ВАЖНО!"""
    try:
        from middlewares.auto_register_middleware import AutoRegisterMiddleware

        logger.info("🛠️ Настройка middleware...")

        # 1. СНАЧАЛА регистрируем ThrottlingMiddleware
        setup_throttling(
            dp,
            throttled_commands=THROTTLED_COMMANDS,
            limit=2  # 2 секунды для тестирования
        )
        logger.info(f"✅ ThrottlingMiddleware зарегистрирован для {len(THROTTLED_COMMANDS)} команд")

        # 2. Затем AutoRegisterMiddleware
        dp.middleware.setup(AutoRegisterMiddleware())
        logger.info("✅ AutoRegisterMiddleware зарегистрирован")

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка настройки middleware: {e}")
        return False


def register_all_handlers():
    """Регистрация всех обработчиков ПОСЛЕ middleware"""
    logger.info("🔄 Регистрация обработчиков...")

    registered_handlers = set()
    global mute_ban_manager

    for module_name, register_func_name in HANDLERS:
        try:
            module = __import__(f"handlers.{module_name}", fromlist=[register_func_name])
            register_func = getattr(module, register_func_name)

            # Для mute_ban сохраняем менеджер для использования в middleware
            if module_name == "mute_ban":
                mute_ban_manager = register_func(dp)
            else:
                register_func(dp)

            registered_handlers.add(module_name)
            logger.info(f"✅ {module_name} обработчики зарегистрированы")

        except (ImportError, AttributeError) as e:
            logger.error(f"❌ Ошибка регистрации {module_name}: {e}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при регистрации {module_name}: {e}")

    logger.info(f"✅ Все обработчики зарегистрированы. Всего: {len(registered_handlers)}")
    return mute_ban_manager


async def setup_bot_ban_middleware(mute_ban_manager):
    """Настройка BotBanMiddleware после получения менеджера"""
    if mute_ban_manager:
        bot_ban_middleware = BotBanMiddleware(mute_ban_manager)
        dp.middleware.setup(bot_ban_middleware)

        # Устанавливаем связь между менеджером и middleware
        mute_ban_manager.bot_ban_manager.set_middleware(bot_ban_middleware)

        logger.info("✅ BotBanMiddleware зарегистрирован")
        return True
    else:
        logger.warning("⚠️ BotBanMiddleware не зарегистрирован - mute_ban_manager не найден")
        return False


async def start_cleanup_tasks(mute_ban_manager):
    """Запуск задач очистки и проверки банов"""
    try:
        # Запускаем планировщик очистки БД
        global cleanup_scheduler
        cleanup_scheduler = CleanupScheduler()
        asyncio.create_task(cleanup_scheduler.start_daily_cleanup())
        logger.info("✅ Планировщик очистки БД запущен")

        # Запускаем задачи проверки мутов/банов если есть менеджер
        if mute_ban_manager:
            mute_ban_manager.start_cleanup_tasks(dp.bot)
            logger.info("✅ Задачи проверки мутов/банов запущены")

            # Восстанавливаем активные муты после перезапуска
            await mute_ban_manager.restore_mutes_after_restart(dp.bot)
            logger.info("✅ Активные муты восстановлены после перезапуска")

    except Exception as e:
        logger.error(f"❌ Ошибка запуска задач очистки: {e}")
        raise


async def on_startup(_):
    """Действия при запуске бота - ПРАВИЛЬНЫЙ ПОРЯДОК!"""
    logger.info("🚀 Запуск бота...")

    # 1. Синхронные операции с БД
    logger.info("📊 Настройка базы данных...")
    if not setup_database():
        raise RuntimeError("Не удалось настроить базу данных")

    logger.info("🧹 Очистка старых данных...")
    cleanup_old_limits()

    # 2. СНАЧАЛА настраиваем middleware (кроме BotBanMiddleware)
    if not await setup_middleware_first():
        raise RuntimeError("Не удалось настроить middleware")

    # 3. ПОТОМ регистрируем обработчики
    logger.info("📝 Регистрация обработчиков...")
    mute_ban_manager = register_all_handlers()

    # 4. Теперь настраиваем BotBanMiddleware (нужен mute_ban_manager)
    await setup_bot_ban_middleware(mute_ban_manager)

    # 5. Запуск задач очистки
    logger.info("⏰ Запуск задач очистки...")
    await start_cleanup_tasks(mute_ban_manager)

    logger.info("✅ Бот успешно запущен")


async def on_shutdown(dp: Dispatcher):
    """Корректное завершение работы с улучшенной обработкой ошибок"""
    logger.info("🛑 Завершение работы бота...")

    try:
        # Останавливаем планировщик очистки
        global cleanup_scheduler
        if cleanup_scheduler:
            try:
                await cleanup_scheduler.stop()
                logger.info("✅ Планировщик очистки остановлен")
            except Exception as e:
                logger.error(f"❌ Ошибка остановки планировщика: {e}")

        # Останавливаем задачи мутов/банов
        global mute_ban_manager
        if mute_ban_manager:
            try:
                await mute_ban_manager.stop_cleanup_tasks()
                logger.info("✅ Задачи мутов/банов остановлены")
            except Exception as e:
                logger.error(f"❌ Ошибка остановки задач мутов/банов: {e}")

        # Закрываем соединения с БД
        try:
            from database import engine
            engine.dispose()
            logger.info("✅ Соединения с БД закрыты")
        except Exception as e:
            logger.error(f"❌ Ошибка закрытия БД: {e}")

        # Останавливаем диспетчер
        try:
            await dp.storage.close()
            await dp.storage.wait_closed()
            logger.info("✅ Хранилище диспетчера закрыто")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка закрытия хранилища: {e}")

    except Exception as e:
        logger.error(f"💥 Критическая ошибка при завершении: {e}")
    finally:
        logger.info("✅ Бот остановлен")


def main():
    """Основная функция запуска бота"""

    # Регистрируем обработчики сигналов для корректного завершения
    def signal_handler(signum, frame):
        """Улучшенный обработчик сигналов"""
        logger.info(f"📞 Получен сигнал {signum}. Завершение работы...")

        # Даем время для корректного завершения
        import threading
        def shutdown():
            import time
            time.sleep(1)  # Даем время для завершения операций
            sys.exit(0)

        threading.Thread(target=shutdown).start()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    restart_count = 0
    max_restarts = 5
    restart_delays = [2, 5, 10, 30, 60]

    while restart_count < max_restarts:
        try:
            logger.info(f"🔄 Запуск бота (попытка {restart_count + 1}/{max_restarts})")

            # Используем стандартный запуск aiogram с увеличенным relax
            executor.start_polling(
                dp,
                skip_updates=True,
                on_startup=on_startup,
                on_shutdown=on_shutdown,
                timeout=60,
                allowed_updates=AllowedUpdates.all(),
                relax=0.5  # Увеличено с 0.1 до 0.5 для снижения нагрузки
            )

            # Если бот завершился без ошибки, выходим
            logger.info("Бот завершил работу")
            break

        except KeyboardInterrupt:
            logger.info("⏹️ Остановка по запросу пользователя")
            break

        except Exception as e:
            restart_count += 1
            logger.critical(f"❌ Критическая ошибка (перезапуск {restart_count}/{max_restarts}): {e}", exc_info=True)

            if restart_count < max_restarts:
                delay_index = min(restart_count - 1, len(restart_delays) - 1)
                delay = restart_delays[delay_index]

                logger.info(f"🔄 Перезапуск через {delay} секунд...")
                time.sleep(delay)
            else:
                logger.error("🚨 Достигнут лимит перезапусков. Завершение работы.")
                break


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("👋 До свидания!")
    except Exception as e:
        logger.critical(f"💥 Фатальная ошибка: {e}", exc_info=True)
        sys.exit(1)