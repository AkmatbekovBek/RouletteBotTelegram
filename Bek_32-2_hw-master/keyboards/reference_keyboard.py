from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def reference_menu_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🔗 Получить ссылку", callback_data="reference_link"),
        InlineKeyboardButton("📊 Список рефералов", callback_data="referral_list")
    )
    markup.add(InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    return markup