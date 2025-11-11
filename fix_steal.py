with open('handlers/thief_handler.py', 'r') as f:
    content = f.read()

# Заменяем блок проверки ареста на упрощенный
old_block = '''        try:
            # 🔥 ВОССТАНАВЛИВАЕМ проверку ареста!
            from database.crud import PoliceRepository
            arrest = PoliceRepository.get_user_arrest(db, thief_id)
            if arrest and arrest.release_time > datetime.now():
                time_left = arrest.release_time - datetime.now()
                minutes_left = int(time_left.total_seconds() // 60)
                hours_left = int(minutes_left // 60)
                if hours_left > 0:
                    return False, f"🔒 Вы арестованы! Освобождение через {hours_left}ч {minutes_left % 60}м"
                else:
                    return False, f"🔒 Вы арестованы! Освобождение через {minutes_left} минут"

            # Проверяем кулдаун вора'''

new_block = '''        try:
            # 🔥 УПРОЩЕННАЯ проверка ареста (временно)
            try:
                from database.crud import PoliceRepository
                arrest = PoliceRepository.get_user_arrest(db, thief_id)
                if arrest and arrest.release_time > datetime.now():
                    return False, "🔒 Вы арестованы! Нельзя красть во время ареста."
            except Exception as e:
                print(f"⚠️ Ошибка проверки ареста: {e}")
                # Продолжаем если ошибка

            # Проверяем кулдаун вора'''

content = content.replace(old_block, new_block)

with open('handlers/thief_handler.py', 'w') as f:
    f.write(content)

print("✅ Упрощенная проверка ареста установлена!")
