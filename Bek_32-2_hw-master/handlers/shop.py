import logging
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from aiogram import Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import get_db, models
from database.crud import UserRepository, ShopRepository

# Конфигурация магазина
SHOP_ITEMS = [
    {
        "id": 4,
        "name": "🙈 Невидимка от !бот ищи",
        "price": 250000,
        "price_display": "250к монет",
        "description": "🙈 Невидимка от !бот ищи - 250к монет",
        "benefit": "🙈 Теперь вас не найдет команда 'бот ищи'!"
    },
    {
        "id": 5,
        "name": "🚫 Защита от !бот стоп",
        "price": 1000000,
        "price_display": "1кк монет",
        "description": "🚫 Защита от !бот стоп - 1кк монет",
        "benefit": "🚫 Теперь вас не остановит команда 'бот стоп'!"
    },
    {
        "id": 6,
        "name": "🚫🙊 Защита от !!мут и !бот стоп",
        "price": 4000000,
        "price_display": "4кк монет",
        "description": "🚫🙊 Защита от !!мут и !бот стоп - 4кк монет",
        "benefit": "🚫🙊 Теперь вас не замутит и не остановит!"
    },
    {
        "id": 7,
        "name": "🔐 Снятие лимита рулетки в группе",
        "price": 2000000,
        "price_display": "2кк монет",
        "description": "🔐 Снятие лимита рулетки в группе - 2кк монет",
        "benefit": "🔐 Теперь лимит рулетки снят! Вы можете играть без ограничений!"
    }
]

# ID товаров для быстрого доступа
ITEM_IDS = {item["id"]: item for item in SHOP_ITEMS}


