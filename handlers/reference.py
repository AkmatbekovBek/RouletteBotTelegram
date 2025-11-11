import binascii
import os
from aiogram import types, Dispatcher
from aiogram.utils.deep_linking import get_start_link
from config import bot
from database import get_db
from database.crud import UserRepository, ReferenceRepository
from const import REFERENCE_MENU_TEXT, REFERENCE_LINK_TEXT
from keyboards.reference_keyboard import reference_menu_keyboard


async def reference_menu_call(call: types.CallbackQuery):
    await bot.send_message(
        chat_id=call.message.chat.id,
        text=REFERENCE_MENU_TEXT,
        reply_markup=reference_menu_keyboard(),
        parse_mode=types.ParseMode.MARKDOWN
    )


async def reference_link_call(call: types.CallbackQuery):
    db = next(get_db())
    try:
        user = UserRepository.get_user_by_telegram_id(db, call.from_user.id)

        if not user or not user.reference_link:
            token = binascii.hexlify(os.urandom(4)).decode()
            link = await get_start_link(payload=token)
            UserRepository.update_reference_link(db, call.from_user.id, link)
        else:
            link = user.reference_link

        await bot.send_message(
            chat_id=call.message.chat.id,
            text=REFERENCE_LINK_TEXT.format(link=link)
        )
    except Exception as e:
        print(f"❌ Ошибка создания реферальной ссылки: {e}")
    finally:
        db.close()


async def reference_list_call(call: types.CallbackQuery):
    db = next(get_db())
    try:
        references = ReferenceRepository.get_user_references(db, call.from_user.id)

        if references:
            data = []
            for ref in references:
                # Получаем данные пользователя по ID
                user_data = UserRepository.get_user_by_telegram_id(db, ref.reference_telegram_id)
                if user_data:
                    # Создаем кликабельную ссылку на пользователя
                    username = user_data.username or user_data.first_name or "Неизвестный"
                    data.append(f"[{username}](tg://user?id={ref.reference_telegram_id})")
                else:
                    data.append(f"[Неизвестный пользователь](tg://user?id={ref.reference_telegram_id})")

            text = "👥 *Ваши рефералы:*\n\n" + '\n'.join(data)
            await call.message.reply(text, parse_mode=types.ParseMode.MARKDOWN)
        else:
            await call.message.reply('У вас нет рефералов', parse_mode=types.ParseMode.MARKDOWN)

    except Exception as e:
        print(f"❌ Ошибка получения списка рефералов: {e}")
        await call.message.reply('❌ Ошибка при получении списка рефералов')
    finally:
        db.close()


def register_reference_handlers(dp: Dispatcher):
    dp.register_callback_query_handler(reference_menu_call, lambda call: call.data == "reference_menu")
    dp.register_callback_query_handler(reference_link_call, lambda call: call.data == "reference_link")
    dp.register_callback_query_handler(reference_list_call, lambda call: call.data == "referral_list")