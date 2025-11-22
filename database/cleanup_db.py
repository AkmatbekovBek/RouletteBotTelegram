# safe_cleanup.py
from database import SessionLocal
from database.models import *


def safe_cleanup():
    db = SessionLocal()
    try:
        print("🧹 Безопасная очистка данных...")

        # Очищаем в правильном порядке чтобы не нарушить foreign keys
        tables_to_clean = [
            # Сначала таблицы без зависимостей
            UserGift, StealAttempt, ThiefArrest, UserArrest,
            DivorceRequest, Marriage, DonatePurchase, UserNickSearch,
            UserChatSearch, BotStop, ModerationLog, RouletteLimit,
            TransferLimit, UserPurchase, RouletteTransaction, DailyRecord,
            Transaction, ReferenceUser, UserChat, RouletteGameLog,

            # Потом таблица User (зависит от TelegramUser)
            User,

            # И наконец остальные
            Gift, Chat
        ]

        # НЕ очищаем TelegramUser - там основные данные пользователей!

        for table in tables_to_clean:
            try:
                count = db.query(table).count()
                if count > 0:
                    db.query(table).delete()
                    db.commit()
                    print(f"✅ Очищена {table.__tablename__}: {count} записей")
                else:
                    print(f"ℹ️  {table.__tablename__}: уже пустая")
            except Exception as e:
                db.rollback()
                print(f"❌ Ошибка в {table.__tablename__}: {e}")

        print("🎯 Очистка завершена! Основные данные пользователей сохранены.")

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    safe_cleanup()