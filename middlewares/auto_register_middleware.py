# middlewares/auto_register_middleware.py
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware
from database import SessionLocal
from database.models import User

class AutoRegisterMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        # Определяем контекстный chat_id
        if message.chat.type in ('group', 'supergroup'):
            context_chat_id = message.chat.id
        else:
            context_chat_id = 0  # глобальный контекст для ЛС

        # Создаём сессию
        db = SessionLocal()
        try:
            # Ищем пользователя в этом чате
            user = db.query(User).filter(
                User.tg_id == message.from_user.id,
                User.chat_id == context_chat_id
            ).first()

            if not user:
                user = User(
                    tg_id=message.from_user.id,
                    chat_id=context_chat_id,
                    username=message.from_user.username or '',
                    balance=0,
                    max_win=0,
                    max_loss=0,
                    max_bet=0
                )
                db.add(user)
                db.commit()
                db.refresh(user)

            # Обновляем username, если изменился
            if message.from_user.username and user.username != message.from_user.username:
                user.username = message.from_user.username
                db.commit()

        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()