# main.py
import asyncio
import logging
import signal
import sys

from sqlalchemy import text

from aiogram import executor, Dispatcher
from aiogram.types import AllowedUpdates

from handlers.gifts import ensure_gifts_on_startup
from middlewares.bot_ban_middleware import BotBanMiddleware
from middlewares.throttling import setup_throttling

from handlers.cleanup_scheduler import CleanupScheduler
from config import dp
from database import engine, SessionLocal
from database.models import Base

# ✅ ДОБАВЛЕНО: police и thief — последние, чтобы не перекрывались
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
    # ✅ ВАЖНО: police и thief — ПОСЛЕДНИМИ!
    ("police", "register_police_handlers"),
    ("thief", "register_thief_handlers"),
    ("bot_search_handler", "register_bot_search_handlers"),
    ("chat_handlers", "register_chat_handlers"),
    ("bot_stop_handler", "register_bot_stop_handlers"),
]

# Список команд для антифлуда
THROTTLED_COMMANDS = [
    'start', 'help', 'menu', 'profile', 'settings',
    'б', 'Б', 'профиль', 'рулетка', 'донат', 'подарки',
    'магазин', 'ссылки', 'баланс', 'топ', 'перевод',
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
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Все таблицы базы данных созданы")

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

        # 1. СНАЧАЛА регистрируем AutoRegisterMiddleware (самый первый!)
        dp.middleware.setup(AutoRegisterMiddleware())
        logger.info("✅ AutoRegisterMiddleware зарегистрирован")

        # 2. Затем ThrottlingMiddleware
        setup_throttling(
            dp,
            throttled_commands=THROTTLED_COMMANDS,
            limit=2
        )
        logger.info(f"✅ ThrottlingMiddleware зарегистрирован для {len(THROTTLED_COMMANDS)} команд")

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

        mute_ban_manager.bot_ban_manager.set_middleware(bot_ban_middleware)

        logger.info("✅ BotBanMiddleware зарегистрирован")
        return True
    else:
        logger.warning("⚠️ BotBanMiddleware не зарегистрирован - mute_ban_manager не найден")
        return False


async def start_cleanup_tasks(mute_ban_manager):
    """Запуск задач очистки и проверки банов"""
    try:
        global cleanup_scheduler
        cleanup_scheduler = CleanupScheduler()
        asyncio.create_task(cleanup_scheduler.start_daily_cleanup())
        logger.info("✅ Планировщик очистки БД запущен")

        if mute_ban_manager:
            mute_ban_manager.start_cleanup_tasks(dp.bot)
            logger.info("✅ Задачи проверки мутов/банов запущены")

            await mute_ban_manager.restore_mutes_after_restart(dp.bot)
            logger.info("✅ Активные муты восстановлены после перезапуска")

    except Exception as e:
        logger.error(f"❌ Ошибка запуска задач очистки: {e}")
        raise


async def on_startup(_):
    """Действия при запуске бота - ПРАВИЛЬНЫЙ ПОРЯДОК!"""
    logger.info("🚀 Запуск бота...")

    logger.info("📊 Настройка базы данных...")
    if not setup_database():
        raise RuntimeError("Не удалось настроить базу данных")

    logger.info("🧹 Очистка старых данных...")
    cleanup_old_limits()

    if not await setup_middleware_first():
        raise RuntimeError("Не удалось настроить middleware")

    logger.info("📝 Регистрация обработчиков...")
    mute_ban_manager = register_all_handlers()

    await ensure_gifts_on_startup()

    await setup_bot_ban_middleware(mute_ban_manager)

    logger.info("⏰ Запуск задач очистки...")
    await start_cleanup_tasks(mute_ban_manager)

    logger.info("✅ Бот успешно запущен")


async def on_shutdown(dp: Dispatcher):
    """Корректное завершение работы"""
    logger.info("🛑 Завершение работы бота...")

    try:
        global cleanup_scheduler
        if cleanup_scheduler:
            await cleanup_scheduler.stop()
            logger.info("✅ Планировщик очистки остановлен")

        global mute_ban_manager
        if mute_ban_manager:
            await mute_ban_manager.stop_cleanup_tasks()
            logger.info("✅ Задачи мутов/банов остановлены")

        from database import engine
        engine.dispose()
        logger.info("✅ Соединения с БД закрыты")

        await dp.storage.close()
        await dp.storage.wait_closed()
        logger.info("✅ Хранилище диспетчера закрыто")

    except Exception as e:
        logger.error(f"💥 Критическая ошибка при завершении: {e}")
    finally:
        logger.info("✅ Бот остановлен")


def main():
    """Основная функция запуска бота"""

    def signal_handler(signum, frame):
        logger.info(f"📞 Получен сигнал {signum}. Завершение работы...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info("🔄 Запуск бота")

        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            timeout=60,
            allowed_updates=AllowedUpdates.all(),
            relax=0.5
        )

    except KeyboardInterrupt:
        logger.info("⏹️ Остановка по запросу пользователя")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()