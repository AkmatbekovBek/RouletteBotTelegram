# main_admin_handler.py

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from aiogram import types, Dispatcher
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher import FSMContext
from handlers.admin.mute_ban import MuteBanManager
from .admin_constants import ADMIN_IDS, BROADCAST_BATCH_SIZE, BROADCAST_DELAY, PRIVILEGES, SHOP_ITEMS
from .admin_helpers import (db_session, check_admin_async, get_all_admins_from_db, format_number,
                            get_gift_cancel_keyboard, get_gift_management_keyboard, get_broadcast_cancel_keyboard,
                            GiftAdminStates)
from .admin_notifications import send_admin_action_notification
from database.crud import UserRepository, TransactionRepository, GiftRepository, ShopRepository
from handlers.cleanup_scheduler import CleanupScheduler

logger = logging.getLogger(__name__)

class AdminHandler:
    """Основной класс для обработки административных команд"""
    def __init__(self):
        self.logger = logger
        self.broadcast_cancelled = False
        self.cleanup_scheduler = None
        self.mute_ban_manager = MuteBanManager()

    # ========== КОМАНДА ПОМОЩИ ==========
    async def admin_help(self, message: types.Message):
        """Показывает список админ-команд"""
        if not await check_admin_async(message):
            return
        all_admins = get_all_admins_from_db()
        total_admins = len(all_admins) + len(ADMIN_IDS)
        help_text = (
            "🛠 <b>Админ-панель</b>\n"
            "👮 <b>Модерация:</b>\n"
            "<code>/mute [время] [причина]</code> - Мут пользователя (ответом)\n"
            "<code>/unmute</code> - Снять мут (ответом)\n"
            "<code>/ban [время] [причина]</code> - Бан пользователя (ответом)\n"
            "<code>/unban [ID]</code> - Разбан пользователя\n"
            "<code>/kick [причина]</code> - Кик пользователя (ответом)\n"
            "💰 <b>Управление монетами:</b>\n"
            "<code>/admin_addcoins [ID] [amount]</code> - Добавить монеты\n"
            "<code>/admin_removecoins [ID] [amount]</code> - Забрать монеты\n"
            "<code>/admin_setcoins [ID] [amount]</code> - Установить точное количество\n"
            "👤 <b>Управление пользователями:</b>\n"
            "<code>/admin_info [ID]</code> - Информация о пользователе\n"
            "<code>/admin_find [username/имя]</code> - Поиск пользователя\n"
            "<code>/admin_unlimit [ID]</code> - Снять лимит переводов\n"
            "<code>/admin_limit [ID]</code> - Установить лимит переводов\n"
            "<code>/admin_add [ID]</code> - Добавить администратора\n"
            "<code>/admin_remove [ID]</code> - Удалить администратора\n"
            "<code>/admin_list</code> - Список администраторов\n"
            "🎁 <b>Управление подарками:</b>\n"
            "<code>/admin_gift_add</code> - Добавить новый подарок\n"
            "<code>/admin_gift_list</code> - Список всех подарков\n"
            "<code>/admin_gift_delete</code> - Удалить подарок\n"
            "🎯 <b>Управление привилегиями:</b>\n"
            "<code>/admin_give [ID] [привилегия] [дни]</code> - Выдать привилегию\n"
            "<code>/admin_remove_privilege [ID] [привилегия]</code> - Отобрать привилегию\n"
            "<code>/admin_privileges [ID]</code> - Показать привилегии пользователя\n"
            "<code>/admin_extend [ID] [привилегия] [дни]</code> - Продлить привилегию\n"
            "📋 <b>Доступные привилегии:</b>\n"
            "• <code>thief</code> - 👑 Вор в законе\n"
            "• <code>police</code> - 👮‍♂️ Полицейский\n"
            "• <code>unlimit</code> - 🔐 Снятие лимита перевода\n"
            "📊 <b>Статистика:</b>\n"
            "<code>/admin_stats</code> - Общая статистика бота\n"
            "<code>/admin_chats_stats</code> - Статистика по чатам\n"
            "<code>/admin_broadcast [текст]</code> - Рассылка пользователям\n"
            "<code>/admin_broadcast_chats [текст]</code> - Рассылка в чаты\n"
            "<code>/admin_broadcast_all [текст]</code> - Общая рассылка\n"
            "🧹 <b>Очистка:</b>\n"
            "<code>очистить базу</code> - Ручная очистка старых данных\n"
            "ℹ️ <b>Справка:</b>\n"
            "<code>/admin_help</code> - Показать это сообщение\n"
            "📝 <b>Примеры модерации:</b>\n"
            "• <code>/mute 30м спам</code> - Мут на 30 минут\n"
            "• <code>/ban 1d оскорбления</code> - Бан на 1 день\n"
            "• <code>/mute 2h флуд</code> - Мут на 2 часа\n"
            "• <code>/kick нарушение правил</code> - Кик\n"
            f"👑 Всего админов: <b>{total_admins}</b>"
        )
        await message.answer(help_text, parse_mode="HTML")

    # ========== УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ ==========
    async def add_admin(self, message: types.Message):
        """Добавляет нового администратора"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 1:
                await message.answer("❌ Использование: <code>/admin_add [ID пользователя]</code>", parse_mode="HTML")
                return
            new_admin_id = int(args[0])
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, new_admin_id)
                if not user:
                    await message.answer("❌ Пользователь не найден в базе данных")
                    return
                if user.is_admin:
                    await message.answer("ℹ️ Этот пользователь уже является администратором")
                    return
                UserRepository.update_admin_status(db, new_admin_id, True)
                db.commit()
                self.logger.info(f"Admin {message.from_user.id} added new admin {new_admin_id}")
                response = (
                    f"✅ <b>Пользователь добавлен в администраторы!</b>\n"
                    f"👤 ID: <code>{new_admin_id}</code>\n"
                    f"📛 Имя: {user.first_name or 'Не указано'}\n"
                    f"📱 Username: @{user.username or 'нет'}\n"
                    f"👑 Теперь у пользователя есть доступ к админ-панели"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in add_admin: {e}")
            await message.answer("❌ Произошла ошибка при добавлении администратора")

    async def remove_admin(self, message: types.Message):
        """Удаляет администратора"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 1:
                await message.answer("❌ Использование: <code>/admin_remove [ID администратора]</code>",
                                     parse_mode="HTML")
                return
            admin_id_to_remove = int(args[0])
            if admin_id_to_remove in ADMIN_IDS:
                await message.answer("❌ Нельзя удалить администратора из основного списка")
                return
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, admin_id_to_remove)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                if not user.is_admin:
                    await message.answer("❌ Этот пользователь не является администратором")
                    return
                UserRepository.update_admin_status(db, admin_id_to_remove, False)
                db.commit()
                self.logger.info(f"Admin {message.from_user.id} removed admin {admin_id_to_remove}")
                response = (
                    f"✅ <b>Администратор удален!</b>\n"
                    f"👤 ID: <code>{admin_id_to_remove}</code>\n"
                    f"📛 Имя: {user.first_name or 'Не указано'}\n"
                    f"📱 Username: @{user.username or 'нет'}\n"
                    f"👑 Пользователь больше не имеет доступа к админ-панели"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in remove_admin: {e}")
            await message.answer("❌ Произошла ошибка при удалении администратора")

    async def list_admins(self, message: types.Message):
        """Показывает список всех администраторов"""
        if not await check_admin_async(message):
            return
        try:
            with db_session() as db:
                admin_users = UserRepository.get_admin_users(db)
                admins_text = "👑 <b>Список администраторов</b>\n"
                # Основные администраторы
                admins_text += "🔐 <b>Основные администраторы:</b>\n"
                for admin_id in ADMIN_IDS:
                    user = UserRepository.get_user_by_telegram_id(db, admin_id)
                    if user:
                        admins_text += f"👑 ID: {admin_id} | {user.first_name or 'Без имени'} | @{user.username or 'нет'}"
                        if admin_id == message.from_user.id:
                            admins_text += " 👑 <b>(Вы)</b>"
                        admins_text += "\n"
                admins_text += "\n"
                # Дополнительные администраторы
                other_admins = [user for user in admin_users if user.telegram_id not in ADMIN_IDS]
                if other_admins:
                    admins_text += "👥 <b>Дополнительные администраторы:</b>\n"
                    for i, user in enumerate(other_admins, 1):
                        admins_text += f"{i}. ID: {user.telegram_id} | {user.first_name or 'Без имени'} | @{user.username or 'нет'}\n"
                else:
                    admins_text += "👥 <b>Дополнительные администраторы:</b>\nНет дополнительных админов\n"
                total_admins = len(admin_users) + len(ADMIN_IDS)
                admins_text += f"\n📊 Всего администраторов: {total_admins}"
                await message.answer(admins_text, parse_mode="HTML")
        except Exception as e:
            self.logger.error(f"Error in list_admins: {e}")
            await message.answer("❌ Произошла ошибка при получении списка администраторов")

    # ========== УПРАВЛЕНИЕ МОНЕТАМИ ==========
    async def _manage_coins(self, message: types.Message, operation: str):
        """Общий метод для управления монетами"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 2:
                commands = {
                    "addcoins": "/admin_addcoins [ID] [amount]",
                    "removecoins": "/admin_removecoins [ID] [amount]",
                    "setcoins": "/admin_setcoins [ID] [amount]"
                }
                await message.answer(f"❌ Использование: <code>{commands[operation]}</code>", parse_mode="HTML")
                return
            user_id = int(args[0])
            amount = int(args[1])
            if amount <= 0:
                await message.answer("❌ Сумма должна быть положительной")
                return
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                # Если пользователя нет - создаем его
                if not user:
                    try:
                        # Пытаемся получить информацию о пользователе через Telegram API
                        chat_member = await message.bot.get_chat(user_id)
                        username = chat_member.username
                        first_name = chat_member.first_name or "Пользователь"
                        user = UserRepository.create_user_safe(
                            db, user_id,
                            first_name=first_name,
                            username=username
                        )
                        self.logger.info(f"✅ Создан новый пользователь {user_id} для операции с монетами")
                    except Exception as user_info_error:
                        self.logger.warning(
                            f"Не удалось получить информацию о пользователе {user_id}: {user_info_error}")
                        user = UserRepository.create_user_safe(
                            db, user_id,
                            first_name="Пользователь",
                            username=None
                        )
                    # Обновляем текущие монеты после создания пользователя
                    user = UserRepository.get_user_by_telegram_id(db, user_id)

                current_coins = user.coins
                if operation == "addcoins":
                    new_coins = current_coins + amount
                    transaction_desc = "админ пополнение"
                    from_user, to_user = None, user_id
                elif operation == "removecoins":
                    if amount > current_coins:
                        await message.answer(f"❌ У пользователя только {format_number(current_coins)} монет")
                        return
                    new_coins = current_coins - amount
                    transaction_desc = "админ снятие"
                    from_user, to_user = user_id, None
                else:  # setcoins
                    new_coins = amount
                    difference = amount - current_coins
                    if difference == 0:
                        await message.answer("ℹ️ Баланс пользователя уже установлен на эту сумму")
                        return
                    transaction_desc = "админ установка баланса"
                    from_user, to_user = (None, user_id) if difference > 0 else (user_id, None)
                    amount = abs(difference)

                UserRepository.update_user_balance(db, user_id, new_coins)
                if operation != "setcoins" or amount != 0:
                    TransactionRepository.create_transaction(
                        db=db,
                        from_user_id=from_user,
                        to_user_id=to_user,
                        amount=amount,
                        description=transaction_desc
                    )
                db.commit()
                self.logger.info(f"Admin {message.from_user.id} {operation} {amount} coins for user {user_id}")

                # Отправляем уведомление пользователю
                if operation == "addcoins":
                    await send_admin_action_notification(
                        message.bot,
                        user_id,
                        "add_coins",
                        amount=amount,
                        new_balance=new_coins
                    )

                operation_names = {
                    "addcoins": "добавлено",
                    "removecoins": "забрано",
                    "setcoins": "установлено"
                }
                response = (
                    f"✅ <b>Операция выполнена успешно!</b>\n"
                    f"👤 Пользователь: <code>{user_id}</code>\n"
                    f"💰 Было: {format_number(current_coins)} | Стало: {format_number(new_coins)}\n"
                    f"📊 {operation_names[operation].title()}: {format_number(amount)} монет"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID и сумма должны быть числами")
        except Exception as e:
            self.logger.error(f"Error in {operation}: {e}")
            await message.answer("❌ Произошла ошибка при выполнении операции")

    async def add_coins(self, message: types.Message):
        """Добавить монеты пользователю"""
        await self._manage_coins(message, "addcoins")

    async def remove_coins(self, message: types.Message):
        """Забрать монеты у пользователя"""
        await self._manage_coins(message, "removecoins")

    async def set_coins(self, message: types.Message):
        """Установить точное количество монет"""
        await self._manage_coins(message, "setcoins")

    # ========== УПРАВЛЕНИЕ ПОДАРКАМИ ==========
    async def admin_gift_add_start(self, message: types.Message):
        """Начало процесса добавления подарка"""
        if not await check_admin_async(message):
            return
        await message.answer(
            "➕ <b>Добавление нового подарка</b>\n"
            "Введите название подарка:",
            reply_markup=get_gift_cancel_keyboard(),
            parse_mode="HTML"
        )
        await GiftAdminStates.waiting_for_gift_name.set()

    async def admin_gift_add_name(self, message: types.Message, state: FSMContext):
        """Обработка названия подарка"""
        if not message.text or len(message.text.strip()) < 2:
            await message.answer("❌ Название должно содержать минимум 2 символа. Введите снова:")
            return
        await state.update_data(name=message.text.strip())
        await message.answer(
            "📎 Введите стикер или эмодзи для подарка:\n"
            "Пример: 🌹, 🎁, 🍫, ❤️",
            reply_markup=get_gift_cancel_keyboard()
        )
        await GiftAdminStates.waiting_for_gift_sticker.set()

    async def admin_gift_add_sticker(self, message: types.Message, state: FSMContext):
        """Обработка стикера подарка"""
        if not message.text or len(message.text.strip()) == 0:
            await message.answer("❌ Стикер не может быть пустым. Введите снова:")
            return
        await state.update_data(sticker=message.text.strip())
        await message.answer(
            "💰 Введите цену подарка (в монетах):\n"
            "Пример: 1000, 500, 2500",
            reply_markup=get_gift_cancel_keyboard()
        )
        await GiftAdminStates.waiting_for_gift_price.set()

    async def admin_gift_add_price(self, message: types.Message, state: FSMContext):
        """Обработка цены подарка"""
        try:
            price = int(message.text)
            if price <= 0:
                await message.answer("❌ Цена должна быть положительной! Введите снова:")
                return
            await state.update_data(price=price)
            await message.answer(
                "💝 Введите комплимент при дарении:\n"
                "Можно использовать переменные:\n"
                "<code>{giver}</code> - имя дарителя\n"
                "<code>{receiver}</code> - имя получателя\n"
                "Пример: \"<code>{giver}</code> дарит <code>{receiver}</code> прекрасный подарок! 💖\"",
                reply_markup=get_gift_cancel_keyboard(),
                parse_mode="HTML"
            )
            await GiftAdminStates.waiting_for_gift_compliment.set()
        except ValueError:
            await message.answer("❌ Введите корректное число!")

    async def admin_gift_add_compliment(self, message: types.Message, state: FSMContext):
        """Обработка комплимента и создание подарка"""
        if not message.text or len(message.text.strip()) < 5:
            await message.answer("❌ Комплимент должен содержать минимум 5 символов. Введите снова:")
            return
        data = await state.get_data()
        data['compliment'] = message.text.strip()
        with db_session() as db:
            try:
                gift = GiftRepository.create_gift(
                    db,
                    name=data['name'],
                    sticker=data['sticker'],
                    price=data['price'],
                    compliment=data['compliment']
                )
                db.commit()
                response = (
                    f"✅ <b>Подарок успешно создан!</b>\n"
                    f"🎁 Название: {gift.name}\n"
                    f"📎 Стикер: {gift.sticker}\n"
                    f"💰 Цена: {format_number(gift.price)} монет\n"
                    f"💝 Комплимент: {gift.compliment}"
                )
                await message.answer(
                    response,
                    reply_markup=get_gift_management_keyboard(),
                    parse_mode="HTML"
                )
            except Exception as e:
                db.rollback()
                self.logger.error(f"Database error creating gift: {e}")
                await message.answer("❌ Ошибка базы данных при создании подарка")
        await state.finish()

    async def admin_gift_list(self, message: types.Message):
        """Показать список всех подарков"""
        if not await check_admin_async(message):
            return
        with db_session() as db:
            gifts = GiftRepository.get_all_gifts(db)
            if not gifts:
                await message.answer(
                    "📊 <b>Список подарков</b>\n"
                    "Подарков пока нет...\n"
                    "Добавьте первый подарок командой /admin_gift_add",
                    parse_mode="HTML"
                )
                return
            gifts_text = "📊 <b>Список подарков</b>\n"
            for i, gift in enumerate(gifts, 1):
                gifts_text += f"{i}. 🎁 <b>{gift.name}</b>\n"
                gifts_text += f"   📎 {gift.sticker} | 💰 {format_number(gift.price)} монет\n"
                gifts_text += f"   💝 {gift.compliment}\n"
            await message.answer(
                gifts_text,
                reply_markup=get_gift_management_keyboard(),
                parse_mode="HTML"
            )

    async def admin_gift_delete_start(self, message: types.Message):
        """Начало процесса удаления подарка"""
        if not await check_admin_async(message):
            return
        with db_session() as db:
            gifts = GiftRepository.get_all_gifts(db)
            if not gifts:
                await message.answer("❌ Нет подарков для удаления!")
                return
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            for gift in gifts:
                keyboard.add(types.InlineKeyboardButton(
                    text=f"🗑️ {gift.name}",
                    callback_data=f"admin_gift_delete_{gift.id}"
                ))
            keyboard.add(types.InlineKeyboardButton("❌ Отмена", callback_data="admin_gift_cancel"))
            await message.answer(
                "🗑️ <b>Удаление подарка</b>\n"
                "Выберите подарок для удаления:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

    async def admin_gift_delete_confirm(self, callback: types.CallbackQuery):
        """Подтверждение удаления подарка"""
        try:
            gift_id = int(callback.data.split("_")[3])
            with db_session() as db:
                gift = GiftRepository.get_gift_by_id(db, gift_id)
                if gift:
                    GiftRepository.delete_gift(db, gift_id)
                    db.commit()
                    await callback.message.edit_text(
                        f"✅ Подарок \"{gift.name}\" успешно удален!",
                        reply_markup=get_gift_management_keyboard()
                    )
                else:
                    await callback.message.edit_text(
                        "❌ Подарок не найден!",
                        reply_markup=get_gift_management_keyboard()
                    )
        except (ValueError, IndexError) as e:
            self.logger.error(f"Invalid gift ID format: {e}")
            await callback.message.edit_text("❌ Неверный формат ID подарка")
        except Exception as e:
            self.logger.error(f"Error in admin_gift_delete_confirm: {e}")
            await callback.message.edit_text("❌ Произошла ошибка при удалении подарка")
        await callback.answer()

    # ========== УПРАВЛЕНИЕ ПРИВИЛЕГИЯМИ ==========
    async def give_privilege(self, message: types.Message):
        """Выдать привилегию пользователю"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) < 2:
                await self._show_privilege_help(message, "give")
                return
            user_id = int(args[0])
            privilege_type = args[1].lower()
            days = int(args[2]) if len(args) > 2 else PRIVILEGES.get(privilege_type, {}).get("default_days", 30)
            if privilege_type not in PRIVILEGES:
                await message.answer("❌ Неизвестный тип привилегии")
                return
            privilege = PRIVILEGES[privilege_type]
            if days < 0:
                await message.answer("❌ Количество дней не может быть отрицательным")
                return
            # ИСПРАВЛЕНИЕ: Для unlimit устанавливаем days = 0
            if privilege_type == "unlimit":
                days = 0  # Для снятия лимита всегда навсегда
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                # Если пользователя нет - создаем его
                if not user:
                    try:
                        chat_member = await message.bot.get_chat(user_id)
                        username = chat_member.username
                        first_name = chat_member.first_name or "Пользователь"
                        user = UserRepository.create_user_safe(db, user_id, first_name, username)
                        self.logger.info(f"✅ Создан новый пользователь {user_id} для выдачи привилегии")
                    except Exception as user_info_error:
                        self.logger.warning(
                            f"Не удалось получить информацию о пользователе {user_id}: {user_info_error}")
                        user = UserRepository.create_user_safe(db, user_id, "Пользователь", None)
                    user = UserRepository.get_user_by_telegram_id(db, user_id)

                user_purchases = ShopRepository.get_user_purchases(db, user_id)
                # ИСПРАВЛЕНИЕ: Проверяем по правильному ID привилегии
                if privilege["id"] in user_purchases:
                    await message.answer(f"ℹ️ У пользователя уже есть привилегия '{privilege['name']}'")
                    return

                # ИСПРАВЛЕНИЕ: Сохраняем с правильным ID
                ShopRepository.add_user_purchase(
                    db,
                    user_id,
                    privilege["id"],  # Теперь для unlimit это 3, для thief - 1
                    privilege["name"],
                    days if privilege["extendable"] else 0  # Для unlimit сохраняем 0
                )
                db.commit()

                # ИСПРАВЛЕНИЕ: Создаем копию privilege с реальным количеством дней
                privilege_with_days = privilege.copy()
                privilege_with_days['actual_days'] = days

                # Отправляем уведомление пользователю
                await send_admin_action_notification(
                    message.bot,
                    user_id,
                    "privilege",
                    privilege_info=privilege_with_days  # ← ПЕРЕДАЕМ С РЕАЛЬНЫМИ ДНЯМИ
                )

                self.logger.info(f"Admin {message.from_user.id} gave {privilege['name']} to user {user_id}")
                duration_text = f"{days} дней" if days > 0 else "навсегда"
                response = (
                    f"✅ <b>Привилегия успешно выдана!</b>\n"
                    f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"🎁 Привилегия: {privilege['name']}\n"
                    f"⏰ Срок: {duration_text}\n"
                    f"👮‍♂️ Выдал: {message.from_user.first_name}"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID и дни должны быть числами")
        except Exception as e:
            self.logger.error(f"Error in give_privilege: {e}")
            await message.answer("❌ Произошла ошибка при выдаче привилегии")


    async def remove_privilege(self, message: types.Message):
        """Отобрать привилегию у пользователя"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 2:
                await self._show_privilege_help(message, "remove")
                return
            user_id = int(args[0])
            privilege_type = args[1].lower()
            if privilege_type not in PRIVILEGES:
                await message.answer("❌ Неизвестный тип привилегии")
                return
            privilege = PRIVILEGES[privilege_type]
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                user_purchases = ShopRepository.get_user_purchases(db, user_id)
                if privilege["id"] not in user_purchases:
                    await message.answer(f"ℹ️ У пользователя нет привилегии '{privilege['name']}'")
                    return
                ShopRepository.remove_user_purchase(db, user_id, privilege["id"])
                db.commit()
                self.logger.info(f"Admin {message.from_user.id} removed {privilege['name']} from user {user_id}")
                response = (
                    f"✅ <b>Привилегия успешно отобрана!</b>\n"
                    f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"🎁 Привилегия: {privilege['name']}\n"
                    f"👮‍♂️ Отобрал: {message.from_user.first_name}"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in remove_privilege: {e}")
            await message.answer("❌ Произошла ошибка при отборе привилегии")

    async def list_privileges(self, message: types.Message):
        """Показать привилегии пользователя"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 1:
                await message.answer("❌ Использование: <code>/admin_privileges [ID пользователя]</code>",
                                     parse_mode="HTML")
                return
            user_id = int(args[0])
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                user_purchases_ids = ShopRepository.get_user_purchases(db, user_id)
                if not user_purchases_ids:
                    await message.answer(f"ℹ️ У пользователя {user_id} нет привилегий")
                    return
                privileges_text = f"🎁 <b>Привилегии пользователя</b> {user_id}\n"
                privileges_text += f"👤 Имя: {user.first_name or 'Не указано'}\n"
                privileges_text += f"📱 Username: @{user.username or 'нет'}\n"
                # Получаем детали привилегий
                from sqlalchemy import text
                result = db.execute(
                    text("SELECT item_id, item_name FROM user_purchases WHERE user_id = :user_id"),
                    {"user_id": user_id}
                ).fetchall()
                for item_id, item_name in result:
                    privileges_text += f"• {item_name}\n"
                privileges_text += f"\n📊 Всего привилегий: {len(user_purchases_ids)}"
                await message.answer(privileges_text, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in list_privileges: {e}")
            await message.answer("❌ Произошла ошибка при получении привилегий")

    async def extend_privilege(self, message: types.Message):
        """Продлить привилегию пользователю"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 3:
                await self._show_privilege_help(message, "extend")
                return
            user_id = int(args[0])
            privilege_type = args[1].lower()
            days = int(args[2])
            if privilege_type not in PRIVILEGES:
                await message.answer("❌ Неизвестный тип привилегии")
                return
            privilege = PRIVILEGES[privilege_type]
            if not privilege["extendable"]:
                await message.answer(f"❌ Привилегию '{privilege['name']}' нельзя продлить")
                return
            if days <= 0:
                await message.answer("❌ Количество дней должно быть положительным")
                return
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                success = ShopRepository.extend_user_purchase(db, user_id, privilege["id"], days)
                if success:
                    db.commit()
                    self.logger.info(
                        f"Admin {message.from_user.id} extended {privilege['name']} for user {user_id} by {days} days")
                    # Отправляем уведомление пользователю
                    # ИСПРАВЛЕНИЕ: Создаем копию privilege с реальным количеством дней
                    privilege_with_days = privilege.copy()
                    privilege_with_days['actual_days'] = days

                    # Отправляем уведомление пользователю
                    await send_admin_action_notification(
                        message.bot,
                        user_id,
                        "privilege",
                        privilege_info=privilege_with_days
                    )
                    response = (
                        f"✅ <b>Привилегия успешно продлена!</b>\n"
                        f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                        f"🆔 ID: <code>{user_id}</code>\n"
                        f"🎁 Привилегия: {privilege['name']}\n"
                        f"📈 Продлено на: {days} дней\n"
                        f"👮‍♂️ Продлил: {message.from_user.first_name}"
                    )
                    await message.answer(response, parse_mode="HTML")
                else:
                    await message.answer(f"❌ У пользователя нет привилегии '{privilege['name']}' или произошла ошибка")
        except ValueError:
            await message.answer("❌ Неверный формат. ID и дни должны быть числами")
        except Exception as e:
            self.logger.error(f"Error in extend_privilege: {e}")
            await message.answer("❌ Произошла ошибка при продлении привилегии")

    async def _show_privilege_help(self, message: types.Message, command: str):
        """Показывает справку по командам привилегий"""
        help_texts = {
            "give": "❌ Использование: <code>/admin_give [ID] [привилегия] [дни]</code>\n",
            "remove": "❌ Использование: <code>/admin_remove_privilege [ID] [привилегия]</code>\n",
            "extend": "❌ Использование: <code>/admin_extend [ID] [привилегия] [дни]</code>\n"
        }
        help_text = help_texts[command] + "📋 <b>Доступные привилегии:</b>\n"
        for priv_type, priv_info in PRIVILEGES.items():
            help_text += f"• <code>{priv_type}</code> - {priv_info['name']}"
            if command == "extend" and not priv_info['extendable']:
                help_text += " (не продлевается)"
            help_text += "\n"
        help_text += "\n📝 <b>Примеры:</b>\n"
        if command == "give":
            help_text += (
                "<code>/admin_give 123456 thief</code>\n"
                "<code>/admin_give 123456 police 60</code>\n"
                "<code>/admin_give 123456 unlimit</code>"
            )
        elif command == "remove":
            help_text += (
                "<code>/admin_remove_privilege 123456 thief</code>\n"
                "<code>/admin_remove_privilege 123456 unlimit</code>"
            )
        else:  # extend
            help_text += (
                "<code>/admin_extend 123456 thief 30</code>\n"
                "<code>/admin_extend 123456 police 60</code>"
            )
        await message.answer(help_text, parse_mode="HTML")

    # ========== СТАТИСТИКА И ИНФОРМАЦИЯ ==========
    async def user_info(self, message: types.Message):
        """Информация о пользователе"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 1:
                await message.answer("❌ Использование: <code>/admin_info [ID]</code>", parse_mode="HTML")
                return
            user_id = int(args[0])
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                user_purchases = ShopRepository.get_user_purchases(db, user_id)
                has_unlimited = PRIVILEGES["unlimit"]["id"] in user_purchases
                info_text = (
                    f"👤 <b>Информация о пользователе</b> #{user_id}\n"
                    f"📛 Имя: {user.first_name or 'Не указано'}\n"
                    f"📱 Username: @{user.username or 'Не указан'}\n"
                    f"💰 Баланс: {format_number(user.coins)} монет\n"
                    f"🎯 Выиграно: {format_number(user.win_coins or 0)} монет\n"
                    f"💸 Проиграно: {format_number(user.defeat_coins or 0)} монет\n"
                    f"📈 Макс. выигрыш: {format_number(user.max_win_coins or 0)} монет\n"
                    f"♾️ Безлимитные переводы: {'✅ Да' if has_unlimited else '❌ Нет'}\n"
                    f"👑 Админ: {'✅ Да' if user.is_admin else '❌ Нет'}\n"
                )
                if hasattr(user, 'created_at') and user.created_at:
                    info_text += f"📅 Зарегистрирован: {user.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                await message.answer(info_text, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in user_info: {e}")
            await message.answer("❌ Произошла ошибка")

    async def bot_stats(self, message: types.Message):
        """Общая статистика бота"""
        if not await check_admin_async(message):
            return
        with db_session() as db:
            total_users = UserRepository.get_total_users_count(db)
            total_coins = UserRepository.get_total_coins_sum(db)
            admin_users = UserRepository.get_admin_users(db)
            all_users = UserRepository.get_all_users(db)
            rich_users = sorted(all_users, key=lambda u: u.coins, reverse=True)[:5]
            stats_text = "📊 <b>Статистика бота</b>\n"
            stats_text += f"👥 Всего пользователей: {format_number(total_users)}\n"
            stats_text += f"💰 Всего монет в системе: {format_number(total_coins)}\n"
            stats_text += f"👑 Администраторов: {len(admin_users)}\n"
            if rich_users:
                stats_text += "🏆 <b>Топ-5 по балансу:</b>\n"
                for i, user in enumerate(rich_users, 1):
                    display_name = user.first_name or user.username or f"Пользователь {user.telegram_id}"
                    admin_status = " 👑" if user.is_admin else ""
                    stats_text += f"{i}. {display_name} - {format_number(user.coins)} монет{admin_status}\n"
            else:
                stats_text += "🏆 Пока нет данных о пользователях\n"
            await message.answer(stats_text, parse_mode="HTML")

    async def get_chats_stats(self, message: types.Message):
        """Статистика по чатам"""
        if not await check_admin_async(message):
            return
        with db_session() as db:
            all_chats = UserRepository.get_all_chats(db)
            active_chats = UserRepository.get_active_chats(db, days_active=7)
            stats_text = "📊 <b>Статистика чатов</b>\n"
            stats_text += f"👥 Всего чатов в базе: {len(all_chats)}\n"
            stats_text += f"🔔 Активных чатов: {len(active_chats)}\n"
            if all_chats:
                chat_stats = []
                for chat_id in all_chats[:15]:
                    info = UserRepository.get_chat_info(db, chat_id)
                    chat_stats.append((chat_id, info['members_count'], info['is_active'], info['title']))
                chat_stats.sort(key=lambda x: x[1], reverse=True)
                stats_text += "🏆 <b>Топ чатов по участникам:</b>\n"
                for i, (chat_id, members_count, is_active, title) in enumerate(chat_stats[:10], 1):
                    status = "🟢" if is_active else "🔴"
                    chat_title = title if title != 'Неизвестно' else f"Чат {chat_id}"
                    stats_text += f"{i}. {chat_title} | 👥 {members_count} {status}\n"
            await message.answer(stats_text, parse_mode="HTML")

    # ========== РАССЫЛКИ ==========
    async def _broadcast_message(self, message: types.Message, target_type: str):
        """Общий метод для рассылки сообщений"""
        if not await check_admin_async(message):
            return
        text = message.get_args()
        if not text:
            usage_commands = {
                "users": "/admin_broadcast [текст]",
                "chats": "/admin_broadcast_chats [текст]",
                "all": "/admin_broadcast_all [текст]"
            }
            await message.answer(f"❌ Использование: <code>{usage_commands[target_type]}</code>", parse_mode="HTML")
            return
        try:
            with db_session() as db:
                if target_type == "users":
                    recipients = UserRepository.get_all_users(db)
                    recipient_ids = [user.telegram_id for user in recipients]
                    recipient_type = "пользователей"
                    broadcast_type = ""
                elif target_type == "chats":
                    recipient_ids = UserRepository.get_all_chats(db)
                    recipient_type = "чатов"
                    broadcast_type = "_chats"
                else:  # all
                    users = UserRepository.get_all_users(db)
                    chats = UserRepository.get_all_chats(db)
                    recipient_ids = [user.telegram_id for user in users] + chats
                    recipient_type = "получателей"
                    broadcast_type = "_all"
                total = len(recipient_ids)
                if total == 0:
                    await message.answer(f"❌ Нет {recipient_type} для рассылки")
                    return
                status_msg = await message.answer(
                    f"📢 Начинаю рассылку для {format_number(total)} {recipient_type}...\n"
                    f"⏳ Обработано: 0/{format_number(total)}\n"
                    f"✅ Успешно: 0\n"
                    f"❌ Ошибок: 0",
                    reply_markup=get_broadcast_cancel_keyboard(broadcast_type)
                )
                success_count = 0
                failed_count = 0
                self.broadcast_cancelled = False
                for i, recipient_id in enumerate(recipient_ids, 1):
                    if self.broadcast_cancelled:
                        break
                    try:
                        await message.bot.send_message(
                            chat_id=recipient_id,
                            text=f"📢 Рассылка от администратора:\n{text}"
                        )
                        success_count += 1
                        await asyncio.sleep(BROADCAST_DELAY)
                    except Exception as e:
                        self.logger.warning(f"Не удалось отправить сообщение {recipient_id}: {e}")
                        failed_count += 1
                    # Обновляем статус каждые N получателей
                    if i % BROADCAST_BATCH_SIZE == 0 or i == total:
                        try:
                            await status_msg.edit_text(
                                f"📢 Рассылка для {format_number(total)} {recipient_type}...\n"
                                f"⏳ Обработано: {format_number(i)}/{format_number(total)}\n"
                                f"✅ Успешно: {format_number(success_count)}\n"
                                f"❌ Ошибок: {format_number(failed_count)}",
                                reply_markup=get_broadcast_cancel_keyboard(broadcast_type)
                            )
                        except Exception as e:
                            self.logger.error(f"Ошибка при обновлении статуса: {e}")
                if self.broadcast_cancelled:
                    result_text = (
                        f"❌ Рассылка отменена!\n"
                        f"📊 Итоги:\n"
                        f"👥 Всего {recipient_type}: {format_number(total)}\n"
                        f"⏳ Обработано: {format_number(i)}\n"
                        f"✅ Успешно: {format_number(success_count)}\n"
                        f"❌ Ошибок: {format_number(failed_count)}"
                    )
                else:
                    delivery_rate = (success_count / total) * 100 if total > 0 else 0
                    result_text = (
                        f"✅ Рассылка завершена!\n"
                        f"📊 Итоги:\n"
                        f"👥 Всего {recipient_type}: {format_number(total)}\n"
                        f"✅ Успешно: {format_number(success_count)}\n"
                        f"❌ Не удалось: {format_number(failed_count)}\n"
                        f"📈 Процент доставки: {delivery_rate:.1f}%"
                    )
                await status_msg.edit_text(result_text)
        except Exception as e:
            self.logger.error(f"Error in broadcast {target_type}: {e}")
            await message.answer(f"❌ Произошла ошибка при рассылке: {e}")

    async def broadcast_message(self, message: types.Message):
        """Рассылка пользователям"""
        await self._broadcast_message(message, "users")

    async def broadcast_to_chats(self, message: types.Message):
        """Рассылка в чаты"""
        await self._broadcast_message(message, "chats")

    async def broadcast_to_all(self, message: types.Message):
        """Общая рассылка"""
        await self._broadcast_message(message, "all")

    # ========== ПОИСК И ОЧИСТКА ==========
    async def find_user(self, message: types.Message):
        """Поиск пользователя по имени или username"""
        if not await check_admin_async(message):
            return
        search_term = message.get_args()
        if not search_term:
            await message.answer("❌ Использование: <code>/admin_find [имя/username]</code>", parse_mode="HTML")
            return
        with db_session() as db:
            found_users = UserRepository.search_users(db, search_term)
            if not found_users:
                await message.answer("❌ Пользователи не найдены")
                return
            result_text = f"🔍 <b>Результаты поиска по '{search_term}':</b>\n"
            for user in found_users[:10]:
                user_id = user.telegram_id
                name = user.first_name or 'Не указано'
                username = f"@{user.username}" if user.username else "Нет username"
                coins = format_number(user.coins)
                admin_status = " 👑" if user.is_admin else ""
                result_text += f"🆔 {user_id} | {name} | {username} | {coins} монет{admin_status}\n"
            if len(found_users) > 10:
                result_text += f"\n... и еще {len(found_users) - 10} пользователей"
            await message.answer(result_text, parse_mode="HTML")

    async def remove_transfer_limit(self, message: types.Message):
        """Снимает лимит переводов для пользователя"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 1:
                await message.answer("❌ Использование: <code>/admin_unlimit [ID пользователя]</code>",
                                     parse_mode="HTML")
                return
            user_id = int(args[0])
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                user_purchases = ShopRepository.get_user_purchases(db, user_id)
                if SHOP_ITEMS["unlimited_transfers"] in user_purchases:
                    await message.answer("ℹ️ У пользователя уже снят лимит переводов")
                    return
                # ИСПРАВЛЕНИЕ: Используем правильный ID и название
                ShopRepository.add_user_purchase(
                    db,
                    user_id,
                    SHOP_ITEMS["unlimited_transfers"],  # Теперь это 3
                    PRIVILEGES["unlimit"]["name"],  # "🔐 Снятие лимита перевода"
                    0
                )
                db.commit()
                self.logger.info(f"Admin {message.from_user.id} removed transfer limit for user {user_id}")
                # Отправляем уведомление пользователю ТОЛЬКО о снятии лимита
                await send_admin_action_notification(
                    message.bot,
                    user_id,
                    "unlimit",
                    privilege_info=PRIVILEGES["unlimit"]
                )
                response = (
                    f"✅ <b>Лимит переводов успешно снят!</b>\n"
                    f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                    f"📱 Username: @{user.username or 'нет'}\n"
                    f"💰 Текущий баланс: {format_number(user.coins)} монет\n"
                    f"♾️ Теперь пользователь может переводить неограниченные суммы"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in remove_transfer_limit: {e}")
            await message.answer("❌ Произошла ошибка при снятии лимита")

    async def manual_cleanup(self, message: types.Message):
        """Ручная очистка данных"""
        if not await check_admin_async(message):
            return
        if self.cleanup_scheduler is None:
            self.cleanup_scheduler = CleanupScheduler()
        try:
            result = await self.cleanup_scheduler.run_manual_cleanup()
            await message.answer(result)
        except Exception as e:
            self.logger.error(f"Error in manual_cleanup: {e}")
            await message.answer(f"❌ Ошибка при очистке: {e}")

    # ========== CALLBACK ОБРАБОТЧИКИ ==========
    async def handle_gift_cancel(self, callback: types.CallbackQuery, state: FSMContext):
        """Отмена операций с подарками"""
        try:
            if state:
                await state.finish()
            await callback.message.edit_text(
                "❌ Операция отменена.",
                reply_markup=get_gift_management_keyboard()
            )
        except Exception as e:
            self.logger.error(f"Error in handle_gift_cancel: {e}")
            await callback.answer("❌ Ошибка при отмене операции")
        finally:
            await callback.answer()

    async def handle_gift_add_more(self, callback: types.CallbackQuery):
        """Добавить еще один подарок"""
        try:
            await callback.message.edit_text(
                "➕ <b>Добавление нового подарка</b>\n"
                "Введите название подарка:",
                reply_markup=get_gift_cancel_keyboard(),
                parse_mode="HTML"
            )
            await GiftAdminStates.waiting_for_gift_name.set()
        except Exception as e:
            self.logger.error(f"Error in handle_gift_add_more: {e}")
            await callback.answer("❌ Ошибка при начале добавления подарка")
        finally:
            await callback.answer()

    async def handle_gift_list_cmd(self, callback: types.CallbackQuery):
        """Показать список подарков через callback"""
        try:
            with db_session() as db:
                gifts = GiftRepository.get_all_gifts(db)
                if not gifts:
                    await callback.message.edit_text(
                        "📊 <b>Список подарков</b>\n"
                        "Подарков пока нет...\n"
                        "Добавьте первый подарок:",
                        reply_markup=types.InlineKeyboardMarkup().add(
                            types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_gift_add_more")
                        ),
                        parse_mode="HTML"
                    )
                    return
                gifts_text = "📊 <b>Список подарков</b>\n"
                for i, gift in enumerate(gifts, 1):
                    gifts_text += f"{i}. 🎁 <b>{gift.name}</b>\n"
                    gifts_text += f"   📎 {gift.sticker} | 💰 {format_number(gift.price)} монет\n"
                    gifts_text += f"   💝 {gift.compliment}\n"
                await callback.message.edit_text(
                    gifts_text,
                    reply_markup=get_gift_management_keyboard(),
                    parse_mode="HTML"
                )
        except Exception as e:
            self.logger.error(f"Error in handle_gift_list_cmd: {e}")
            await callback.answer("❌ Ошибка при загрузке списка подарков")
        finally:
            await callback.answer()

    async def handle_broadcast_cancel(self, callback: types.CallbackQuery):
        """Обработчик отмены рассылки"""
        if not await check_admin_async(callback.message):
            await callback.answer("❌ У вас нет прав для отмены рассылки", show_alert=True)
            return
        self.broadcast_cancelled = True
        await callback.answer("❌ Рассылка будет отменена", show_alert=True)

    async def add_transfer_limit(self, message: types.Message):
        """Устанавливает лимит переводов для пользователя"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) != 1:
                await message.answer("❌ Использование: <code>/admin_limit [ID пользователя]</code>",
                                     parse_mode="HTML")
                return
            user_id = int(args[0])
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                user_purchases = ShopRepository.get_user_purchases(db, user_id)
                # ИСПРАВЛЕНИЕ: Проверяем по правильному ID
                if SHOP_ITEMS["unlimited_transfers"] not in user_purchases:
                    await message.answer("ℹ️ У пользователя уже установлен лимит переводов")
                    return
                # ИСПРАВЛЕНИЕ: Удаляем по правильному ID
                ShopRepository.remove_user_purchase(db, user_id, SHOP_ITEMS["unlimited_transfers"])
                db.commit()
                self.logger.info(f"Admin {message.from_user.id} added transfer limit for user {user_id}")
                response = (
                    f"✅ <b>Лимит переводов успешно установлен!</b>\n"
                    f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                    f"📱 Username: @{user.username or 'нет'}\n"
                    f"💰 Текущий баланс: {format_number(user.coins)} монет\n"
                    f"📏 Теперь пользователь ограничен в переводах стандартными лимитами"
                )
                await message.answer(response, parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный формат. ID должен быть числом")
        except Exception as e:
            self.logger.error(f"Error in add_transfer_limit: {e}")
            await message.answer("❌ Произошла ошибка при установке лимита")

    async def admin_give_reward(self, message: types.Message):
        """Выдать монеты и привилегию одновременно"""
        if not await check_admin_async(message):
            return
        try:
            args = message.get_args().split()
            if len(args) < 3:
                await message.answer(
                    "❌ Использование: <code>/admin_reward [ID] [сумма] [привилегия]</code>\n"
                    "📋 Доступные привилегии:\n"
                    "• <code>thief</code> - 👑 Вор в законе\n"
                    "• <code>police</code> - 👮‍♂️ Полицейский\n"
                    "• <code>unlimit</code> - 🔐 Снятие лимита\n"
                    "📝 Примеры:\n"
                    "<code>/admin_reward 123456 5000000 thief</code>\n"
                    "<code>/admin_reward 123456 10000000 unlimit</code>",
                    parse_mode="HTML"
                )
                return
            user_id = int(args[0])
            amount = int(args[1])
            privilege_type = args[2].lower()
            if amount <= 0:
                await message.answer("❌ Сумма должна быть положительной")
                return
            if privilege_type not in PRIVILEGES:
                await message.answer("❌ Неизвестный тип привилегии")
                return
            privilege = PRIVILEGES[privilege_type]
            with db_session() as db:
                user = UserRepository.get_user_by_telegram_id(db, user_id)
                if not user:
                    await message.answer("❌ Пользователь не найден")
                    return
                # Добавляем монеты
                current_coins = user.coins
                new_coins = current_coins + amount
                UserRepository.update_user_balance(db, user_id, new_coins)
                # Создаем транзакцию
                TransactionRepository.create_transaction(
                    db=db,
                    from_user_id=None,
                    to_user_id=user_id,
                    amount=amount,
                    description="админ награда"
                )
                # Выдаем привилегию
                user_purchases = ShopRepository.get_user_purchases(db, user_id)
                privilege_given = False
                if privilege["id"] not in user_purchases:
                    ShopRepository.add_user_purchase(
                        db,
                        user_id,
                        privilege["id"],
                        privilege["name"],
                        privilege["default_days"] if privilege["extendable"] else 0
                    )
                    privilege_given = True
                else:
                    # Если привилегия уже есть - продлеваем если можно
                    if privilege["extendable"]:
                        ShopRepository.extend_user_purchase(
                            db,
                            user_id,
                            privilege["id"],
                            privilege["default_days"]
                        )
                        privilege_given = True

                db.commit()
                # Отправляем уведомление админу
                admin_response = (
                    f"✅ <b>Награда успешно выдана!</b>\n"
                    f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"💰 Сумма: {format_number(amount)} монет\n"
                    f"💳 Новый баланс: {format_number(new_coins)} монет\n"
                    f"🎁 Привилегия: {privilege['name']}"
                )
                await message.answer(admin_response, parse_mode="HTML")
                # Отправляем красивое уведомление в ЛС пользователю
                await send_admin_action_notification(
                    message.bot,
                    user_id,
                    "coins_and_privilege",
                    amount=amount,
                    new_balance=new_coins,
                    privilege_info=privilege
                )
                self.logger.info(f"Admin {message.from_user.id} gave reward to user {user_id}")
        except ValueError:
            await message.answer("❌ Неверный формат. ID и сумма должны быть числами")
        except Exception as e:
            self.logger.error(f"Error in admin_give_reward: {e}")
            await message.answer("❌ Произошла ошибка при выдаче награды")

    async def _ensure_user_exists(self, db, user_id: int, bot=None) -> bool:
        """Гарантирует что пользователь существует в базе"""
        user = UserRepository.get_user_by_telegram_id(db, user_id)
        if user:
            return True
        try:
            # Пытаемся получить информацию о пользователе
            first_name = "Пользователь"
            username = None
            if bot:
                try:
                    chat_member = await bot.get_chat(user_id)
                    first_name = chat_member.first_name or "Пользователь"
                    username = chat_member.username
                except Exception as chat_error:
                    self.logger.warning(f"Could not get chat info for {user_id}: {chat_error}")
            UserRepository.create_user_safe(db, user_id, first_name, username)
            self.logger.info(f"✅ Создан новый пользователь {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания пользователя {user_id}: {e}")
            return False

def register_admin_handlers(dp: Dispatcher):
    """Регистрирует все админ-обработчики"""
    handler = AdminHandler()
    # Группировка команд для лучшей читаемости
    # Основные команды
    dp.register_message_handler(handler.admin_help, Command("admin_help"))
    dp.register_message_handler(handler.admin_help, Command("admin"))
    # Управление монетами
    dp.register_message_handler(handler.add_coins, Command("admin_addcoins"))
    dp.register_message_handler(handler.remove_coins, Command("admin_removecoins"))
    dp.register_message_handler(handler.set_coins, Command("admin_setcoins"))
    # Управление пользователями
    dp.register_message_handler(handler.user_info, Command("admin_info"))
    dp.register_message_handler(handler.find_user, Command("admin_find"))
    dp.register_message_handler(handler.remove_transfer_limit, Command("admin_unlimit"))
    dp.register_message_handler(handler.add_transfer_limit, Command("admin_limit"))
    dp.register_message_handler(handler.add_admin, Command("admin_add"))
    dp.register_message_handler(handler.remove_admin, Command("admin_remove"))
    dp.register_message_handler(handler.list_admins, Command("admin_list"))
    # Статистика
    dp.register_message_handler(handler.bot_stats, Command("admin_stats"))
    dp.register_message_handler(handler.get_chats_stats, Command("admin_chats_stats"))
    # Рассылки
    dp.register_message_handler(handler.broadcast_message, Command("admin_broadcast"))
    dp.register_message_handler(handler.broadcast_to_chats, Command("admin_broadcast_chats"))
    dp.register_message_handler(handler.broadcast_to_all, Command("admin_broadcast_all"))
    # Управление подарками
    dp.register_message_handler(handler.admin_gift_add_start, Command("admin_gift_add"))
    dp.register_message_handler(handler.admin_gift_list, Command("admin_gift_list"))
    dp.register_message_handler(handler.admin_gift_delete_start, Command("admin_gift_delete"))
    # Управление привилегиями
    dp.register_message_handler(handler.give_privilege, Command("admin_give"))
    dp.register_message_handler(handler.remove_privilege, Command("admin_remove_privilege"))
    dp.register_message_handler(handler.list_privileges, Command("admin_privileges"))
    dp.register_message_handler(handler.extend_privilege, Command("admin_extend"))
    # Комбинированные действия
    dp.register_message_handler(handler.admin_give_reward, Command("admin_reward"))
    # Очистка
    dp.register_message_handler(
        handler.manual_cleanup,
        lambda m: m.text and m.text.lower().strip() in ["очистить базу", "cleanup", "очистка"]
    )
    # FSM обработчики для подарков
    dp.register_message_handler(handler.admin_gift_add_name, state=GiftAdminStates.waiting_for_gift_name)
    dp.register_message_handler(handler.admin_gift_add_sticker, state=GiftAdminStates.waiting_for_gift_sticker)
    dp.register_message_handler(handler.admin_gift_add_price, state=GiftAdminStates.waiting_for_gift_price)
    dp.register_message_handler(handler.admin_gift_add_compliment, state=GiftAdminStates.waiting_for_gift_compliment)
    # Callback обработчики
    callbacks = [
        (handler.handle_gift_cancel, lambda c: c.data == "admin_gift_cancel"),
        (handler.handle_gift_add_more, lambda c: c.data == "admin_gift_add_more"),
        (handler.handle_gift_list_cmd, lambda c: c.data == "admin_gift_list_cmd"),
        (handler.admin_gift_delete_confirm, lambda c: c.data.startswith("admin_gift_delete_")),
        (handler.handle_broadcast_cancel,
         lambda c: c.data in ["cancel_broadcast", "cancel_broadcast_chats", "cancel_broadcast_all"])
    ]
    for handler_func, filter_func in callbacks:
        dp.register_callback_query_handler(handler_func, filter_func, state="*")
    print("✅ Админ обработчики зарегистрированы (разделённая версия)")