# handlers/donate/handlers.py

import logging
from aiogram import types, Dispatcher
from .config import BONUS_AMOUNT, BONUS_COOLDOWN_HOURS, THIEF_BONUS_AMOUNT, POLICE_BONUS_AMOUNT, \
    PRIVILEGE_BONUS_COOLDOWN_HOURS, SUPPORT_USERNAME, DONATE_ITEMS
from .utils import format_time_left # Импортируем format_time_left
from .bonus import BonusManager
from .keyboards import _get_bonus_keyboard, _get_privilege_bonus_keyboard, _get_purchase_keyboard, _get_back_keyboard, _create_donate_keyboard
from database.crud import UserRepository, DonateRepository # Добавляем DonateRepository

logger = logging.getLogger(__name__)

class DonateHandler:
    """Класс для обработки операций доната и бонусов"""

    def __init__(self):
        self.logger = logger
        self.bonus_manager = BonusManager() # Создаём экземпляр BonusManager

    # --- Вспомогательные методы ---
    async def _ensure_private_chat(self, message: types.Message) -> bool:
        """Проверяет, что команда вызвана в личных сообщениях"""
        if message.chat.type != "private":
            bot_username = (await message.bot.get_me()).username
            bot_link = f"https://t.me/{bot_username}"
            await message.reply(
                "💎 <b>Донат магазин</b>"
                f"Команда работает только в <a href='{bot_link}'>личных сообщениях</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return False
        return True

    def _get_donate_message_text(self) -> str:
        """Форматирует текст сообщения для доната"""
        text = (
            "💎 <b>Донат магазин</b>\n"
            "✨ <b>Доступные привилегии:</b>\n"
        )
        # Добавляем все товары в описание
        for item in DONATE_ITEMS:
            text += f"• {item['description']}\n"
        text += f"🎁 <b>Ежедневный бонус:</b> {BONUS_AMOUNT} монет каждые {BONUS_COOLDOWN_HOURS} часа\n"
        text += f"👑 <b>Бонус Вора:</b> {THIEF_BONUS_AMOUNT:,} монет каждые {PRIVILEGE_BONUS_COOLDOWN_HOURS} часа\n"
        text += f"👮‍♂️ <b>Бонус Полицейского:</b> {POLICE_BONUS_AMOUNT:,} монет каждые {PRIVILEGE_BONUS_COOLDOWN_HOURS} часа\n"
        text += f"💬 <b>По вопросам покупки:</b> @{SUPPORT_USERNAME}"
        return text

    # --- Основные команды ---
    async def donate_command(self, message: types.Message):
        """Обработчик команды доната"""
        if not await self._ensure_private_chat(message):
            return
        donate_text = self._get_donate_message_text()
        keyboard = _create_donate_keyboard(message.from_user.id) # Используем функцию из keyboards.py
        await message.answer(donate_text, reply_markup=keyboard, parse_mode="HTML")

    async def bonus_command(self, message: types.Message):
        """Обработчик команды бонуса"""
        await self._handle_bonus_request(message)

    async def privilege_bonus_command(self, message: types.Message):
        """Обработчик команды бонусов за привилегии"""
        await self._handle_privilege_bonus_request(message)

    # --- Обработчики запросов бонусов ---
    async def _handle_bonus_request(self, message: types.Message):
        """Обрабатывает запрос на ежедневный бонус"""
        if not await self._ensure_private_chat(message):
            return

        user_id = message.from_user.id
        bonus_info = await self.bonus_manager.check_daily_bonus(user_id)

        if bonus_info["available"]:
            success = await self.bonus_manager.claim_daily_bonus(
                user_id=user_id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or "User"
            )
            if success:
                updated_bonus_info = await self.bonus_manager.check_daily_bonus(user_id)
                await message.answer(
                    f"🎉 <b>Бонус получен!</b>\n"
                    f"💰 Вам начислено: <b>{BONUS_AMOUNT} монет</b>\n"
                    f"📊 Всего получено бонусов: <b>{updated_bonus_info['bonus_count']}</b>\n"
                    f"⏰ Следующий бонус через <b>{BONUS_COOLDOWN_HOURS} часа</b>",
                    reply_markup=_get_bonus_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
                await message.answer("🎁 Бонус успешно получен!")
            else:
                await message.answer(
                    "❌ <b>Ошибка!</b>\n"
                    "Не удалось выдать бонус. Попробуйте позже.",
                    reply_markup=_get_bonus_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
        else:
            time_left = format_time_left(bonus_info['hours_left'], bonus_info['minutes_left']) # Используем format_time_left из utils
            await message.answer(
                f"⏳ <b>Бонус еще не доступен</b>\n"
                f"🕐 До следующего бонуса: <b>{time_left}</b>\n"
                f"📊 Всего получено бонусов: <b>{bonus_info['bonus_count']}</b>\n"
                f"💫 Приходите позже!",
                reply_markup=_get_bonus_keyboard(), # Используем функцию из keyboards.py
                parse_mode="HTML"
            )

    async def _handle_privilege_bonus_request(self, message: types.Message):
        """Обрабатывает запрос на бонусы за привилегии"""
        if not await self._ensure_private_chat(message):
            return

        user_id = message.from_user.id
        # Получаем активные привилегии
        with self.bonus_manager._db_session() as db: # Используем сессию из BonusManager
            user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
            purchased_ids = [p.item_id for p in user_purchases]
            has_thief = 1 in purchased_ids
            has_police = 2 in purchased_ids

        # Передаём флаги в check_privilege_bonus
        privilege_bonus_info = await self.bonus_manager.check_privilege_bonus(user_id, has_thief, has_police)

        if privilege_bonus_info["available"]:
            success, bonuses_claimed = await self.bonus_manager.claim_privilege_bonus(
                user_id=user_id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or "User"
            )
            if success:
                # После выдачи получаем обновлённую информацию
                with self.bonus_manager._db_session() as db:
                    user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                    purchased_ids = [p.item_id for p in user_purchases]
                    updated_has_thief = 1 in purchased_ids
                    updated_has_police = 2 in purchased_ids
                updated_bonus_info = await self.bonus_manager.check_privilege_bonus(user_id, updated_has_thief, updated_has_police)
                bonus_text = "🎉 <b>Бонусы за привилегии получены!</b>\n"
                total_bonus = 0
                if "thief" in bonuses_claimed:
                    bonus_text += f"👑 Бонус Вора: <b>{THIEF_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += THIEF_BONUS_AMOUNT
                if "police" in bonuses_claimed:
                    bonus_text += f"👮‍♂️ Бонус Полицейского: <b>{POLICE_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += POLICE_BONUS_AMOUNT
                bonus_text += f"💰 Всего получено: <b>{total_bonus:,} монет</b>\n"
                bonus_text += f"📊 Всего бонусов Вора: <b>{updated_bonus_info['thief_bonus_count']}</b>\n"
                bonus_text += f"📊 Всего бонусов Полицейского: <b>{updated_bonus_info['police_bonus_count']}</b>\n"
                bonus_text += f"⏰ Следующие бонусы через <b>{PRIVILEGE_BONUS_COOLDOWN_HOURS} часа</b>"

                await message.answer(
                    bonus_text,
                    reply_markup=_get_privilege_bonus_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "❌ <b>Ошибка!</b>\n"
                    "Не удалось выдать бонусы. Попробуйте позже.",
                    reply_markup=_get_privilege_bonus_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
        else:
            time_left = format_time_left(privilege_bonus_info['hours_left'], privilege_bonus_info['minutes_left']) # Используем format_time_left из utils
            bonus_text = "⏳ <b>Бонусы за привилегии еще не доступны</b>\n"
            if privilege_bonus_info['has_thief']:
                bonus_text += f"👑 Вор в законе: бонус доступен через <b>{time_left}</b>\n"
            if privilege_bonus_info['has_police']:
                bonus_text += f"👮‍♂️ Полицейский: бонус доступен через <b>{time_left}</b>\n"
            bonus_text += f"📊 Всего бонусов Вора: <b>{privilege_bonus_info['thief_bonus_count']}</b>\n"
            bonus_text += f"📊 Всего бонусов Полицейского: <b>{privilege_bonus_info['police_bonus_count']}</b>\n"
            bonus_text += "💫 Приходите позже!"

            await message.answer(
                bonus_text,
                reply_markup=_get_privilege_bonus_keyboard(), # Используем функцию из keyboards.py
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
        """Обрабатывает запрос на ежедневный бонус через callback"""
        bonus_info = await self.bonus_manager.check_daily_bonus(user_id)

        if bonus_info["available"]:
            success = await self.bonus_manager.claim_daily_bonus(
                user_id=user_id,
                username=callback.from_user.username or "",
                first_name=callback.from_user.first_name or "User"
            )
            if success:
                updated_bonus_info = await self.bonus_manager.check_daily_bonus(user_id)
                try: # Обернем edit_text в try-except
                    await callback.message.edit_text(
                        f"🎉 <b>Бонус получен!</b>\n"
                        f"💰 Вам начислено: <b>{BONUS_AMOUNT} монет</b>\n"
                        f"📊 Всего получено бонусов: <b>{updated_bonus_info['bonus_count']}</b>\n"
                        f"⏰ Следующий бонус через <b>{BONUS_COOLDOWN_HOURS} часа</b>",
                        reply_markup=_get_bonus_keyboard(), # Используем функцию из keyboards.py
                        parse_mode="HTML"
                    )
                except Exception as e:
                    # Игнорируем ошибку "Message is not modified" при редактировании
                    if "Message is not modified" not in str(e):
                        self.logger.error(f"Error editing message after claiming daily bonus (callback): {e}")
                await callback.answer("🎁 Бонус успешно получен!")
            else:
                try: # Обернем edit_text в try-except
                    await callback.message.edit_text(
                        "❌ <b>Ошибка!</b>\n"
                        "Не удалось выдать бонус. Попробуйте позже.",
                        reply_markup=_get_bonus_keyboard(), # Используем функцию из keyboards.py
                        parse_mode="HTML"
                    )
                except Exception as e:
                    # Игнорируем ошибку "Message is not modified" при редактировании
                    if "Message is not modified" not in str(e):
                        self.logger.error(f"Error editing message after failed daily bonus claim (callback): {e}")
                await callback.answer("⚠️ Ошибка при получении бонуса")
        else:
            time_left = format_time_left(bonus_info['hours_left'], bonus_info['minutes_left']) # Используем format_time_left из utils
            try: # Обернем edit_text в try-except
                await callback.message.edit_text(
                    f"⏳ <b>Бонус еще не доступен</b>\n"
                    f"🕐 До следующего бонуса: <b>{time_left}</b>\n"
                    f"📊 Всего получено бонусов: <b>{bonus_info['bonus_count']}</b>\n"
                    f"💫 Приходите позже!",
                    reply_markup=_get_bonus_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
            except Exception as e:
                # Игнорируем ошибку "Message is not modified" при редактировании
                if "Message is not modified" not in str(e):
                    self.logger.error(f"Error editing message when daily bonus is not available (callback): {e}")
            await callback.answer(f"⏰ Бонус будет доступен через {time_left}")

    async def _handle_privilege_bonus_callback(self, callback: types.CallbackQuery, user_id: int):
        """Обрабатывает запрос на бонусы за привилегии через callback"""
        # Получаем активные привилегии
        with self.bonus_manager._db_session() as db:
            user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
            purchased_ids = [p.item_id for p in user_purchases]
            has_thief = 1 in purchased_ids
            has_police = 2 in purchased_ids

        # Передаём флаги в check_privilege_bonus
        privilege_bonus_info = await self.bonus_manager.check_privilege_bonus(user_id, has_thief, has_police)

        if privilege_bonus_info["available"]:
            success, bonuses_claimed = await self.bonus_manager.claim_privilege_bonus(
                user_id=user_id,
                username=callback.from_user.username or "",
                first_name=callback.from_user.first_name or "User"
            )
            if success:
                # После выдачи получаем обновлённую информацию
                with self.bonus_manager._db_session() as db:
                    user_purchases = DonateRepository.get_user_active_purchases(db, user_id)
                    purchased_ids = [p.item_id for p in user_purchases]
                    updated_has_thief = 1 in purchased_ids
                    updated_has_police = 2 in purchased_ids
                updated_bonus_info = await self.bonus_manager.check_privilege_bonus(user_id, updated_has_thief, updated_has_police)
                bonus_text = "🎉 <b>Бонусы за привилегии получены!</b>\n"
                total_bonus = 0
                if "thief" in bonuses_claimed:
                    bonus_text += f"👑 Бонус Вора: <b>{THIEF_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += THIEF_BONUS_AMOUNT
                if "police" in bonuses_claimed:
                    bonus_text += f"👮‍♂️ Бонус Полицейского: <b>{POLICE_BONUS_AMOUNT:,} монет</b>\n"
                    total_bonus += POLICE_BONUS_AMOUNT
                bonus_text += f"💰 Всего получено: <b>{total_bonus:,} монет</b>\n"
                bonus_text += f"📊 Всего бонусов Вора: <b>{updated_bonus_info['thief_bonus_count']}</b>\n"
                bonus_text += f"📊 Всего бонусов Полицейского: <b>{updated_bonus_info['police_bonus_count']}</b>\n"
                bonus_text += f"⏰ Следующие бонусы через <b>{PRIVILEGE_BONUS_COOLDOWN_HOURS} часа</b>"

                try: # Обернем edit_text в try-except
                    await callback.message.edit_text(
                        bonus_text,
                        reply_markup=_get_privilege_bonus_keyboard(), # Используем функцию из keyboards.py
                        parse_mode="HTML"
                    )
                except Exception as e:
                    # Игнорируем ошибку "Message is not modified" при редактировании
                    if "Message is not modified" not in str(e):
                        self.logger.error(f"Error editing message after claiming privilege bonus (callback): {e}")
                await callback.answer("💰 Бонусы успешно получены!")
            else:
                try: # Обернем edit_text в try-except
                    await callback.message.edit_text(
                        "❌ <b>Ошибка!</b>\n"
                        "Не удалось выдать бонусы. Попробуйте позже.",
                        reply_markup=_get_privilege_bonus_keyboard(), # Используем функцию из keyboards.py
                        parse_mode="HTML"
                    )
                except Exception as e:
                    # Игнорируем ошибку "Message is not modified" при редактировании
                    if "Message is not modified" not in str(e):
                        self.logger.error(f"Error editing message after failed privilege bonus claim (callback): {e}")
                await callback.answer("⚠️ Ошибка при получении бонусов")
        else:
            time_left = format_time_left(privilege_bonus_info['hours_left'], privilege_bonus_info['minutes_left']) # Используем format_time_left из utils
            bonus_text = "⏳ <b>Бонусы за привилегии еще не доступны</b>\n"
            if privilege_bonus_info['has_thief']:
                bonus_text += f"👑 Вор в законе: бонус доступен через <b>{time_left}</b>\n"
            if privilege_bonus_info['has_police']:
                bonus_text += f"👮‍♂️ Полицейский: бонус доступен через <b>{time_left}</b>\n"
            bonus_text += f"📊 Всего бонусов Вора: <b>{privilege_bonus_info['thief_bonus_count']}</b>\n"
            bonus_text += f"📊 Всего бонусов Полицейского: <b>{privilege_bonus_info['police_bonus_count']}</b>\n"
            bonus_text += "💫 Приходите позже!"

            try: # Обернем edit_text в try-except
                await callback.message.edit_text(
                    bonus_text,
                    reply_markup=_get_privilege_bonus_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
            except Exception as e:
                # Игнорируем ошибку "Message is not modified" при редактировании
                if "Message is not modified" not in str(e):
                    self.logger.error(f"Error editing message when privilege bonus is not available (callback): {e}")
            await callback.answer(f"⏰ Бонусы будут доступны через {time_left}")

    async def _handle_purchase_selection(self, callback: types.CallbackQuery):
        """Обрабатывает выбор товара для покупки"""
        item_id = int(callback.data.split("_")[2])
        item = next((i for i in DONATE_ITEMS if i["id"] == item_id), None)
        if item:
            try: # Обернем edit_text в try-except
                await callback.message.edit_text(
                    f"💳 <b>Покупка донат-привилегии</b>\n"
                    f"📦 Товар: <b>{item['name']}</b>\n"
                    f"💰 Цена: <b>{item['price']}</b>\n"
                    f"⏱️ Срок: <b>{item['duration']}</b>\n"
                    f"🎯 <b>Преимущество:</b>\n"
                    f"{item['benefit']}\n"
                    f"💬 <b>Для покупки обратитесь:</b>\n"
                    f"👤 @{SUPPORT_USERNAME}",
                    reply_markup=_get_purchase_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
            except Exception as e:
                # Игнорируем ошибку "Message is not modified" при редактировании
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
            try: # Обернем edit_text в try-except
                await callback.message.edit_text(
                    f"✅ <b>Привилегия уже куплена</b>\n"
                    f"📦 Товар: <b>{item['name']}</b>\n"
                    f"💰 Цена: <b>{item['price']}</b>\n"
                    f"⏱️ Срок: <b>{item['duration']}</b>\n"
                    f"🎯 <b>Преимущество:</b>\n"
                    f"{item['benefit']}\n"
                    f"💡 Эта привилегия уже активна в вашем профиле!",
                    reply_markup=_get_back_keyboard(), # Используем функцию из keyboards.py
                    parse_mode="HTML"
                )
            except Exception as e:
                # Игнорируем ошибку "Message is not modified" при редактировании
                if "Message is not modified" not in str(e):
                    self.logger.error(f"Error editing message for already bought item: {e}")
            await callback.answer("✅ Уже куплено")
        else:
            await callback.answer("❌ Товар не найден")

    async def _handle_back_to_donate(self, callback: types.CallbackQuery):
        """Возвращает в главное меню доната"""
        donate_text = self._get_donate_message_text()
        keyboard = _create_donate_keyboard(callback.from_user.id) # Используем функцию из keyboards.py
        try: # Обернем edit_text в try-except
            await callback.message.edit_text(donate_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            # Игнорируем ошибку "Message is not modified" при редактировании
            if "Message is not modified" not in str(e):
                self.logger.error(f"Error editing message when going back to donate: {e}")
        await callback.answer("⬅️ Возврат в меню")

    async def _handle_error(self, callback: types.CallbackQuery):
        """Обрабатывает общие ошибки"""
        try: # Обернем edit_text в try-except
            await callback.message.edit_text(
                "❌ <b>Произошла ошибка!</b>\n"
                "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                reply_markup=_get_back_keyboard(), # Используем функцию из keyboards.py
                parse_mode="HTML"
            )
        except Exception as e:
            # Игнорируем ошибку "Message is not modified" при редактировании
            if "Message is not modified" not in str(e):
                self.logger.error(f"Error editing message in _handle_error: {e}")
        await callback.answer("⚠️ Произошла ошибка")


def register_donate_handlers(dp: Dispatcher):
    """Регистрация обработчиков доната"""
    handler = DonateHandler()

    # Регистрация команд доната
    dp.register_message_handler(handler.donate_command, commands=["донат", "donate"], state="*")
    dp.register_message_handler(handler.donate_command, lambda m: m.text and m.text.lower() in ["донат", "donate"], state="*")

    # Регистрация команд бонуса
    dp.register_message_handler(handler.bonus_command, commands=["бонус", "bonus"], state="*")
    dp.register_message_handler(handler.bonus_command, lambda m: m.text and m.text.lower() in ["бонус", "bonus"], state="*")

    # Регистрация команд бонусов за привилегии
    dp.register_message_handler(handler.privilege_bonus_command, commands=["привилегиябонус", "privilegebonus"], state="*")
    dp.register_message_handler(handler.privilege_bonus_command, lambda m: m.text and m.text.lower() in ["привилегиябонус", "privilegebonus", "бонусы"], state="*")

    # Регистрация callback обработчиков
    donate_callbacks = ["donate_buy_", "donate_already_bought_", "daily_bonus", "privilege_bonus", "back_to_donate"]
    dp.register_callback_query_handler(handler.donate_callback_handler, lambda c: any(c.data.startswith(prefix) for prefix in donate_callbacks), state="*")

    logging.info("✅ Донат обработчики зарегистрированы (с бонусами за привилегии)")