# add_coins_to_user.py
import asyncio
from database import get_db
from database.crud import UserRepository, TransactionRepository


async def add_coins_to_user():
    """Добавляет монеты пользователю напрямую"""
    try:
        USER_ID = 7326913977  # Получатель
        AMOUNT = 700000000000000000000000000  # Сколько монет добавить

        print(f"💰 Добавляем {AMOUNT} монет пользователю {USER_ID}...")

        db = next(get_db())
        try:
            # Получаем пользователя
            user = UserRepository.get_user_by_telegram_id(db, USER_ID)

            if not user:
                print(f"❌ Пользователь {USER_ID} не найден в базе")
                return

            # Получаем текущий баланс
            current_balance = user.coins
            new_balance = current_balance + AMOUNT

            # Обновляем баланс
            UserRepository.update_user_balance(db, USER_ID, new_balance)

            # Создаем транзакцию пополнения (без отправителя)
            TransactionRepository.create_transaction(
                db=db,
                from_user_id=None,  # Без отправителя
                to_user_id=USER_ID,
                amount=AMOUNT,
                description="Пополнение от администратора"
            )

            db.commit()

            print("✅ Монеты успешно добавлены!")
            print(f"👤 Пользователь: {USER_ID}")
            print(f"💰 Было: {current_balance} монет")
            print(f"💰 Стало: {new_balance} монет")
            print(f"📈 Добавлено: +{AMOUNT} монет")

        except Exception as e:
            db.rollback()
            print(f"❌ Ошибка базы данных: {e}")
        finally:
            db.close()

    except Exception as e:
        print(f"❌ Общая ошибка: {e}")


# Запуск
if __name__ == "__main__":
    asyncio.run(add_coins_to_user())