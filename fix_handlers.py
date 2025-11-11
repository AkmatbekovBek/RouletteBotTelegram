with open('handlers/thief_handler.py', 'r') as f:
    content = f.read()

# Добавляем тестовый обработчик перед основным
test_handler = '''
    # 🔥 ТЕСТОВЫЙ обработчик для отладки
    dp.register_message_handler(
        handler.steal_money,
        lambda msg: True,  # Принимаем все сообщения для теста
        state="*"
    )'''

# Вставляем тестовый обработчик после создания handler
if 'handler = ThiefHandler()' in content and '🔥 ТЕСТОВЫЙ обработчик' not in content:
    content = content.replace(
        '    handler = ThiefHandler()\n\n    # Обработчик для команд с "красть"',
        '    handler = ThiefHandler()\n' + test_handler + '\n\n    # Обработчик для команд с "красть"'
    )

with open('handlers/thief_handler.py', 'w') as f:
    f.write(content)

print("✅ Тестовый обработчик добавлен!")
