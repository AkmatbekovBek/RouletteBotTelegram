# handlers/thief/handlers.py
import re
from aiogram import types
from handlers.thief.service import ThiefService


def normalize_cmd(text: str) -> str:
    """Нормализует команду, убирает лишние пробелы и приводит к нижнему регистру"""
    if not text or not text.strip():
        return ""

    # Убираем символы команд и упоминания
    text = re.sub(r"^[/!]", "", text)
    text = re.sub(r"@[\w_]+$", "", text)

    # Разбиваем на слова и берем первое, если оно есть
    parts = text.strip().lower().split()
    return parts[0] if parts else ""


def is_rob_cmd(msg: types.Message):
    """Проверяет, является ли сообщение командой кражи"""
    if not msg.text or not msg.text.strip():
        return False

    normalized_cmd = normalize_cmd(msg.text)
    return normalized_cmd in ["украсть", "ограбить", "воруй"]


async def rob_user(message: types.Message):
    print(f"🔍 [DEBUG] rob_user вызван: '{message.text}'")
    try:
        thief = message.from_user
        if not ThiefService.check_thief_permission(thief.id):
            await message.reply("🎭 Только <b>Воры в законе</b> могут красть!", parse_mode="HTML")
            return

        if not message.reply_to_message:
            await message.reply("❗ Ответь на сообщение жертвы.")
            return

        victim = message.reply_to_message.from_user
        bot = await message.bot.get_me()

        if victim.id == bot.id:
            await message.reply("🤖 У бота нет денег.")
            return

        success, msg, amount = ThiefService.rob_user(thief.id, victim.id)

        if success:
            # Определяем имена с fallback'ом (на случай пустых имён)
            thief_name = thief.full_name or thief.first_name or thief.username or "Неизвестный вор"
            victim_name = victim.full_name or victim.first_name or victim.username or "Неизвестная жертва"

            # Реакция в зависимости от суммы
            if amount < 100:
                reaction = "🤫 Мелочь, но на шоколадку хватит..."
            elif amount < 500:
                reaction = "👀 Ловко! Никто не заметил."
            elif amount < 1000:
                reaction = "🕶️ Профессионал! Ни единого намёка."
            elif amount < 5000:
                reaction = "🔥 Горячая монета! Полиция уже ищет..."
            elif amount < 10000:
                reaction = "🚨 КРУПНОЕ ОГРАБЛЕНИЕ! Группа захвата выехала!"
            else:
                reaction = "💣 БАНКОВСКИЙ РАЗБОЙ! Объявлен федеральный розыск!!!"

            await message.reply(
                f"🌑 <b>СВОРОВАНО!!!</b>\n"
                f"👤 <b>{thief_name}</b> незаметно стырил монеты у <b>{victim_name}</b>\n"
                f"💸 <b>+{amount}</b> монет пропали\n"
                f"\n{reaction}",
                parse_mode="HTML"
            )
        else:
            await message.reply(f"❌ {msg}")

    except Exception as e:
        import traceback
        print("💥 rob_user error:")
        traceback.print_exc()
        await message.reply("🚨 Внутренняя ошибка кражи.")


def register_thief_handlers(dp):
    dp.register_message_handler(rob_user, is_rob_cmd, state="*")
    print("✅ thief handlers registered")