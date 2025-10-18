import asyncio
from main import SessionLocal
from database import crud, models
from datetime import datetime, timedelta


def test_user_operations():
    """Тест операций с пользователями"""
    db = SessionLocal()
    try:
        print("🧪 Тестирование пользователей...")

        # Создание тестового пользователя
        user = crud.UserRepository.get_or_create_user(
            db, 999999999, "test_user", "Test", "User"
        )
        print(f"✅ Создан тестовый пользователь: {user.telegram_id}")

        # Проверка баланса
        assert user.coins >= 0, "Баланс не может быть отрицательным"
        print(f"✅ Баланс пользователя: {user.coins}")

        # Обновление баланса
        updated = crud.UserRepository.update_user_balance(db, 999999999, 10000)
        assert updated.coins == 10000, "Баланс не обновился"
        print("✅ Обновление баланса работает")

    except Exception as e:
        print(f"❌ Ошибка в тесте пользователей: {e}")
    finally:
        db.close()


def test_transactions():
    """Тест транзакций"""
    db = SessionLocal()
    try:
        print("\n🧪 Тестирование транзакций...")

        # Создание тестовых пользователей
        user1 = crud.UserRepository.get_or_create_user(db, 1000000001, "user1", "User1")
        user2 = crud.UserRepository.get_or_create_user(db, 1000000002, "user2", "User2")

        # Изначальные балансы
        initial_balance1 = user1.coins
        initial_balance2 = user2.coins

        # Создание транзакции
        transaction = crud.TransactionRepository.create_transaction(
            db, user1.telegram_id, user2.telegram_id, 1000, "Тестовая транзакция"
        )
        print(f"✅ Транзакция создана: ID {transaction.id}")

        # Обновление балансов
        crud.UserRepository.update_user_balance(db, user1.telegram_id, initial_balance1 - 1000)
        crud.UserRepository.update_user_balance(db, user2.telegram_id, initial_balance2 + 1000)

        # Проверка истории транзакций
        transactions = crud.TransactionRepository.get_user_transactions(db, user1.telegram_id)
        assert len(transactions) > 0, "История транзакций пуста"
        print(f"✅ История транзакций: {len(transactions)} записей")

    except Exception as e:
        print(f"❌ Ошибка в тесте транзакций: {e}")
    finally:
        db.close()


def test_limits():
    """Тест системы лимитов"""
    db = SessionLocal()
    try:
        print("\n🧪 Тестирование лимитов...")

        user = crud.UserRepository.get_or_create_user(db, 1000000003, "limit_user", "Limit")

        # Исправление: используем timezone-aware datetime
        from datetime import timezone
        transfer_time = datetime.now(timezone.utc)

        # Добавление лимита
        limit = crud.TransferLimitRepository.add_transfer_limit(
            db, user.telegram_id, 5000, transfer_time
        )
        print(f"✅ Лимит добавлен: {limit.amount}")

        # Проверка лимитов за последние 6 часов
        six_hours_ago = datetime.now(timezone.utc) - timedelta(hours=6)
        limits = crud.TransferLimitRepository.get_user_transfers_last_6h(db, user.telegram_id)
        print(f"✅ Лимитов за 6ч: {len(limits)}")

        # Очистка старых лимитов (7 дней)
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        deleted_count = db.query(models.TransferLimit).filter(
            models.TransferLimit.transfer_time < seven_days_ago
        ).delete()
        db.commit()
        print(f"✅ Удалено старых лимитов: {deleted_count}")

    except Exception as e:
        print(f"❌ Ошибка в тесте лимитов: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def test_roulette():
    """Тест рулетки"""
    db = SessionLocal()
    try:
        print("\n🧪 Тестирование рулетки...")

        user = crud.UserRepository.get_or_create_user(db, 1000000004, "roulette_user", "Roulette")

        # Тестовая транзакция рулетки
        roulette_tx = crud.RouletteRepository.create_roulette_transaction(
            db, user.telegram_id, 100, True, "number", "7", 7, 350
        )
        print(f"✅ Транзакция рулетки создана: {roulette_tx.id}")

        # История ставок
        history = crud.RouletteRepository.get_user_bet_history(db, user.telegram_id)
        print(f"✅ История ставок: {len(history)} записей")

        # Лог игры
        game_log = crud.RouletteRepository.add_game_log(db, -100, 7, "🔴")
        print(f"✅ Лог игры создан: {game_log.id}")

    except Exception as e:
        print(f"❌ Ошибка в тесте рулетки: {e}")
    finally:
        db.close()


def test_references():
    """Тест реферальной системы"""
    db = SessionLocal()
    try:
        print("\n🧪 Тестирование рефералов...")

        owner = crud.UserRepository.get_or_create_user(db, 1000000005, "owner", "Owner")
        referral = crud.UserRepository.get_or_create_user(db, 1000000006, "referral", "Referral")

        # Добавление реферала
        ref = crud.ReferenceRepository.add_reference(db, owner.telegram_id, referral.telegram_id)
        print(f"✅ Реферал добавлен: {ref.id}")

        # Проверка существования реферала
        exists = crud.ReferenceRepository.check_reference_exists(db, referral.telegram_id)
        assert exists, "Реферал не найден"
        print("✅ Проверка реферала работает")

        # Список рефералов
        refs = crud.ReferenceRepository.get_user_references(db, owner.telegram_id)
        print(f"✅ Рефералов у пользователя: {len(refs)}")

    except Exception as e:
        print(f"❌ Ошибка в тесте рефералов: {e}")
    finally:
        db.close()


def run_all_tests():
    """Запуск всех тестов"""
    print("🚀 Запуск комплексного тестирования БД...")

    test_user_operations()
    test_transactions()
    test_limits()
    test_roulette()
    test_references()

    print("\n🎉 Все тесты завершены!")


if __name__ == "__main__":
    run_all_tests()