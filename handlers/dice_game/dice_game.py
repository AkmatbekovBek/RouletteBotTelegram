import logging
import random
import asyncio
from aiogram import types, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import get_db
from database.crud import UserRepository
from contextlib import contextmanager
from config import bot

logger = logging.getLogger(__name__)

# Конфигурация игры
DICE_GAME_CONFIG = {
    'single_bet_min': 100,
    'single_bet_max': 100000,
    'double_bet_min': 200,
    'double_bet_max': 200000,
    'single_multiplier': 6,
    'double_multiplier': 12,
    'partial_multiplier': 3
}

# ВАШИ СТИКЕРЫ КУБИКОВ
DICE_STICKERS = {
    1: "CAACAgIAAxkBAAEUA9dpHI2ocRRS6CFKaYjlvi-wpVGZfQAC3MYBAAFji0YMsbUSFEouGv82BA",
    2: "CAACAgIAAxkBAAEUA9lpHI2tuZJ8VVe-NmSvcB_kb_Q6ZgAC3cYBAAFji0YM608pO-wjAlE2BA",
    3: "CAACAgIAAxkBAAEUA9tpHI2xgDxYRolKxChx5c2FV3BKqwAC3sYBAAFji0YMVHH9hav7ILk2BA",
    4: "CAACAgIAAxkBAAEUA91pHI21f82e-GSmVPN6h9FjHuNLIQAC38YBAAFji0YMHEUTINW7Yxc2BA",
    5: "CAACAgIAAxkBAAEUA99pHI24gud3GBq_TR7ZOEuLIrhE2AAC4MYBAAFji0YMSLHz-sj_Jqk2BA",
    6: "CAACAgIAAxkBAAEUA-FpHI27WLW_E9HKZUe6orzkryBQxQAC4cYBAAFji0YM75p8zae_tHo2BA"
}


