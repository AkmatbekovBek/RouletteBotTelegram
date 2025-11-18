from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_inline_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)

    # Первый ряд
    keyboard.add(
        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        InlineKeyboardButton("🎰 Рулетка", callback_data="roulette")
    )

    # Второй ряд
    keyboard.add(
        InlineKeyboardButton("🔗 Ссылки", callback_data="links"),
        InlineKeyboardButton("👥 Рефералы", callback_data="reference")
    )

    # Третий ряд
    keyboard.add(
        InlineKeyboardButton("🛍️ Магазин", callback_data="shop"),
        InlineKeyboardButton("🎁 Подарки", callback_data="gifts")
    )

    # Четвертый ряд
    keyboard.add(
        InlineKeyboardButton("🤖 Другие боты", callback_data="other_bots"),
        InlineKeyboardButton("💎 Донат", callback_data="donate")
    )

    # Пятый ряд
    keyboard.add(
        InlineKeyboardButton("🎲 Кубик", callback_data="dice_game")
    )

    # Шестой ряд
    keyboard.add(
        InlineKeyboardButton("🛠️ Тех. поддержка", callback_data="support")
    )

    # Седьмой ряд
    keyboard.add(
        InlineKeyboardButton("📄 Пользовательское соглашение", callback_data="agreement")
    )

    return keyboard