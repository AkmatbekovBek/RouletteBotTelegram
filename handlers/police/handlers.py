# handlers/police/handlers.py
import re
from datetime import datetime, timedelta  # ← добавь timedelta сюда
from datetime import datetime
from aiogram import types
from database import get_db
from datetime import datetime
from handlers.police.service import PoliceService


def normalize_cmd(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"^[/!]", "", text)
    text = re.sub(r"@[\w_]+$", "", text)
    return text.strip().lower().split()[0]


def is_arrest_cmd(msg: types.Message):
    return normalize_cmd(msg.text) == "арест"


def is_check_cmd(msg: types.Message):
    return normalize_cmd(msg.text) in ["проверить", "арест?"]


async def arrest_user(message: types.Message):
    print(f"🔍 [DEBUG] arrest_user вызван: '{message.text}'")
    try:
        police = message.from_user
        if not PoliceService.check_police_permission(police.id):
            await message.reply("👮 Только <b>Полицейские</b> могут арестовывать!", parse_mode="HTML")
            return

        if not message.reply_to_message:
            await message.reply("❗ Ответь на сообщение вора.")
            return

        target = message.reply_to_message.from_user
        bot = await message.bot.get_me()

        if police.id == target.id:
            await message.reply("🚫 Нельзя арестовать себя!")
            return
        if target.id == bot.id:
            await message.reply("🤖 Бот вне закона!")
            return
        if not PoliceService.check_thief_permission(target.id):
            await message.reply("🎭 Цель не является <b>Вором в законе</b>!", parse_mode="HTML")
            return

        can, cooldown_end = PoliceService.check_police_cooldown(police.id)
        if not can:
            left = cooldown_end - datetime.now()
            secs = int(left.total_seconds())
            h, m = divmod(secs // 60, 60)
            cd = f"{h}ч {m}м" if h else f"{m}м"
            await message.reply(f"⏳ КД: следующий арест через {cd}")
            return

        minutes = PoliceService.parse_arrest_time(message.text)
        success, msg = PoliceService.arrest_user(police.id, target.id, minutes)

        if success:
            release_time = datetime.now() + timedelta(minutes=minutes)
            await message.reply(
                f"🚔 <b>АРЕСТОВАН</b>\n"
                f"🕗 До {release_time.strftime('%H:%M')}\n"
                f"⏳ Следующий арест через 3 часа",
                parse_mode="HTML"
            )
        else:
            await message.reply(f"❌ {msg}")

    except Exception as e:
        import traceback
        print("💥 arrest_user error:")
        traceback.print_exc()
        await message.reply("🚨 Внутренняя ошибка ареста.")


async def check_arrest(message: types.Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user

    # Получаем статус + данные об аресте
    from handlers.police.service import PoliceService
    db = next(get_db())  # ← уже есть в файле, если добавил импорт
    try:
        # Получаем "сырую" запись об аресте (без авто-очистки)
        from database.models import UserArrest
        arrest = db.query(UserArrest).filter(UserArrest.user_id == target.id).first()
    finally:
        db.close()

    if arrest and arrest.release_time > datetime.now():
        release_time_str = arrest.release_time.strftime('%H:%M')
        status = f"🔒 Арестован до: {release_time_str}"
    else:
        status = "✅ Свободен"

    await message.reply(f"{target.full_name}: {status}")


def register_police_handlers(dp):
    dp.register_message_handler(arrest_user, is_arrest_cmd, state="*")
    dp.register_message_handler(check_arrest, is_check_cmd, state="*")
    print("✅ police handlers registered")