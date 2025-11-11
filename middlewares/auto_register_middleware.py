from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware
from database import get_db
from database.crud import UserRepository

class AutoRegisterMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.registered_users = set()  # Кэш зарегистрированных пользователей в текущей сессии

    async def on_pre_process_message(self, message: types.Message, data: dict):
        """Вызывается перед обработкой ЛЮБОГО сообщения"""
        if message.from_user and not message.from_user.is_bot:
            await self._ensure_user_exists(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )

    async def on_pre_process_callback_query(self, callback: types.CallbackQuery, data: dict):
        """Вызывается перед обработкой ЛЮБОГО callback"""
        if callback.from_user and not callback.from_user.is_bot:
            await self._ensure_user_exists(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name
            )

    async def _ensure_user_exists(self, telegram_id: int, username: str = None,
                                first_name: str = None, last_name: str = None):
        """Асинхронно проверяет и создает пользователя если его нет"""
        # Проверяем кэш чтобы избежать повторных регистраций
        if telegram_id in self.registered_users:
            return

        db = next(get_db())
        try:
            user = UserRepository.get_user_by_telegram_id(db, telegram_id)
            if not user:
                # Пользователя нет в БД - регистрируем
                user = UserRepository.get_or_create_user(
                    db=db,
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name
                )
                print(f"✅ Авторегистрация пользователя: {telegram_id} ({first_name or 'без имени'})")
            else:
                # Пользователь уже есть в БД - обновляем информацию если нужно
                if (user.username != username or user.first_name != first_name or user.last_name != last_name):
                    UserRepository.update_user_info(
                        db=db,
                        telegram_id=telegram_id,
                        username=username,
                        first_name=first_name,
                        last_name=last_name
                    )
                    print(f"🔄 Обновлена информация пользователя: {telegram_id}")

            # Добавляем в кэш независимо от того, был ли он создан или уже существовал
            self.registered_users.add(telegram_id)

        except Exception as e:
            print(f"❌ Ошибка авторегистрации пользователя {telegram_id}: {e}")
        finally:
            db.close()