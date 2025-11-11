with open('database/crud.py', 'r') as f:
    content = f.read()

# Добавляем метод в PoliceRepository
method_code = '''
    @staticmethod
    def get_last_arrest_by_police(db, police_id: int):
        """Получает последний арест, выполненный полицейским"""
        from database.models import UserArrest
        try:
            last_arrest = db.query(UserArrest)\\
                .filter(UserArrest.arrested_by == police_id)\\
                .order_by(UserArrest.release_time.desc())\\
                .first()
            return last_arrest
        except Exception as e:
            print(f"❌ Ошибка получения последнего ареста полицейского {police_id}: {e}")
            return None
'''

# Вставляем перед cleanup_expired_arrests
if 'def cleanup_expired_arrests' in content and 'def get_last_arrest_by_police' not in content:
    content = content.replace(
        '    @staticmethod\n    def cleanup_expired_arrests(db) -> int:',
        method_code + '\n\n    @staticmethod\n    def cleanup_expired_arrests(db) -> int:'
    )

with open('database/crud.py', 'w') as f:
    f.write(content)

print("✅ Метод get_last_arrest_by_police добавлен в PoliceRepository!")
