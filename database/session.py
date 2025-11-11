# database/session.py
from contextlib import contextmanager
from . import SessionLocal

@contextmanager
def db_session():
    """Безопасный контекстный менеджер для работы с БД"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()