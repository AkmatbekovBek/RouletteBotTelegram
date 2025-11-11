with open('handlers/thief_handler.py', 'r') as f:
    content = f.read()

# Добавляем отладочную информацию в начало steal_money
if 'async def steal_money' in content:
    new_steal_start = '''async def steal_money(self, message: types.Message):
        \"\"\"Команда 'красть' - попытка украсть деньги у пользователя\"\"\"
        self.logger.info(f"🚨🚨🚨 STEAL COMMAND TRIGGERED! User: {message.from_user.id}, Text: '{message.text}'")
        try:'''
    
    content = content.replace(
        'async def steal_money(self, message: types.Message):\n        \"\"\"Команда 'красть' - попытка украсть деньги у пользователя\"\"\"\n        try:',
        new_steal_start
    )

with open('handlers/thief_handler.py', 'w') as f:
    f.write(content)

print("✅ Дополнительная отладка добавлена!")
