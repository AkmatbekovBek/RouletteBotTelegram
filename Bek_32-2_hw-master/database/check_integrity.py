from main import SessionLocal, engine
from sqlalchemy import text


def check_data_integrity():
    """Проверка целостности данных в БД"""
    print("🔍 Проверка целостности данных...")

    db = SessionLocal()
    try:
        # 1. Проверка на отрицательные балансы
        print("\n📊 1. Проверка отрицательных балансов...")
        result = db.execute(text("""
                                 SELECT telegram_id, username, coins
                                 FROM telegram_users
                                 WHERE coins < 0
                                 """))
        negative_balances = result.fetchall()

        if negative_balances:
            print(f"❌ Найдены отрицательные балансы: {len(negative_balances)}")
            for user in negative_balances:
                print(f"   👤 {user[1]} (ID: {user[0]}): {user[2]} монет")
        else:
            print("✅ Отрицательных балансов не найдено")

        # 2. Проверка на дубликаты пользователей
        print("\n👥 2. Проверка дубликатов пользователей...")
        result = db.execute(text("""
                                 SELECT telegram_id, COUNT(*)
                                 FROM telegram_users
                                 GROUP BY telegram_id
                                 HAVING COUNT(*) > 1
                                 """))
        duplicates = result.fetchall()

        if duplicates:
            print(f"❌ Найдены дубликаты пользователей: {len(duplicates)}")
            for dup in duplicates:
                print(f"   🔄 Telegram ID {dup[0]}: {dup[1]} записей")
        else:
            print("✅ Дубликатов пользователей не найдено")

        # 3. Проверка транзакций с несуществующими пользователями
        print("\n💸 3. Проверка целостности транзакций...")
        result = db.execute(text("""
                                 SELECT t.id, t.from_user_id, t.to_user_id
                                 FROM transactions t
                                          LEFT JOIN telegram_users u1 ON t.from_user_id = u1.telegram_id
                                          LEFT JOIN telegram_users u2 ON t.to_user_id = u2.telegram_id
                                 WHERE u1.telegram_id IS NULL
                                    OR u2.telegram_id IS NULL
                                 """))
        broken_transactions = result.fetchall()

        if broken_transactions:
            print(f"❌ Найдены проблемные транзакции: {len(broken_transactions)}")
            for tx in broken_transactions:
                print(f"   ⚠️ Транзакция ID {tx[0]}: from={tx[1]}, to={tx[2]}")
        else:
            print("✅ Все транзакции корректны")

        # 4. Проверка целостности внешних ключей
        print("\n🔗 4. Проверка внешних ключей...")

        tables_to_check = [
            ('reference_users', 'owner_telegram_id'),
            ('user_chats', 'user_id'),
            ('daily_records', 'user_id'),
            ('roulette_transactions', 'user_id'),
            ('user_purchases', 'user_id'),
            ('transfer_limits', 'user_id')
        ]

        total_problems = 0
        for table_name, column_name in tables_to_check:
            result = db.execute(text(f"""
                SELECT COUNT(*)
                FROM {table_name} 
                WHERE {column_name} NOT IN (SELECT telegram_id FROM telegram_users)
            """))
            problem_count = result.scalar()

            if problem_count > 0:
                print(f"❌ {table_name}.{column_name}: {problem_count} проблемных записей")
                total_problems += problem_count
            else:
                print(f"✅ {table_name}.{column_name}: OK")

        if total_problems == 0:
            print("✅ Все внешние ключи корректны")

        # 5. Проверка согласованности данных
        print("\n📈 5. Проверка согласованности данных...")

        # Проверка общего баланса системы
        result = db.execute(text("SELECT SUM(coins) FROM telegram_users"))
        total_coins = result.scalar() or 0

        result = db.execute(text("SELECT COUNT(*) FROM telegram_users"))
        user_count = result.scalar()

        print(f"   👥 Всего пользователей: {user_count}")
        print(f"   💰 Общая сумма монет: {total_coins}")
        print(f"   📊 Средний баланс: {total_coins / user_count if user_count > 0 else 0:.2f}")

        # Проверка транзакций
        result = db.execute(text("SELECT COUNT(*), SUM(amount) FROM transactions"))
        tx_stats = result.fetchone()
        print(f"   🔄 Всего транзакций: {tx_stats[0]}")
        print(f"   📦 Общая сумма переводов: {tx_stats[1] or 0}")

    except Exception as e:
        print(f"❌ Ошибка при проверке целостности: {e}")
    finally:
        db.close()


def check_database_structure():
    """Проверка структуры базы данных"""
    print("\n🏗️ Проверка структуры базы данных...")

    db = SessionLocal()
    try:
        # Проверка существования всех таблиц
        tables = [
            'telegram_users', 'reference_users', 'transactions',
            'user_chats', 'daily_records', 'roulette_transactions',
            'roulette_game_logs', 'user_purchases', 'transfer_limits',
            'user_bonuses'
        ]

        missing_tables = []
        for table in tables:
            result = db.execute(text("""
                                     SELECT EXISTS (SELECT
                                                    FROM information_schema.tables
                                                    WHERE table_schema = 'public'
                                                      AND table_name = :table_name)
                                     """), {'table_name': table})

            exists = result.scalar()
            if exists:
                print(f"✅ Таблица {table} существует")
            else:
                print(f"❌ Таблица {table} отсутствует")
                missing_tables.append(table)

        if missing_tables:
            print(f"\n⚠️ Отсутствуют таблицы: {', '.join(missing_tables)}")
        else:
            print("✅ Все таблицы присутствуют")

    except Exception as e:
        print(f"❌ Ошибка при проверке структуры: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    check_data_integrity()
    check_database_structure()