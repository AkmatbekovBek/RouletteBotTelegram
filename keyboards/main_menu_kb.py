from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_inline_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Профиль", callback_data="profile"),
        InlineKeyboardButton("Рулетка", callback_data="roulette"),
        InlineKeyboardButton("Ссылки", callback_data="links"),
        InlineKeyboardButton("Рефералы", callback_data="reference"),
        InlineKeyboardButton("Магазин", callback_data="shop"),
        InlineKeyboardButton("Подарки", callback_data="gifts"),
        InlineKeyboardButton("Другие боты", callback_data="other_bots"),
        InlineKeyboardButton("Донат", callback_data="donate"),
        InlineKeyboardButton("🛠️ Тех. поддержка", callback_data="support"),
        InlineKeyboardButton("📄 Пользовательское соглашение", callback_data="agreement"),
        InlineKeyboardButton("🤝 Сотрудничество", callback_data="cooperation"),

    )

    return keyboard
