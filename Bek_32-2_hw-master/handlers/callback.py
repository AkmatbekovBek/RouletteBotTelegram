from aiogram import types, Dispatcher
import logging
from config import bot
from database import get_db
from database.crud import UserRepository
from keyboards.main_menu_kb import main_inline_keyboard
from typing import List, Dict

# Настройка логирования
logger = logging.getLogger(__name__)


class CallbackHandler:
    """Обработчик callback запросов"""

    async def handle_main_menu(self, call: types.CallbackQuery) -> None:
        """Обработка перехода в главное меню"""
        try:
            await self._send_main_menu_message(call)
            await self._cleanup_previous_message(call)
        except Exception as e:
            logger.error(f"Main menu callback error: {e}")
            await self._handle_callback_error(call, "Не удалось открыть главное меню")

    async def handle_admin_users_list(self, call: types.CallbackQuery) -> None:
        """Обработка запроса списка пользователей для администратора"""
        db = next(get_db())
        try:
            users = UserRepository.get_all_users(db)
            if not users:
                await call.answer("📭 Пользователей не найдено", show_alert=True)
                return

            formatted_users = self._format_users_list(users)
            await self._send_users_list(call, formatted_users)

        except Exception as e:
            logger.error(f"Admin users callback error: {e}")
            await self._handle_callback_error(call, "Не удалось загрузить список пользователей")
        finally:
            db.close()

    async def _send_main_menu_message(self, call: types.CallbackQuery) -> None:
        """Отправляет сообщение с главным меню"""
        await bot.send_message(
            chat_id=call.message.chat.id,
            text="🎯 *Главное меню*\n\nВыберите нужный раздел:",
            parse_mode=types.ParseMode.MARKDOWN,
            reply_markup=main_inline_keyboard()   # ✅ заменено на inline
        )

    async def _cleanup_previous_message(self, call: types.CallbackQuery) -> None:
        """Удаляет предыдущее сообщение с callback кнопками"""
        try:
            await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception as e:
            logger.warning(f"Could not delete previous message: {e}")

    def _format_users_list(self, users: List) -> str:
        """Форматирует список пользователей для отправки"""
        formatted_lines = []
        for user in users:
            username = user.username or user.first_name or "Неизвестный"
            user_id = user.telegram_id
            formatted_lines.append(f"👤 [{username}](tg://user?id={user_id})")
        return "\n".join(formatted_lines) if formatted_lines else "📭 Пользователей не найдено"

    async def _send_users_list(self, call: types.CallbackQuery, users_text: str) -> None:
        """Отправляет форматированный список пользователей"""
        await call.message.reply(text=users_text, parse_mode=types.ParseMode.MARKDOWN)

    async def _handle_callback_error(self, call: types.CallbackQuery, error_message: str) -> None:
        """Обрабатывает ошибки в callback обработчиках"""
        await call.answer("❌ Произошла ошибка", show_alert=True)
        logger.error(f"Callback error for user {call.from_user.id}: {error_message}")


class CallbackHandlerFactory:
    """Фабрика для создания и регистрации обработчиков callback"""

    @staticmethod
    def create_and_register_handlers(dp: Dispatcher) -> None:
        """Создает и регистрирует все callback обработчики"""
        handler = CallbackHandler()

        CallbackHandlerFactory._register_handler(dp, handler.handle_main_menu, lambda c: c.data == "main_menu")
        CallbackHandlerFactory._register_handler(dp, handler.handle_admin_users_list, lambda c: c.data == "admin_user_list")

    @staticmethod
    def _register_handler(dp: Dispatcher, handler_func, filter_func) -> None:
        """Регистрация обработчика с логированием"""
        try:
            dp.register_callback_query_handler(handler_func, filter_func)
            logger.info(f"Successfully registered callback handler: {handler_func.__name__}")
        except Exception as e:
            logger.error(f"Failed to register callback handler {handler_func.__name__}: {e}")


def register_callback_handlers(dp: Dispatcher) -> None:
    """Основная функция регистрации callback обработчиков"""
    CallbackHandlerFactory.create_and_register_handlers(dp)