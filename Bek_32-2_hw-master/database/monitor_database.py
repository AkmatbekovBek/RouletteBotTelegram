import psutil
import time
from main import engine
from sqlalchemy import text


def monitor_database():
    """Мониторинг состояния БД"""
    print("📊 Мониторинг БД...")

    try:
        with engine.connect() as conn:
            # Активные подключения
            result = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"))
            active_connections = result.scalar()
            print(f"🔗 Активные подключения: {active_connections}")

            # Размер БД
            result = conn.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
            db_size = result.scalar()
            print(f"💾 Размер БД: {db_size}")

            # Статистика по таблицам
            result = conn.execute(text("""
                                       SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del
                                       FROM pg_stat_user_tables
                                       ORDER BY n_tup_ins + n_tup_upd + n_tup_del DESC LIMIT 5
                                       """))
            print("📈 Самые активные таблицы:")
            for row in result:
                print(f"  {row.tablename}: +{row.n_tup_ins} ↑{row.n_tup_upd} -{row.n_tup_del}")

    except Exception as e:
        print(f"❌ Ошибка мониторинга: {e}")


if __name__ == "__main__":
    monitor_database()