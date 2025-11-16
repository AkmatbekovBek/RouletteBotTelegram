# admin_constants.py

# Конфигурация
ADMIN_IDS = [6090751674, 1054684037]
BROADCAST_BATCH_SIZE = 10
BROADCAST_DELAY = 0.1

# Константы для привилегий
PRIVILEGES = {
    "thief": {"id": 1, "name": "👑 Вор в законе", "extendable": True, "default_days": 30},
    "police": {"id": 2, "name": "👮‍♂️ Полицейский", "extendable": True, "default_days": 30},
    "unlimit": {"id": 3, "name": "🔐 Снятие лимита перевода", "extendable": False, "default_days": 0}
}

# Константы для предметов магазина
SHOP_ITEMS = {
    "unlimited_transfers": 3
}