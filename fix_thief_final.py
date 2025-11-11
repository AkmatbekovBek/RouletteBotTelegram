with open('handlers/thief_handler.py', 'r') as f:
    content = f.read()

# 1. Добавляем отладочную строку в steal_money
if 'self.logger.info(f"🚨🚨🚨 STEAL COMMAND TRIGGERED!' not in content:
    content = content.replace(
        'async def steal_money(self, message: types.Message):\\n        \\"\\"\\"Команда \\'красть\\' - попытка украсть деньги у пользователя\\"\\"\\"\\n        try:',
        'async def steal_money(self, message: types.Message):\\n        \\"\\"\\"Команда \\'красть\\' - попытка украсть деньги у пользователя\\"\\"\\"\\n        self.logger.info(f"🚨🚨🚨 STEAL COMMAND TRIGGERED! User: {message.from_user.id}, Text: \\'{message.text}\\'")\\n        try:'
    )

# 2. Добавляем проверку ареста в _check_steal_cooldowns
arrest_check = '''        try:
            # 🔥 ДОБАВЛЯЕМ проверку ареста
            try:
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
            except Exception as arrest_error:
                self.logger.error(f"❌ Ошибка проверки ареста: {arrest_error}")
                # Продолжаем если ошибка

            # Убрали проверку ареста, так как ареста больше нет'''

content = content.replace(
    '        try:\\n            # Убрали проверку ареста, так как ареста больше нет',
    arrest_check
)

with open('handlers/thief_handler.py', 'w') as f:
    f.write(content)

print("✅ Проверка ареста и отладка добавлены!")
