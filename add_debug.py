with open('handlers/thief_handler.py', 'r') as f:
    content = f.read()

# Добавляем отладочное сообщение в начало метода steal_money
if 'async def steal_money' in content and 'self.logger.info(f"🚨 Начало кражи от пользователя' not in content:
    content = content.replace(
        'async def steal_money(self, message: types.Message):',
        'async def steal_money(self, message: types.Message):\n        self.logger.info(f"🚨 Начало кражи от пользователя {message.from_user.id}")'
    )

with open('handlers/thief_handler.py', 'w') as f:
    f.write(content)

print("✅ Отладочные сообщения добавлены!")