class ShopHandler:
    """Класс для обработки операций магазина"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def _db_session(self):
        """Контекстный менеджер для работы с БД"""
        session = None
        try:
            session = next(get_db())
            yield session
        except Exception as e:
            self.logger.error(f"Database connection error: {e}")
            if session:
                session.rollback()
            raise
        finally:
            if session:
                session.close()

    def _format_number(self, number: int) -> str:
        """Форматирует числа с разделителями тысяч"""
        return f"{number:,}".replace(",", ".")

    def _create_shop_keyboard(self, user_id: int = None, chat_id: int = None) -> InlineKeyboardMarkup:
        """Создает клавиатуру магазина с учетом активных покупок"""
        keyboard = InlineKeyboardMarkup(row_width=1)

        with self._db_session() as db:
            try:
                # Получаем активные покупки пользователя
                active_purchases = set(ShopRepository.get_active_purchases(db, user_id))

                # Добавляем кнопки товаров
                for item in SHOP_ITEMS:
                    if item["id"] in active_purchases:
                        # Товар уже активен - нельзя купить снова
                        button_text = f"✅ {item['name']} (активно)"
                        callback_data = f"shop_already_active_{item['id']}"
                    else:
                        # Товар доступен для покупки
                        button_text = f"{item['name']} - {item['price_display']}"
                        callback_data = f"shop_buy_{item['id']}"

                    keyboard.add(InlineKeyboardButton(
                        text=button_text,
                        callback_data=callback_data
                    ))

                # Кнопка подарков
                keyboard.add(InlineKeyboardButton(
                    text="🎁 Подарки",
                    callback_data="gifts"
                ))

            except Exception as e:
                self.logger.error(f"Error creating shop keyboard: {e}")

        return keyboard

    def _get_shop_message_text(self, user_id: int = None, chat_id: int = None) -> str:
        """Формирует текст сообщения для магазина"""
        text = "🛍️ <b>Магазин привилегий</b>\n\n"

        # Описание товаров
        for item in SHOP_ITEMS:
            text += f"• {item['description']}\n"

        # Информация о покупках
        if user_id and chat_id:
            with self._db_session() as db:
                try:
                    user_purchases = ShopRepository.get_user_purchases_in_chat(db, user_id, chat_id)
                    if user_purchases:
                        text += "\n🛒 <b>Ваши покупки в этом чате:</b>\n"
                        for item_id in user_purchases:
                            item = ITEM_IDS.get(item_id)
                            if item:
                                text += f"✅ {item['name']}\n"
                except Exception as e:
                    self.logger.error(f"Error getting user purchases: {e}")

        return text

    async def shop_command(self, message: types.Message):
        """Обработчик команды магазина"""
        # Проверяем, что команда вызвана в личных сообщениях
        if message.chat.type != "private":
            bot_username = (await message.bot.get_me()).username
            await message.reply(
                f"<b>🛍️ Магазин привилегий</b>\n"
                f"Покупка доступна только в <a href='https://t.me/{bot_username}'>личных сообщениях</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

        user_id = message.from_user.id
        chat_id = message.chat.id

        shop_text = self._get_shop_message_text(user_id, chat_id)
        keyboard = self._create_shop_keyboard(user_id, chat_id)

        await message.answer(
            shop_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    async def shop_callback_handler(self, callback: types.CallbackQuery):
        """Обработчик нажатий на кнопки магазина"""
        action = callback.data
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        try:
            if action.startswith("shop_buy_"):
                await self._handle_purchase(callback, user_id, chat_id)
            elif action.startswith("shop_already_bought_"):
                await self._handle_already_purchased(callback)
            elif action.startswith("shop_already_active_"):  # Добавьте эту строку
                await self._handle_already_active(callback)
            elif action == "shop_gifts":
                await self._handle_gifts_section(callback)
            elif action == "back_to_shop":
                await self._handle_back_to_shop(callback, user_id, chat_id)

        except Exception as e:
            self.logger.error(f"Error in shop callback handler: {e}")
            await self._handle_error(callback)

    async def _handle_purchase(self, callback: types.CallbackQuery, user_id: int, chat_id: int):
        """Обрабатывает попытку покупки товара с проверкой активных покупок"""
        item_id = int(callback.data.split("_")[2])
        item = ITEM_IDS.get(item_id)

        if not item:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return

        with self._db_session() as db:
            try:
                # ПЕРВАЯ ПРОВЕРКА: Проверяем, не активна ли уже привилегия
                if ShopRepository.has_active_purchase(db, user_id, item_id):
                    await callback.message.edit_text(
                        f"❌ <b>Эта привилегия уже активна!</b>\n\n"
                        f"📦 Товар: {item['name']}\n\n"
                        f"Вы не можете купить эту привилегию повторно, "
                        f"пока текущая активна.\n\n"
                        f"💡 Дождитесь окончания срока действия или "
                        f"используйте текущую привилегию.",
                        reply_markup=self._get_back_keyboard(),
                        parse_mode="HTML"
                    )
                    await callback.answer()
                    return

                # ВТОРАЯ ПРОВЕРКА: Проверяем, не куплен ли уже товар в этом чате
                if ShopRepository.has_user_purchased_in_chat(db, user_id, item_id, chat_id):
                    await callback.message.edit_text(
                        f"❌ <b>Этот товар уже куплен в этом чате!</b>\n\n"
                        f"📦 Товар: {item['name']}\n\n"
                        f"Вы уже приобрели этот товар в этом чате ранее.",
                        reply_markup=self._get_back_keyboard(),
                        parse_mode="HTML"
                    )
                    await callback.answer()
                    return

                # Получаем пользователя и проверяем баланс
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await callback.message.edit_text(
                        "❌ <b>Ошибка!</b> Пользователь не найден.",
                        reply_markup=self._get_back_keyboard(),
                        parse_mode="HTML"
                    )
                    return

                user_balance = user.coins

                # Проверяем достаточно ли средств
                if user_balance >= item["price"]:
                    # Совершаем покупку
                    user.coins -= item["price"]
                    ShopRepository.add_user_purchase(
                        db, user_id, item_id, item["name"], item["price"], chat_id
                    )
                    db.commit()

                    # Формируем сообщение об успехе
                    success_text = (
                        f"✅ <b>Покупка успешна!</b>\n\n"
                        f"📦 Товар: {item['name']}\n"
                        f"💰 Стоимость: {item['price_display']}\n"
                        f"💳 Списано: {item['price_display']}\n\n"
                        f"{item['benefit']}\n\n"
                        f"💎 Новый баланс: {self._format_number(user.coins)} монет"
                    )

                    await callback.message.edit_text(
                        success_text,
                        reply_markup=self._get_back_keyboard(),
                        parse_mode="HTML"
                    )

                    self.logger.info(f"User {user_id} purchased item {item_id} in chat {chat_id}")

                else:
                    # Недостаточно средств
                    missing_money = item["price"] - user_balance
                    await self._handle_insufficient_funds(callback, item, missing_money, user_id)

            except Exception as e:
                db.rollback()
                self.logger.error(f"Purchase error: {e}")
                raise

    async def _handle_insufficient_funds(self, callback: types.CallbackQuery, item: Dict,
                                         missing_money: int, user_id: int):
        """Обрабатывает случай недостатка средств"""
        missing_formatted = self._format_number(missing_money)

        try:
            # Пытаемся отправить уведомление в ЛС
            await callback.message.bot.send_message(
                user_id,
                f"❌ <b>Недостаточно средств</b>\n\n"
                f"📦 Товар: {item['name']}\n"
                f"💰 Не хватает: {missing_formatted} монет\n\n"
                f"💡 Пополните баланс и попробуйте снова!",
                parse_mode="HTML"
            )

            await callback.message.edit_text(
                "❌ <b>Недостаточно средств</b>\n\n"
                f"Информация отправлена в личные сообщения.",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )

        except Exception as e:
            # Если не удалось отправить в ЛС
            self.logger.warning(f"Could not send DM to user {user_id}: {e}")
            await callback.message.edit_text(
                f"❌ <b>Недостаточно средств!</b>\n\n"
                f"📦 Товар: {item['name']}\n"
                f"💰 Не хватает: {missing_formatted} монет\n\n"
                f"💡 <b>Разблокируйте бота в ЛС для получения уведомлений!</b>",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )

    async def _handle_already_purchased(self, callback: types.CallbackQuery):
        """Обрабатывает нажатие на уже купленный товар"""
        try:
            item_id = int(callback.data.split("_")[3])
            item = ITEM_IDS.get(item_id)

            if item:
                await callback.message.edit_text(
                    f"✅ <b>Товар уже куплен</b>\n\n"
                    f"📦 Товар: {item['name']}\n\n"
                    f"Вы уже приобрели этот товар. Привилегия активна! 🎉",
                    reply_markup=self._get_back_keyboard(),
                    parse_mode="HTML"
                )
                await callback.answer("✅ Уже куплено")
            else:
                await callback.message.edit_text(
                    "❌ Товар не найден",
                    reply_markup=self._get_back_keyboard(),
                    parse_mode="HTML"
                )
        except Exception as e:
            self.logger.error(f"Error in _handle_already_purchased: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при обработке запроса",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )

    async def _handle_gifts_section(self, callback: types.CallbackQuery):
        """Переходит в раздел подарков"""
        try:
            from handlers.gifts import gifts_section
            await gifts_section(callback)
        except ImportError:
            await callback.message.edit_text(
                "🎁 <b>Раздел подарков</b>\n\n"
                "Функция подарков временно недоступна.",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            self.logger.error(f"Error opening gifts section: {e}")
            await callback.message.edit_text(
                "❌ <b>Ошибка загрузки раздела подарков</b>",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )

    async def _handle_already_active(self, callback: types.CallbackQuery):
        """Обрабатывает нажатие на уже активный товар"""
        item_id = int(callback.data.split("_")[3])
        item = ITEM_IDS.get(item_id)

        if item:
            with self._db_session() as db:
                try:
                    # Получаем информацию о покупке
                    purchase = db.query(models.UserPurchase).filter(
                        models.UserPurchase.user_id == callback.from_user.id,
                        models.UserPurchase.item_id == item_id
                    ).first()

                    if purchase:
                        expires_text = ""
                        if purchase.expires_at:
                            from datetime import datetime
                            now = datetime.now()
                            if purchase.expires_at > now:
                                time_left = purchase.expires_at - now
                                days_left = time_left.days
                                hours_left = time_left.seconds // 3600

                                if days_left > 0:
                                    expires_text = f"\n⏰ Осталось: {days_left} дней {hours_left} часов"
                                else:
                                    expires_text = f"\n⏰ Осталось: {hours_left} часов"
                            else:
                                expires_text = "\n⚠️ Срок действия истек"
                        else:
                            expires_text = "\n⏰ Действует бессрочно"

                        await callback.message.edit_text(
                            f"✅ <b>Привилегия активна</b>\n\n"
                            f"📦 Товар: {item['name']}\n"
                            f"🛒 Куплено: {purchase.purchased_at.strftime('%d.%m.%Y %H:%M')}"
                            f"{expires_text}\n\n"
                            f"🎯 <b>Преимущество:</b>\n"
                            f"{item['benefit']}",
                            reply_markup=self._get_back_keyboard(),
                            parse_mode="HTML"
                        )
                        await callback.answer("✅ Привилегия активна")
                    else:
                        await callback.message.edit_text(
                            "❌ Информация о покупке не найдена",
                            reply_markup=self._get_back_keyboard(),
                            parse_mode="HTML"
                        )
                except Exception as e:
                    self.logger.error(f"Error in _handle_already_active: {e}")
                    await callback.message.edit_text(
                        "❌ Ошибка при получении информации о покупке",
                        reply_markup=self._get_back_keyboard(),
                        parse_mode="HTML"
                    )
        else:
            await callback.message.edit_text(
                "❌ Товар не найден",
                reply_markup=self._get_back_keyboard(),
                parse_mode="HTML"
            )

    async def _handle_back_to_shop(self, callback: types.CallbackQuery, user_id: int, chat_id: int):
        """Возвращает в главное меню магазина"""
        shop_text = self._get_shop_message_text(user_id, chat_id)
        keyboard = self._create_shop_keyboard(user_id, chat_id)

        await callback.message.edit_text(
            shop_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    async def _handle_error(self, callback: types.CallbackQuery):
        """Обрабатывает общие ошибки"""
        await callback.message.edit_text(
            "❌ <b>Произошла ошибка!</b>\n\n"
            "Пожалуйста, попробуйте позже или обратитесь к администратору.",
            reply_markup=self._get_back_keyboard(),
            parse_mode="HTML"
        )

    def _get_back_keyboard(self) -> InlineKeyboardMarkup:
        """Создает клавиатуру с кнопкой возврата"""
        return InlineKeyboardMarkup().add(
            InlineKeyboardButton("⬅️ Назад в магазин", callback_data="back_to_shop")
        )


def register_shop_handlers(dp: Dispatcher):
    """Регистрация обработчиков магазина"""
    handler = ShopHandler()

    # Регистрация команд
    dp.register_message_handler(
        handler.shop_command,
        commands=["магазин", "shop"],
        state="*"
    )
    dp.register_message_handler(
        handler.shop_command,
        lambda m: m.text and m.text.lower() in ["магазин", "shop"],
        state="*"
    )

    # Регистрация callback обработчиков
    shop_callbacks = [
        "shop_buy_", "shop_already_bought_", "shop_already_active_",
        "shop_gifts", "back_to_shop"
    ]

    dp.register_callback_query_handler(
        handler.shop_callback_handler,
        lambda c: any(c.data.startswith(prefix) for prefix in shop_callbacks),
        state="*"
    )

    logging.info("✅ Магазин обработчики зарегистрированы (с защитой от повторных покупок)")