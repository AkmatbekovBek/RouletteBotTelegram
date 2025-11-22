# handlers/record.py
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import Dispatcher
from database import SessionLocal
from database.models import User, TelegramUser
from sqlalchemy import desc, func, or_
import asyncio

TOP_CATEGORIES = {
    'balance': 'топ богатеев 💰',
    'max_win': 'макс. выигрыш 🎯',
    'max_loss': 'макс. проигрыш 😵',
    'max_bet': 'макс. ставка 🎲'
}


async def show_top_menu(message: types.Message):
    is_private = message.chat.type == 'private'

    # Если это группа/супергруппа, регистрируем всех участников чата
    if not is_private:
        await register_all_chat_users(message.chat.id, message.bot)

    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton(text=name, callback_data=f'top_select:{key}:{int(is_private)}')
        for key, name in TOP_CATEGORIES.items()
    ]
    markup.add(*buttons)
    await message.answer("📊 Какой топ вас интересует?", reply_markup=markup)


async def register_all_chat_users(chat_id: int, bot):
    """Регистрирует всех участников чата в базе данных"""
    db = SessionLocal()
    try:
        print(f"🔄 Начинаем регистрацию всех пользователей чата {chat_id}")

        # Получаем список участников чата
        try:
            chat_members = await bot.get_chat_administrators(chat_id)
            # Добавляем обычных участников (админы уже в списке)
            all_members_count = await bot.get_chat_members_count(chat_id)
            print(f"👥 В чате {chat_id} всего участников: {all_members_count}")
        except Exception as e:
            print(f"❌ Не удалось получить список участников чата: {e}")
            return

        registered_count = 0
        processed_members = set()

        # Обрабатываем администраторов (они уже в списке chat_members)
        for member in chat_members:
            if member.user.is_bot:
                continue

            user_id = member.user.id
            if user_id in processed_members:
                continue

            processed_members.add(user_id)
            await register_single_user(db, user_id, chat_id, member.user.username, member.user.first_name)
            registered_count += 1

            # Небольшая задержка чтобы не перегружать API
            await asyncio.sleep(0.1)

        print(f"✅ Зарегистрировано {registered_count} пользователей из чата {chat_id}")

    except Exception as e:
        print(f"❌ Ошибка при регистрации пользователей чата: {e}")
    finally:
        db.close()


async def register_single_user(db, user_id: int, chat_id: int, username: str = None, first_name: str = None):
    """Регистрирует одного пользователя в чате"""
    try:
        # Проверяем существующего пользователя в этом чате
        user = db.query(User).filter(
            User.tg_id == user_id,
            User.chat_id == chat_id
        ).first()

        # Если пользователя нет в этом чате, создаем/обновляем запись
        if not user:
            # Ищем пользователя в таблице TelegramUser для копирования данных
            telegram_user = db.query(TelegramUser).filter(
                TelegramUser.telegram_id == user_id
            ).first()

            if telegram_user:
                # Создаем пользователя с данными из TelegramUser
                user = User(
                    tg_id=user_id,
                    chat_id=chat_id,
                    username=username or telegram_user.username or "",
                    coins=telegram_user.coins or 0,
                    win_coins=telegram_user.win_coins or 0,
                    defeat_coins=telegram_user.defeat_coins or 0,
                    max_win_coins=telegram_user.max_win_coins or 0,
                    min_win_coins=telegram_user.min_win_coins or 0,
                    max_bet_coins=telegram_user.max_bet or 0
                )
                print(f"✅ Создан пользователь {user_id} в чате {chat_id} с балансом {user.coins}")
            else:
                # Если пользователя нет в TelegramUser, создаем нового с нулями
                user = User(
                    tg_id=user_id,
                    chat_id=chat_id,
                    username=username or "",
                    coins=0,
                    win_coins=0,
                    defeat_coins=0,
                    max_win_coins=0,
                    min_win_coins=0,
                    max_bet_coins=0
                )
                print(f"✅ Создан новый пользователь {user_id} в чате {chat_id}")

            db.add(user)
            db.commit()
        else:
            # Если пользователь уже существует в этом чате, обновляем его данные из TelegramUser
            telegram_user = db.query(TelegramUser).filter(
                TelegramUser.telegram_id == user_id
            ).first()

            if telegram_user:
                # Обновляем данные из TelegramUser
                user.coins = telegram_user.coins or user.coins
                user.win_coins = telegram_user.win_coins or user.win_coins
                user.defeat_coins = telegram_user.defeat_coins or user.defeat_coins
                user.max_win_coins = telegram_user.max_win_coins or user.max_win_coins
                user.min_win_coins = telegram_user.min_win_coins or user.min_win_coins
                user.max_bet_coins = telegram_user.max_bet or user.max_bet_coins
                user.username = username or telegram_user.username or user.username
                db.commit()
                print(f"✅ Обновлены данные пользователя {user_id} в чате {chat_id}")

    except Exception as e:
        print(f"❌ Ошибка при регистрации пользователя {user_id}: {e}")
        db.rollback()


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

    # Если это группа, регистрируем всех пользователей чата
    if not is_private:
        await register_all_chat_users(chat_id, callback.bot)

    # Регистрируем текущего пользователя
    db = SessionLocal()
    try:
        await register_single_user(db, user_id, 0 if is_private else chat_id,
                                   callback.from_user.username, callback.from_user.first_name)
    finally:
        db.close()

    # Получаем топ
    if is_private:
        top_users, user_rank, user_value = await get_global_top_with_user_rank(user_id, category)
        title = f"🌍 Глобальный {TOP_CATEGORIES[category]}"
    else:
        top_users, user_rank, user_value = await get_top_with_user_rank(chat_id, user_id, category)
        title = f"🏆 {TOP_CATEGORIES[category]} (этот чат)"

    # Если топ пустой, показываем сообщение
    if not top_users:
        await callback.message.edit_text(
            f"😔 В {title.lower()} пока нет участников.\n\n"
            "Начните играть, чтобы попасть в топ!",
            reply_markup=None
        )
        return await callback.answer()

    lines = [f"{title}:\n"]
    for idx, (username, value) in enumerate(top_users, start=1):
        name = (username or "Аноним")[:15]
        display_value = abs(value) if category == 'max_loss' else value
        lines.append(f"{idx}. {name} — {display_value:,}")

    if user_rank is not None and user_value is not None:
        user_name = (callback.from_user.full_name or "Аноним")[:15]
        display_user_value = abs(user_value) if category == 'max_loss' else user_value
        lines.append(f"\n🔽 Ваше место: #{user_rank} — {display_user_value:,}")

    await callback.message.edit_text("\n".join(lines), reply_markup=None)
    await callback.answer()