@contextmanager
def db_session():
    """Контекстный менеджер для работы с БД"""
    db = next(get_db())
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class DiceGameHandler:
    """Обработчик игры в кубики со стикерами"""

    def __init__(self):
        self.logger = logger

    async def _send_dice_sticker(self, chat_id: int, dice_value: int):
        """Отправляет стикер кубика"""
        try:
            sticker_file_id = DICE_STICKERS.get(dice_value)
            if sticker_file_id:
                await bot.send_sticker(chat_id=chat_id, sticker=sticker_file_id)
            else:
                dice_emojis = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
                await bot.send_message(chat_id=chat_id, text=dice_emojis.get(dice_value, "🎲"))
        except Exception as e:
            self.logger.error(f"Error sending dice sticker: {e}")

    def _get_main_keyboard(self) -> InlineKeyboardMarkup:
        """Клавиатура главного меню игры"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🎲 1 кубик", callback_data="dice_single"),
            InlineKeyboardButton("🎲🎲 2 кубика", callback_data="dice_double")
        )
        keyboard.add(InlineKeyboardButton("📊 Правила", callback_data="dice_rules"))
        keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_donate"))
        return keyboard

    def _get_bet_keyboard(self, mode: str) -> InlineKeyboardMarkup:
        """Клавиатура для выбора ставки"""
        keyboard = InlineKeyboardMarkup(row_width=3)

        if mode == "single":
            bets = [100, 500, 1000, 5000, 10000, 50000]
        else:
            bets = [200, 1000, 2000, 10000, 20000, 100000]

        buttons = []
        for bet in bets:
            buttons.append(InlineKeyboardButton(f"{bet:,}", callback_data=f"dice_bet_{mode}_{bet}"))

        for i in range(0, len(buttons), 3):
            keyboard.row(*buttons[i:i + 3])

        keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="dice_back"))
        return keyboard

    def _get_number_keyboard(self, mode: str, bet: int) -> InlineKeyboardMarkup:
        """Клавиатура для выбора числа"""
        keyboard = InlineKeyboardMarkup(row_width=3)

        if mode == "single":
            numbers = list(range(1, 7))
            buttons = [InlineKeyboardButton(f"🎲 {i}", callback_data=f"dice_play_single_{bet}_{i}") for i in numbers]
        else:
            numbers = list(range(2, 13))
            buttons = [InlineKeyboardButton(f"🎯 {i}", callback_data=f"dice_play_double_{bet}_{i}") for i in numbers]

        for i in range(0, len(buttons), 3):
            keyboard.row(*buttons[i:i + 3])

        keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"dice_mode_{mode}"))
        return keyboard

    def _get_rules_text(self) -> str:
        """Текст с правилами игры"""
        return (
            "🎲 <b>Правила игры «Кубик»</b>\n\n"
            "📊 <b>Режим «1 кубик»:</b>\n"
            "• Ставка: от 100 до 100,000 монет\n"
            "• Угадай число от 1 до 6\n"
            "• Выигрыш: <b>x6</b> от ставки\n\n"
            "🎯 <b>Режим «2 кубика»:</b>\n"
            "• Ставка: от 200 до 200,000 монет\n"
            "• Угадай сумму двух кубиков (2-12)\n"
            "• Выигрыш: <b>x12</b> от ставки\n"
            "• Частичный выигрыш (один кубик): <b>x3</b>\n\n"
            "💰 <b>Шансы:</b>\n"
            "• 1 кубик: 1 из 6 (16.67%)\n"
            "• 2 кубика: разные вероятности\n\n"
            "🎮 <b>Удачи в игре!</b>"
        )

    async def dice_command(self, message: types.Message):
        """Обработчик команды игры в кубики"""
        text = (
            "🎲 <b>Игра «Кубик»</b>\n\n"
            "Испытай удачу с настоящими кубиками! 🎯\n\n"
            "<b>Доступные режимы:</b>\n"
            "• 🎲 1 кубик — классика\n"
            "• 🎲🎲 2 кубика — больше азарта\n\n"
            "Выбери режим и начни игру!"
        )

        await message.answer(text, reply_markup=self._get_main_keyboard(), parse_mode="HTML")

    async def dice_callback_handler(self, callback: types.CallbackQuery):
        """Обработчик callback'ов игры"""
        action = callback.data
        user_id = callback.from_user.id

        try:
            if action == "dice_back":
                await self._show_main_menu(callback)
            elif action == "dice_rules":
                await self._show_rules(callback)
            elif action == "dice_single":
                await self._show_single_mode(callback)
            elif action == "dice_double":
                await self._show_double_mode(callback)
            elif action.startswith("dice_mode_"):
                mode = action.split("_")[2]
                await self._show_bet_selection(callback, mode)
            elif action.startswith("dice_bet_"):
                parts = action.split("_")
                mode = parts[2]
                bet = int(parts[3])
                await self._show_number_selection(callback, mode, bet)
            elif action.startswith("dice_play_"):
                parts = action.split("_")
                mode = parts[2]
                bet = int(parts[3])
                number = int(parts[4])
                await self._play_game(callback, mode, bet, number)

        except Exception as e:
            self.logger.error(f"Error in dice callback handler: {e}")
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    async def _show_main_menu(self, callback: types.CallbackQuery):
        """Показывает главное меню игры"""
        text = "🎲 <b>Игра «Кубик»</b>\n\nВыберите режим игры:"
        await callback.message.edit_text(text, reply_markup=self._get_main_keyboard(), parse_mode="HTML")
        await callback.answer()

    async def _show_rules(self, callback: types.CallbackQuery):
        """Показывает правила игры"""
        await callback.message.edit_text(
            self._get_rules_text(),
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="dice_back")
            ),
            parse_mode="HTML"
        )
        await callback.answer()

    async def _show_single_mode(self, callback: types.CallbackQuery):
        """Показывает режим одного кубика"""
        text = (
            "🎲 <b>Режим «1 кубик»</b>\n\n"
            "• Угадай число от 1 до 6\n"
            "• Выигрыш: <b>x6</b> от ставки\n"
            "• Шанс выигрыша: 1 из 6 (16.67%)\n\n"
            "Выберите ставку:"
        )
        await callback.message.edit_text(text, reply_markup=self._get_bet_keyboard("single"), parse_mode="HTML")
        await callback.answer()

    async def _show_double_mode(self, callback: types.CallbackQuery):
        """Показывает режим двух кубиков"""
        text = (
            "🎲🎲 <b>Режим «2 кубика»</b>\n\n"
            "• Угадай сумму двух кубиков (2-12)\n"
            "• Выигрыш: <b>x12</b> от ставки\n"
            "• Частичный выигрыш: <b>x3</b>\n\n"
            "Выберите ставку:"
        )
        await callback.message.edit_text(text, reply_markup=self._get_bet_keyboard("double"), parse_mode="HTML")
        await callback.answer()

    async def _show_bet_selection(self, callback: types.CallbackQuery, mode: str):
        """Показывает выбор ставки"""
        if mode == "single":
            min_bet = DICE_GAME_CONFIG['single_bet_min']
            max_bet = DICE_GAME_CONFIG['single_bet_max']
            text = f"🎲 Выберите ставку (от {min_bet:,} до {max_bet:,} монет):"
        else:
            min_bet = DICE_GAME_CONFIG['double_bet_min']
            max_bet = DICE_GAME_CONFIG['double_bet_max']
            text = f"🎲🎲 Выберите ставку (от {min_bet:,} до {max_bet:,} монет):"

        await callback.message.edit_text(text, reply_markup=self._get_bet_keyboard(mode), parse_mode="HTML")
        await callback.answer()

    async def _show_number_selection(self, callback: types.CallbackQuery, mode: str, bet: int):
        """Показывает выбор числа"""
        with db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, callback.from_user.id)
            if not user or user.coins < bet:
                await callback.answer("❌ Недостаточно монет", show_alert=True)
                return

        if mode == "single":
            text = f"🎲 Ставка: <b>{bet:,} монет</b>\n\nВыберите число от 1 до 6:"
        else:
            text = f"🎲🎲 Ставка: <b>{bet:,} монет</b>\n\nВыберите сумму двух кубиков (2-12):"

        await callback.message.edit_text(text, reply_markup=self._get_number_keyboard(mode, bet), parse_mode="HTML")
        await callback.answer()

    async def _play_game(self, callback: types.CallbackQuery, mode: str, bet: int, selected_number: int):
        """Игровая логика со ставками"""
        with db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, callback.from_user.id)

            if not user or user.coins < bet:
                await callback.answer("❌ Недостаточно монет", show_alert=True)
                return

            # Снимаем ставку
            user.coins -= bet

            # Генерируем результат
            if mode == "single":
                dice_result = random.randint(1, 6)
                win_amount = await self._calculate_single_win(bet, selected_number, dice_result)

                # Отправляем стикер кубика
                await self._send_dice_sticker(callback.message.chat.id, dice_result)
                await asyncio.sleep(1)

                result_text = await self._get_single_result_text(bet, selected_number, dice_result, win_amount)
            else:
                dice1 = random.randint(1, 6)
                dice2 = random.randint(1, 6)
                dice_result = dice1 + dice2
                win_amount = await self._calculate_double_win(bet, selected_number, dice1, dice2)

                # Отправляем стикеры двух кубиков
                await self._send_dice_sticker(callback.message.chat.id, dice1)
                await asyncio.sleep(0.5)
                await self._send_dice_sticker(callback.message.chat.id, dice2)
                await asyncio.sleep(1)

                result_text = await self._get_double_result_text(bet, selected_number, dice1, dice2, win_amount)

            # Начисляем выигрыш
            if win_amount > 0:
                user.coins += win_amount

            # Сохраняем изменения
            db.commit()

            # Показываем результат
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🎲 Играть снова", callback_data=f"dice_mode_{mode}"),
                InlineKeyboardButton("⬅️ В меню", callback_data="dice_back")
            )

            await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

    async def _calculate_single_win(self, bet: int, selected: int, result: int) -> int:
        """Рассчитывает выигрыш для одного кубика"""
        if selected == result:
            return bet * DICE_GAME_CONFIG['single_multiplier']
        return 0

    async def _calculate_double_win(self, bet: int, selected: int, dice1: int, dice2: int) -> int:
        """Рассчитывает выигрыш для двух кубиков"""
        result = dice1 + dice2

        if selected == result:
            return bet * DICE_GAME_CONFIG['double_multiplier']
        elif selected in [dice1, dice2]:
            return bet * DICE_GAME_CONFIG['partial_multiplier']
        return 0

    async def _get_single_result_text(self, bet: int, selected: int, result: int, win_amount: int) -> str:
        """Текст результата для одного кубика"""
        if win_amount > 0:
            return (
                f"🎉 <b>ПОБЕДА!</b>\n\n"
                f"🎲 Выпало: <b>{result}</b>\n"
                f"🎯 Ваша ставка: <b>{selected}</b>\n"
                f"💰 Ставка: <b>{bet:,} монет</b>\n"
                f"🏆 Выигрыш: <b>{win_amount:,} монет</b>\n\n"
                f"💎 Баланс пополнен!"
            )
        else:
            return (
                f"😔 <b>Не повезло...</b>\n\n"
                f"🎲 Выпало: <b>{result}</b>\n"
                f"🎯 Ваша ставка: <b>{selected}</b>\n"
                f"💰 Ставка: <b>{bet:,} монет</b>\n\n"
                f"💫 Попробуйте еще раз!"
            )

    async def _get_double_result_text(self, bet: int, selected: int, dice1: int, dice2: int, win_amount: int) -> str:
        """Текст результата для двух кубиков"""
        result = dice1 + dice2

        if win_amount > 0:
            if selected == result:
                win_type = "🎉 <b>ПОЛНАЯ ПОБЕДА!</b>"
                win_desc = f"Угадана сумма: <b>{result}</b>"
            else:
                win_type = "🎯 <b>ЧАСТИЧНАЯ ПОБЕДА!</b>"
                win_desc = f"Угадан один кубик: <b>{selected}</b>"

            return (
                f"{win_type}\n\n"
                f"🎲🎲 Выпало: <b>{dice1}</b> + <b>{dice2}</b> = <b>{result}</b>\n"
                f"{win_desc}\n"
                f"💰 Ставка: <b>{bet:,} монет</b>\n"
                f"🏆 Выигрыш: <b>{win_amount:,} монет</b>\n\n"
                f"💎 Баланс пополнен!"
            )
        else:
            return (
                f"😔 <b>Не повезло...</b>\n\n"
                f"🎲🎲 Выпало: <b>{dice1}</b> + <b>{dice2}</b> = <b>{result}</b>\n"
                f"🎯 Ваша ставка: <b>{selected}</b>\n"
                f"💰 Ставка: <b>{bet:,} монет</b>\n\n"
                f"💫 Попробуйте еще раз!"
            )




def register_dice_handlers(dp: Dispatcher):
    """Регистрация обработчиков игры в кубики"""
    handler = DiceGameHandler()

    # Регистрация команд для ЛЮБЫХ чатов
    dp.register_message_handler(
        handler.dice_command,
        commands=["кубик", "dice"],
        state="*"
    )
    dp.register_message_handler(
        handler.dice_command,
        lambda m: m.text and m.text.strip().lower() in ["кубик", "dice", "игра", "кости"],
        state="*"
    )

    # Регистрация callback обработчиков
    dice_callbacks = [
        "dice_back", "dice_rules", "dice_single", "dice_double",
        "dice_mode_", "dice_bet_", "dice_play_"
    ]

    dp.register_callback_query_handler(
        handler.dice_callback_handler,
        lambda c: any(c.data.startswith(prefix) for prefix in dice_callbacks),
        state="*"
    )

    logging.info("✅ Игра 'Кубик' зарегистрирована (работает везде)")