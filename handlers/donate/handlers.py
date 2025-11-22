# handlers/donate/handlers.py

import logging
from aiogram import types, Dispatcher
from sqlalchemy import text

from .config import BONUS_AMOUNT, BONUS_COOLDOWN_HOURS, THIEF_BONUS_AMOUNT, POLICE_BONUS_AMOUNT, \
    PRIVILEGE_BONUS_COOLDOWN_HOURS, SUPPORT_USERNAME, DONATE_ITEMS
from .utils import format_time_left
from .bonus import BonusManager
from .keyboards import _get_bonus_keyboard, _get_privilege_bonus_keyboard, _get_purchase_keyboard, _get_back_keyboard, \
    _create_donate_keyboard
from database.crud import UserRepository, DonateRepository
from ..admin.admin_helpers import check_admin_async

logger = logging.getLogger(__name__)


class DonateHandler:
    """Класс для обработки операций доната и бонусов"""

    def __init__(self):
        self.logger = logger
        self.bonus_manager = BonusManager()

    # --- Вспомогательные методы ---
    async def _ensure_private_chat(self, message: types.Message) -> bool:
        """Проверяет, что команда вызвана в личных сообщениях"""
        if message.chat.type != "private":
            bot_username = (await message.bot.get_me()).username
            bot_link = f"https://t.me/{bot_username}"
            await message.reply(
                "💎 <b>Донат магазин</b>\n\n"
                f"Команда работает только в <a href='{bot_link}'>личных сообщениях</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return False
        return True

    def _get_donate_message_text(self) -> str:
        """Форматирует текст сообщения для доната"""
        text = (
            "💎 <b>Донат магазин</b>\n\n"
            "✨ <b>Доступные привилегии:</b>\n"
        )
        # Добавляем все товары в описание
        for item in DONATE_ITEMS:
            text += f"• {item['description']}\n"
        text += f"\n🎁 <b>Ежедневный бонус:</b> {BONUS_AMOUNT:,} монет каждые {BONUS_COOLDOWN_HOURS} часа\n"
        text += f"👑 <b>Бонус Вора:</b> {THIEF_BONUS_AMOUNT:,} монет каждые {PRIVILEGE_BONUS_COOLDOWN_HOURS} часа\n"
        text += f"👮‍♂️ <b>Бонус Полицейского:</b> {POLICE_BONUS_AMOUNT:,} монет каждые {PRIVILEGE_BONUS_COOLDOWN_HOURS} часа\n"
        text += f"\n💬 <b>По вопросам покупки:</b> @{SUPPORT_USERNAME}"
        return text

    def _get_user_bonus_info_text(self, user_id: int) -> str:
        """Формирует текст информации о бонусах пользователя"""
        with self.bonus_manager._db_session() as db:
            user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
            purchased_ids = [p.item_id for p in user_purchases]
            has_thief = 1 in purchased_ids
            has_police = 2 in purchased_ids

        bonus_text = "🎯 <b>Ваша бонусная система</b>\n\n"

        # ОБЫЧНЫЙ БОНУС ДЛЯ ВСЕХ
        bonus_text += f"💰 <b>Ежедневный бонус:</b> {BONUS_AMOUNT:,} монет/день\n"

        if has_thief or has_police:
            bonus_text += "\n💎 <b>Дополнительные бонусы за привилегии:</b>\n"
            if has_thief:
                bonus_text += f"• 👑 Вор в законе: +{THIEF_BONUS_AMOUNT:,} монет/день\n"
            if has_police:
                bonus_text += f"• 👮‍♂️ Полицейский: +{POLICE_BONUS_AMOUNT:,} монет/день\n"

        bonus_text += f"\n⏰ <b>Режим начисления:</b> автоматический каждые {BONUS_COOLDOWN_HOURS} часа\n"
        bonus_text += "✅ Бонусы приходят автоматически - ничего не нужно запрашивать!"

        return bonus_text

    # --- Основные команды ---
    async def donate_command(self, message: types.Message):
        """Обработчик команды доната"""
        if not await self._ensure_private_chat(message):
            return
        donate_text = self._get_donate_message_text()
        keyboard = _create_donate_keyboard(message.from_user.id)
        await message.answer(donate_text, reply_markup=keyboard, parse_mode="HTML")

    async def bonus_command(self, message: types.Message):
        """Обработчик команды бонуса"""
        await self._handle_bonus_request(message)

    async def privilege_bonus_command(self, message: types.Message):
        """Обработчик команды бонусов за привилегии"""
        await self._handle_privilege_bonus_request(message)

    # --- Обработчики запросов бонусов ---
    async def _handle_bonus_request(self, message: types.Message):
        """Обрабатывает запрос на информацию о бонусах"""
        if not await self._ensure_private_chat(message):
            return

        user_id = message.from_user.id
        bonus_info = await self.bonus_manager.check_daily_bonus(user_id)

        bonus_text = self._get_user_bonus_info_text(user_id)

        if bonus_info["available"]:
            # Бонус доступен, но начисляется автоматически
            status_text = "\n🎉 <b>Статус:</b> следующий бонус будет начислен завтра"
        else:
            # Бонус еще не доступен
            time_left = format_time_left(bonus_info['hours_left'], bonus_info['minutes_left'])
            status_text = f"\n⏳ <b>Статус:</b> до следующего бонуса {time_left}"

        full_text = bonus_text + status_text

        await message.answer(
            full_text,
            reply_markup=_get_bonus_keyboard(),
            parse_mode="HTML"
        )

    async def _handle_privilege_bonus_request(self, message: types.Message):
        """Обрабатывает запрос на информацию о бонусах за привилегии"""
        if not await self._ensure_private_chat(message):
            return

        user_id = message.from_user.id
        privilege_bonus_info = await self.bonus_manager.check_privilege_bonus(user_id)

        bonus_text = self._get_user_bonus_info_text(user_id)

        if privilege_bonus_info["available"]:
            status_text = "\n🎉 <b>Статус:</b> следующие бонусы за привилегии будут начислены завтра"
        else:
            time_left = format_time_left(privilege_bonus_info['hours_left'], privilege_bonus_info['minutes_left'])
            status_text = f"\n⏳ <b>Статус:</b> до следующих бонусов {time_left}"

        # Добавляем информацию о конкретных привилегиях
        if privilege_bonus_info['has_thief'] or privilege_bonus_info['has_police']:
            privileges_text = "\n\n🔹 <b>Ваши привилегии:</b>"
            if privilege_bonus_info['has_thief']:
                privileges_text += f"\n• 👑 Вор в законе: {THIEF_BONUS_AMOUNT:,} монет/день"
            if privilege_bonus_info['has_police']:
                privileges_text += f"\n• 👮‍♂️ Полицейский: {POLICE_BONUS_AMOUNT:,} монет/день"
        else:
            privileges_text = "\n\nℹ️ <b>У вас нет активных платных привилегий</b>"

        full_text = bonus_text + status_text + privileges_text

        await message.answer(
            full_text,
            reply_markup=_get_privilege_bonus_keyboard(),
            parse_mode="HTML"
        )

    # --- Callback обработчики ---
    async def donate_callback_handler(self, callback: types.CallbackQuery):
        """Обработчик нажатий на кнопки доната"""
        if callback.message.chat.type != "private":
            await callback.answer("💎 Команда работает только в личных сообщениях", show_alert=True)
            return

        action = callback.data
        user_id = callback.from_user.id

        try:
            if action == "daily_bonus":
                await self._handle_daily_bonus_callback(callback, user_id)
            elif action == "privilege_bonus":
                await self._handle_privilege_bonus_callback(callback, user_id)
            elif action.startswith("donate_buy_"):
                await self._handle_purchase_selection(callback)
            elif action.startswith("donate_already_bought_"):
                await self._handle_already_bought(callback)
            elif action == "back_to_donate":
                await self._handle_back_to_donate(callback)
        except Exception as e:
            self.logger.error(f"Error in donate callback handler: {e}")
            await self._handle_error(callback)

    async def _handle_daily_bonus_callback(self, callback: types.CallbackQuery, user_id: int):
        """Обрабатывает запрос на информацию о бонусах через callback"""
        bonus_info = await self.bonus_manager.check_daily_bonus(user_id)

        bonus_text = self._get_user_bonus_info_text(user_id)

        if bonus_info["available"]:
            status_text = "\n🎉 <b>Статус:</b> следующий бонус будет начислен завтра"
        else:
            time_left = format_time_left(bonus_info['hours_left'], bonus_info['minutes_left'])
            status_text = f"\n⏳ <b>Статус:</b> до следующего бонуса {time_left}"

        full_text = bonus_text + status_text

        try:
            await callback.message.edit_text(
                full_text,
                reply_markup=_get_bonus_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            if "Message is not modified" not in str(e):
                self.logger.error(f"Error editing message in daily bonus callback: {e}")

        if bonus_info["available"]:
            await callback.answer("✅ Бонусы начисляются автоматически")
        else:
            await callback.answer(f"⏳ Бонус будет начислен через {time_left}")

    async def _handle_privilege_bonus_callback(self, callback: types.CallbackQuery, user_id: int):
        """Обрабатывает запрос на информацию о бонусах за привилегии через callback"""
        privilege_bonus_info = await self.bonus_manager.check_privilege_bonus(user_id)

        bonus_text = self._get_user_bonus_info_text(user_id)

        if privilege_bonus_info["available"]:
            status_text = "\n🎉 <b>Статус:</b> следующие бонусы за привилегии будут начислены завтра"
        else:
            time_left = format_time_left(privilege_bonus_info['hours_left'], privilege_bonus_info['minutes_left'])
            status_text = f"\n⏳ <b>Статус:</b> до следующих бонусов {time_left}"

        # Добавляем информацию о конкретных привилегиях
        if privilege_bonus_info['has_thief'] or privilege_bonus_info['has_police']:
            privileges_text = "\n\n🔹 <b>Ваши привилегии:</b>"
            if privilege_bonus_info['has_thief']:
                privileges_text += f"\n• 👑 Вор в законе: {THIEF_BONUS_AMOUNT:,} монет/день"
            if privilege_bonus_info['has_police']:
                privileges_text += f"\n• 👮‍♂️ Полицейский: {POLICE_BONUS_AMOUNT:,} монет/день"
        else:
            privileges_text = "\n\nℹ️ <b>У вас нет активных платных привилегий</b>"

        full_text = bonus_text + status_text + privileges_text

        try:
            await callback.message.edit_text(
                full_text,
                reply_markup=_get_privilege_bonus_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            if "Message is not modified" not in str(e):
                self.logger.error(f"Error editing message in privilege bonus callback: {e}")

        if privilege_bonus_info["available"]:
            await callback.answer("✅ Бонусы начисляются автоматически")
        else:
            await callback.answer(f"⏳ Бонусы будут начислены через {time_left}")

    async def _handle_purchase_selection(self, callback: types.CallbackQuery):
        """Обрабатывает выбор товара для покупки"""
        item_id = int(callback.data.split("_")[2])
        item = next((i for i in DONATE_ITEMS if i["id"] == item_id), None)
        if item:
            try:
                await callback.message.edit_text(
                    f"💳 <b>Покупка донат-привилегии</b>\n\n"
                    f"📦 Товар: <b>{item['name']}</b>\n"
                    f"💰 Цена: <b>{item['price']}</b>\n"
                    f"⏱️ Срок: <b>{item['duration']}</b>\n\n"
                    f"🎯 <b>Преимущество:</b>\n"
                    f"{item['benefit']}\n\n"
                    f"💬 <b>Для покупки обратитесь:</b>\n"
                    f"👤 @{SUPPORT_USERNAME}",
                    reply_markup=_get_purchase_keyboard(),
                    parse_mode="HTML"
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    self.logger.error(f"Error editing message for purchase selection: {e}")
            await callback.answer(f"🛒 {item['name']}")
        else:
            await callback.answer("❌ Товар не найден")

    async def _handle_already_bought(self, callback: types.CallbackQuery):
        """Обрабатывает нажатие на уже купленную привилегию"""
        item_id = int(callback.data.split("_")[3])
        item = next((i for i in DONATE_ITEMS if i["id"] == item_id), None)
        if item:
            try:
                await callback.message.edit_text(
                    f"✅ <b>Привилегия уже активна</b>\n\n"
                    f"📦 Товар: <b>{item['name']}</b>\n"
                    f"💰 Цена: <b>{item['price']}</b>\n"
                    f"⏱️ Срок: <b>{item['duration']}</b>\n\n"
                    f"🎯 <b>Преимущество:</b>\n"
                    f"{item['benefit']}\n\n"
                    f"💡 Эта привилегия уже активна в вашем профиле!\n"
                    f"💰 Вы получаете бонусы автоматически каждые {BONUS_COOLDOWN_HOURS} часа",
                    reply_markup=_get_back_keyboard(),
                    parse_mode="HTML"
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    self.logger.error(f"Error editing message for already bought item: {e}")
            await callback.answer("✅ Уже куплено")
        else:
            await callback.answer("❌ Товар не найден")

    async def _handle_back_to_donate(self, callback: types.CallbackQuery):
        """Возвращает в главное меню доната"""
        donate_text = self._get_donate_message_text()
        keyboard = _create_donate_keyboard(callback.from_user.id)
        try:
            await callback.message.edit_text(donate_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" not in str(e):
                self.logger.error(f"Error editing message when going back to donate: {e}")
        await callback.answer("⬅️ Возврат в меню")

    async def _handle_error(self, callback: types.CallbackQuery):
        """Обрабатывает общие ошибки"""
        try:
            await callback.message.edit_text(
                "❌ <b>Произошла ошибка!</b>\n\n"
                "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                reply_markup=_get_back_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            if "Message is not modified" not in str(e):
                self.logger.error(f"Error editing message in _handle_error: {e}")
        await callback.answer("⚠️ Произошла ошибка")

    # --- Методы для администратора ---
    async def force_bonus_distribution(self, message: types.Message):
        """Принудительное распределение бонусов (для админа)"""
        if not await self._ensure_private_chat(message):
            return

        # Проверяем права администратора (добавьте свою логику проверки)
        # if message.from_user.id not in ADMIN_IDS:
        #     await message.answer("❌ Недостаточно прав")
        #     return

        try:
            await message.answer("🔄 Запуск принудительного распределения бонусов...")

            bonus_count = await self.bonus_manager.process_automatic_bonuses()

            await message.answer(
                f"✅ Принудительное распределение завершено!\n"
                f"🎁 Начислено бонусов: {bonus_count} пользователям"
            )

        except Exception as e:
            self.logger.error(f"Error in force bonus distribution: {e}")
            await message.answer("❌ Ошибка при распределении бонусов")

    async def check_expiring_privileges(self, message: types.Message):
        """Проверка истекающих привилегий (для админа)"""
        if not await self._ensure_private_chat(message):
            return

        # Проверяем права администратора
        # if message.from_user.id not in ADMIN_IDS:
        #     await message.answer("❌ Недостаточно прав")
        #     return

        try:
            await message.answer("🔍 Проверка истекающих привилегий...")

            expiring_soon, expired = await self.bonus_manager.check_expiring_privileges()

            result_text = (
                f"📊 <b>Статус привилегий:</b>\n\n"
                f"⏳ Истекают через 1 день: <b>{len(expiring_soon)}</b>\n"
                f"🔚 Уже истекли: <b>{len(expired)}</b>"
            )

            if expired:
                deactivated_count = await self.bonus_manager.deactivate_expired_privileges(expired)
                result_text += f"\n\n🔚 Деактивировано: <b>{deactivated_count}</b>"

            await message.answer(result_text, parse_mode="HTML")

        except Exception as e:
            self.logger.error(f"Error checking expiring privileges: {e}")
            await message.answer("❌ Ошибка при проверке привилегий")


    async def force_table_update(self, message: types.Message):
        """Принудительное обновление таблицы бонусов (для админа)"""
        if not await self._ensure_private_chat(message):
            return

        try:
            # Создаем новый экземпляр BonusManager для переинициализации таблицы
            self.bonus_manager = BonusManager()

            await message.answer(
                "✅ Таблица бонусов успешно обновлена\n"
                "🔄 Добавлена колонка last_auto_bonus_time"
            )

        except Exception as e:
            self.logger.error(f"Error updating bonus table: {e}")
            await message.answer("❌ Ошибка при обновлении таблицы")


def register_donate_handlers(dp: Dispatcher):
    """Регистрация обработчиков доната"""
    handler = DonateHandler()

    # Регистрация команд доната
    dp.register_message_handler(handler.donate_command, commands=["донат", "donate"], state="*")
    dp.register_message_handler(handler.donate_command, lambda m: m.text and m.text.lower() in ["донат", "donate"],
                                state="*")

    # Регистрация команд бонуса
    dp.register_message_handler(handler.bonus_command, commands=["бонус", "bonus"], state="*")
    dp.register_message_handler(handler.bonus_command, lambda m: m.text and m.text.lower() in ["бонус", "bonus"],
                                state="*")

    # Регистрация команд бонусов за привилегии
    dp.register_message_handler(handler.privilege_bonus_command, commands=["привилегиябонус", "privilegebonus"],
                                state="*")
    dp.register_message_handler(handler.privilege_bonus_command,
                                lambda m: m.text and m.text.lower() in ["привилегиябонус", "privilegebonus", "бонусы"],
                                state="*")

    # Регистрация административных команд
    dp.register_message_handler(handler.force_bonus_distribution, commands=["force_bonus"], state="*")
    dp.register_message_handler(handler.check_expiring_privileges, commands=["check_privileges"], state="*")

    # Регистрация callback обработчиков
    donate_callbacks = ["donate_buy_", "donate_already_bought_", "daily_bonus", "privilege_bonus", "back_to_donate"]
    dp.register_callback_query_handler(handler.donate_callback_handler,
                                       lambda c: any(c.data.startswith(prefix) for prefix in donate_callbacks),
                                       state="*")
    dp.register_message_handler(handler.force_table_update, commands=["update_bonus_table"], state="*")

    logging.info("✅ Донат обработчики зарегистрированы (автоматические бонусы)")