import time
import threading
from main import SessionLocal
from sqlalchemy import text
from database import crud


def performance_test_basic_operations():
    db = SessionLocal()
    try:
        # SELECT
        start = time.time()
        for _ in range(100):
            crud.UserRepository.get_user_by_telegram_id(db, 999999999)
        select_time = time.time() - start

        # INSERT
        start = time.time()
        for i in range(50):
            test_id = 2000000000 + i
            crud.UserRepository.get_or_create_user(
                db, test_id, f"perf_user_{i}", "Performance"
            )
        insert_time = time.time() - start

        print(f"SELECT100={select_time:.3f}s INSERT50={insert_time:.3f}s")

    except Exception as e:
        print(f"ERROR_basic={e}")
    finally:
        db.close()


def stress_test_concurrent_operations():
    def worker(worker_id):
        db = SessionLocal()
        try:
            ops = 0
            for i in range(20):
                user_id = 3000000000 + worker_id * 1000 + i
                crud.UserRepository.get_or_create_user(
                    db, user_id, f"stress_{worker_id}_{i}", "Stress"
                )
                if i % 2 == 0:
                    crud.TransactionRepository.create_transaction(
                        db, user_id, user_id + 1, 100, f"Stress {worker_id}"
                    )
                ops += 1
            return ops
        except:
            return 0
        finally:
            db.close()

    threads, results = [], []
    start = time.time()
    for i in range(5):
        t = threading.Thread(target=lambda idx=i: results.append(worker(idx)))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    total_time = time.time() - start
    total_ops = sum(results)
    print(f"OPS={total_ops} OPSs={total_ops/total_time:.1f}")


def check_query_performance():
    db = SessionLocal()
    try:
        queries = [
            ("SELECT_ID", "SELECT * FROM telegram_users WHERE telegram_id = 999999999"),
            ("TOP10", "SELECT * FROM telegram_users ORDER BY coins DESC LIMIT 10"),
            ("HISTORY", "SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 20"),
            ("ROULETTE", "SELECT COUNT(*), SUM(amount) FROM roulette_transactions WHERE is_win = true"),
        ]
        for name, sql in queries:
            start = time.time()
            for _ in range(10):
                r = db.execute(text(sql))
                r.fetchall()
            avg = (time.time() - start) / 10
            print(f"{name}={avg*1000:.1f}ms", end=" ")
        print()
    except Exception as e:
        print(f"ERROR_queries={e}")
    finally:
        db.close()


if __name__ == "__main__":
    start = time.time()
    performance_test_basic_operations()
    stress_test_concurrent_operations()
    check_query_performance()
    print(f"TOTAL={time.time() - start:.2f}s")
