# handlers/record.py
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import Dispatcher
from database import SessionLocal
from database.models import User
from sqlalchemy import desc, func

TOP_CATEGORIES = {
    'balance': 'топ богатеев 💰',
    'max_win': 'макс. выигрыш 🎯',
    'max_loss': 'макс. проигрыш 😵',
    'max_bet': 'макс. ставка 🎲'
}

async def show_top_menu(message: types.Message):
    is_private = message.chat.type == 'private'
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton(text=name, callback_data=f'top_select:{key}:{int(is_private)}')
        for key, name in TOP_CATEGORIES.items()
    ]
    markup.add(*buttons)
    await message.answer("📊 Какой топ вас интересует?", reply_markup=markup)


async def process_top_selection(callback: types.CallbackQuery):
    parts = callback.data.split(':')
    if len(parts) != 3:
        return await callback.answer("❌ Ошибка", show_alert=True)

    _, category, is_private_str = parts
    is_private = bool(int(is_private_str))

    if category not in TOP_CATEGORIES:
        return await callback.answer("Некорректная категория", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    if is_private:
        top_users, user_rank, user_value = await get_global_top_with_user_rank(user_id, category)
        title = f"🌍 Глобальный {TOP_CATEGORIES[category]}"
    else:
        top_users, user_rank, user_value = await get_top_with_user_rank(chat_id, user_id, category)
        title = f"🏆 {TOP_CATEGORIES[category]} (этот чат)"

    lines = [f"{title}:\n"]
    for idx, (username, value) in enumerate(top_users, start=1):
        name = (username or "Аноним")[:15]
        # Единственное место, где формируем display_value
        display_value = abs(value) if category == 'max_loss' else value
        lines.append(f"{idx}. {name} — {display_value:,}")

    if user_rank is not None:
        user_name = (callback.from_user.full_name or "Аноним")[:15]
        display_user_value = abs(user_value) if category == 'max_loss' else user_value
        lines.append(f"\n🔽 Ваше место: #{user_rank} — {display_user_value:,}")

    await callback.message.edit_text("\n".join(lines), reply_markup=None)
    await callback.answer()


async def get_top_with_user_rank(chat_id: int, user_id: int, category: str):
    db = SessionLocal()
    try:
        column_map = {
            'balance': User.coins,
            'max_win': User.max_win_coins,
            'max_loss': User.min_win_coins,
            'max_bet': User.max_bet_coins
        }
        order_col = column_map[category]

        top_query = (
            db.query(User.username, order_col)
            .filter(User.chat_id == chat_id)
            .order_by(desc(order_col))
            .limit(10)
            .all()
        )
        top_users = [(u.username, getattr(u, category)) for u in top_query]

        # Без фильтра order_col > 0!
        subq = (
            db.query(
                User.tg_id,
                order_col.label('val'),
                func.row_number().over(order_by=desc(order_col)).label('rank')
            )
            .filter(User.chat_id == chat_id)
            .subquery()
        )
        user_row = db.query(subq.c.rank, subq.c.val).filter(subq.c.tg_id == user_id).first()

        return top_users, (user_row[0] if user_row else None), (user_row[1] if user_row else None)
    finally:
        db.close()


async def get_global_top_with_user_rank(user_id: int, category: str):
    db = SessionLocal()
    try:
        column_map = {
            'balance': User.coins,
            'max_win': User.max_win_coins,
            'max_loss': User.min_win_coins,
            'max_bet': User.max_bet_coins
        }
        order_col = column_map[category]

        top_query = (
            db.query(User.username, order_col)
            .order_by(desc(order_col))
            .limit(30)
            .all()
        )
        top_users = [(u.username, getattr(u, category)) for u in top_query]

        subq = (
            db.query(
                User.tg_id,
                order_col.label('val'),
                func.row_number().over(order_by=desc(order_col)).label('rank')
            )
            .subquery()
        )
        user_row = db.query(subq.c.rank, subq.c.val).filter(subq.c.tg_id == user_id).first()

        return top_users, (user_row[0] if user_row else None), (user_row[1] if user_row else None)
    finally:
        db.close()


def register_record_handlers(dp: Dispatcher):
    dp.register_message_handler(show_top_menu, commands=['top', 'топ'])
    dp.register_callback_query_handler(
        process_top_selection,
        lambda c: c.data.startswith('top_select:')
    )