async def get_top_with_user_rank(chat_id: int, user_id: int, category: str):
    db = SessionLocal()
    try:
        db.expire_all()
        field_map = {
            'balance': User.coins,
            'max_win': User.max_win_coins,
            'max_loss': User.min_win_coins,
            'max_bet': User.max_bet_coins
        }
        order_col = field_map[category]

        # Исключаем нулевые значения для некоторых категорий
        query = db.query(User.username, order_col).filter(User.chat_id == chat_id)

        # Для баланса показываем всех, для остальных категорий - только ненулевые значения
        if category != 'balance':
            query = query.filter(order_col != 0)

        top_query = query.order_by(desc(order_col)).limit(10).all()
        top_users = [(u.username, getattr(u, order_col.key)) for u in top_query]

        # Получаем ранг пользователя
        subq = (
            db.query(
                User.tg_id,
                order_col.label('val'),
                func.row_number().over(order_by=desc(order_col)).label('rank')
            )
            .filter(User.chat_id == chat_id)
        )
        if category != 'balance':
            subq = subq.filter(order_col != 0)

        subq = subq.subquery()
        user_row = db.query(subq.c.rank, subq.c.val).filter(subq.c.tg_id == user_id).first()

        return top_users, (user_row[0] if user_row else None), (user_row[1] if user_row else None)
    except Exception as e:
        print(f"❌ Ошибка в get_top_with_user_rank: {e}")
        return [], None, None
    finally:
        db.close()


async def get_global_top_with_user_rank(user_id: int, category: str):
    db = SessionLocal()
    try:
        field_map = {
            'balance': User.coins,
            'max_win': User.max_win_coins,
            'max_loss': User.min_win_coins,
            'max_bet': User.max_bet_coins
        }
        order_col = field_map[category]

        # Исключаем нулевые значения для некоторых категорий
        query = db.query(User.username, order_col)

        # Для баланса показываем всех, для остальных категорий - только ненулевые значения
        if category != 'balance':
            query = query.filter(order_col != 0)

        top_query = query.order_by(desc(order_col)).limit(30).all()
        top_users = [(u.username, getattr(u, order_col.key)) for u in top_query]

        # Получаем ранг пользователя
        subq = (
            db.query(
                User.tg_id,
                order_col.label('val'),
                func.row_number().over(order_by=desc(order_col)).label('rank')
            )
        )
        if category != 'balance':
            subq = subq.filter(order_col != 0)

        subq = subq.subquery()
        user_row = db.query(subq.c.rank, subq.c.val).filter(subq.c.tg_id == user_id).first()

        return top_users, (user_row[0] if user_row else None), (user_row[1] if user_row else None)
    except Exception as e:
        print(f"❌ Ошибка в get_global_top_with_user_rank: {e}")
        return [], None, None
    finally:
        db.close()


def register_record_handlers(dp: Dispatcher):
    # Регистрируем команды с префиксом и без (для русской команды)
    dp.register_message_handler(show_top_menu, commands=['top', 'топ'])

    # Дополнительная регистрация для русской команды без слеша
    dp.register_message_handler(show_top_menu, commands=['top', 'топ'], commands_prefix='!/')

    # Или альтернативный вариант - регистрируем как текстовый обработчик
    dp.register_message_handler(show_top_menu, content_types=['text'], text=['топ', 'Топ', 'ТОП'])

    dp.register_callback_query_handler(
        process_top_selection,
        lambda c: c.data.startswith('top_select:')
    )