# admin_notifications.py

import logging
from pathlib import Path
from aiogram import types
from .admin_helpers import db_session, format_number
from database.crud import UserRepository

logger = logging.getLogger(__name__)

async def send_admin_action_notification(bot, user_id: int, action_type: str,
                                         amount: int = None, new_balance: int = None,
                                         privilege_info: dict = None):
    """Отправляет красивое уведомление о действии админа в ЛС пользователю"""
    try:
        # Сначала проверяем и создаем пользователя если нужно
        with db_session() as db:
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                # Создаем пользователя если его нет
                try:
                    # Пытаемся получить информацию о пользователе через Telegram API
                    chat_member = await bot.get_chat(user_id)
                    username = chat_member.username
                    first_name = chat_member.first_name or "Пользователь"
                    user = UserRepository.create_user_safe(
                        db,
                        user_id,
                        first_name,
                        username
                    )
                    logger.info(f"✅ Создан новый пользователь {user_id} для доната")
                except Exception as user_info_error:
                    logger.warning(
                        f"Не удалось получить информацию о пользователе {user_id}: {user_info_error}")
                    # Создаем с базовыми данными
                    user = UserRepository.create_user_safe(
                        db,
                        user_id,
                        "Пользователь",
                        None
                    )
                db.commit()

        # Остальной код метода без изменений...
        action_texts = {
            "donate": "🎉 Вам зачислен донат!",
            "add_coins": "💰 Вам начислены монеты!",
            "privilege": "🎁 Вам выдана привилегия!",
            "unlimit": "🔐 Вам сняли лимит переводов!",
            "coins_and_privilege": "🎊 Вам начислены монеты и привилегия!"
        }
        # Основной текст уведомления
        notification_text = f"<b>{action_texts.get(action_type, '🎁 Вам начислена награда!')}</b>\n"
        # Добавляем информацию о монетах если есть
        if amount is not None and new_balance is not None:
            notification_text += f"💝 <b>+{format_number(amount)} монет</b>\n"
            notification_text += f"💳 Теперь на вашем балансе: <b>{format_number(new_balance)} монет</b>\n"
        # Добавляем информацию о привилегии если есть
        if privilege_info:
            # Используем реальное количество дней из privilege_info, если передано, иначе default_days
            actual_days = privilege_info.get('actual_days', privilege_info.get('default_days', 30))
            duration = f"{actual_days} дней" if privilege_info.get('extendable') else "навсегда"
            notification_text += f"🎁 <b>Привилегия: {privilege_info['name']}</b>\n"
            notification_text += f"⏰ Срок: {duration}\n"
        notification_text += "✨ <i>Спасибо за вашу активность!</i>"

        # Определяем путь к изображению
        try:
            # Получаем абсолютный путь к проекту
            project_root = Path(__file__).parent.parent
            media_dir = project_root / "media"
            # Проверяем разные возможные имена файлов
            possible_filenames = [
                "donate.jpg",
                "donate.png",
            ]
            photo_path = None
            for filename in possible_filenames:
                potential_path = media_dir / filename
                if potential_path.exists():
                    photo_path = potential_path
                    break

            if photo_path:
                logger.info(f"Using photo: {photo_path}")
                # Открываем файл и отправляем как фото
                with open(photo_path, 'rb') as photo:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=photo,
                        caption=notification_text,
                        parse_mode="HTML"
                    )
                logger.info(f"Successfully sent photo notification to user {user_id}")
            else:
                # Если файл не найден, создаем список доступных файлов для отладки
                available_files = list(media_dir.glob("*.*")) if media_dir.exists() else []
                logger.warning(f"Photo not found. Available files in {media_dir}: {available_files}")
                raise FileNotFoundError("No suitable photo file found")
        except FileNotFoundError as e:
            logger.warning(f"Photo file not found: {e}, falling back to text message")
            # Если файл не найден, отправляем текстовое сообщение
            await bot.send_message(
                chat_id=user_id,
                text=notification_text,
                parse_mode="HTML"
            )
        except Exception as photo_error:
            logger.warning(f"Could not send photo, falling back to text: {photo_error}")
            # Если не удалось отправить фото, отправляем текстовое сообщение
            await bot.send_message(
                chat_id=user_id,
                text=notification_text,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error sending admin action notification to {user_id}: {e}")
        # В случае общей ошибки все равно пытаемся отправить текстовое уведомление
        try:
            notification_text = f"🎉 Вам начислена награда от администратора!"
            if amount is not None:
                notification_text += f"\n💰 +{format_number(amount)} монет"
            if privilege_info:
                notification_text += f"\n🎁 {privilege_info['name']}"
            await bot.send_message(
                chat_id=user_id,
                text=notification_text
            )
        except Exception as fallback_error:
            logger.error(f"Failed to send fallback notification to {user_id}: {fallback_error}")