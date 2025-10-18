# # database/sql_commands.py
# import sqlite3
# from datetime import datetime
# from database import sql_queries
#
#
# class Database:
#     def __init__(self):
#         self.connection = sqlite3.connect("db.sqlite3", check_same_thread=False)
#         self.cursor = self.connection.cursor()
#         self.sql_create_db()
#         self.sql_migrate_daily_records()
#
#     def sql_create_db(self):
#         """Создает все необходимые таблицы при инициализации"""
#         try:
#             tables = [
#                 sql_queries.CREATE_USER_TABLE_QUERY,
#                 sql_queries.CREATE_REFERENCE_USERS_TABLE_QUERY,
#                 sql_queries.CREATE_TRANSACTIONS_TABLE_QUERY,
#                 sql_queries.CREATE_USER_CHATS_TABLE_QUERY,
#                 sql_queries.CREATE_DAILY_RECORDS_TABLE_QUERY,
#                 sql_queries.CREATE_ROULETTE_TRANSACTIONS_TABLE_QUERY,
#                 sql_queries.CREATE_ROULETTE_GAME_LOGS_TABLE_QUERY,
#             ]
#
#             for table_query in tables:
#                 self.cursor.execute(table_query)
#
#             self.connection.commit()
#             print("✅ Все таблицы базы данных созданы/проверены")
#         except Exception as e:
#             print(f"❌ Ошибка создания таблиц: {e}")
#
#     # ==================== USER METHODS ====================
#
#     def sql_insert_user_command(self, telegram_id, username, first_name, last_name):
#         """Добавляет нового пользователя"""
#         self.cursor.execute(
#             sql_queries.START_INSERT_USER_QUERY,
#             (None, telegram_id, username, first_name, last_name, None)
#         )
#         self.connection.commit()
#
#     def sql_select_user_command(self, telegram_id):
#         """Получает данные пользователя"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "id": row[0],
#             "telegram_id": row[1],
#             "username": row[2],
#             "first_name": row[3],
#             "last_name": row[4],
#             "link": row[5],
#             "coins": row[6],
#             "win_coins": row[7],
#             "defeat_coins": row[8],
#             "max_win_coins": row[9],
#             "min_win_coins": row[10]
#         }
#         return self.cursor.execute(
#             sql_queries.SELECT_USER_QUERY, (telegram_id,)
#         ).fetchall()
#
#     def sql_admin_select_user_command(self):
#         """Получает всех пользователей для админки"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "telegram_id": row[1],
#             "username": row[2],
#             "first_name": row[3]
#         }
#         return self.cursor.execute(sql_queries.SELECT_ALL_USERS_QUERY).fetchall()
#
#     # ==================== REFERENCE METHODS ====================
#
#     def sql_update_user_by_link(self, link, telegram_id):
#         """Обновляет реферальную ссылку пользователя"""
#         self.cursor.execute(
#             sql_queries.UPDATE_USER_BY_LINK_QUERY,
#             (link, telegram_id,)
#         )
#         self.connection.commit()
#
#     def sql_select_user_link_command(self, telegram_id):
#         """Получает реферальную ссылку пользователя"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "link": row[0],
#         }
#         return self.cursor.execute(
#             sql_queries.SELECT_USER_LINK_QUERY, (telegram_id,)
#         ).fetchall()
#
#     def sql_select_owner_link_command(self, owner_link):
#         """Получает telegram_id по реферальной ссылке"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "telegram_id": row[0],
#         }
#         return self.cursor.execute(
#             sql_queries.SELECT_OWNER_LINK_QUERY, (owner_link,)
#         ).fetchall()
#
#     def sql_insert_reference_users(self, owner_telegram_id, reference_telegram_users):
#         """Добавляет реферала"""
#         self.cursor.execute(
#             sql_queries.INSERT_REFERENCE_USERS_QUERY,
#             (None, owner_telegram_id, reference_telegram_users,)
#         )
#         self.connection.commit()
#
#     def sql_select_existed_reference_command(self, reference_telegram_users):
#         """Проверяет существование реферала"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "id": row[0],
#         }
#         return self.cursor.execute(
#             sql_queries.SELECT_EXIST_REFERENCE_QUERY, (reference_telegram_users,)
#         ).fetchall()
#
#     def sql_select_all_reference_command(self, owner_telegram_id):
#         """Получает всех рефералов пользователя"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "id": row[2],
#         }
#         return self.cursor.execute(
#             sql_queries.SELECT_ALL_REFERENCE_QUERY, (owner_telegram_id,)
#         ).fetchall()
#
#     # ==================== COINS & STATS METHODS ====================
#
#     def sql_update_user_coins(self, telegram_id, coins):
#         """Обновляет баланс пользователя"""
#         self.cursor.execute(
#             sql_queries.UPDATE_USER_COINS_QUERY,
#             (coins, telegram_id)
#         )
#         self.connection.commit()
#
#     def sql_update_user_stats(self, telegram_id, win_coins, defeat_coins, max_win_coins, min_win_coins):
#         """Обновляет статистику пользователя"""
#         self.cursor.execute(
#             sql_queries.UPDATE_USER_STATS_QUERY,
#             (win_coins, defeat_coins, max_win_coins, min_win_coins, telegram_id)
#         )
#         self.connection.commit()
#
#     def get_user_balance(self, user_id: int) -> int:
#         """Получает баланс пользователя"""
#         self.cursor.execute(sql_queries.SELECT_USER_BALANCE_QUERY, (user_id,))
#         result = self.cursor.fetchone()
#         return result[0] if result else 0
#
#     def update_user_balance(self, user_id: int, new_balance: int):
#         """Обновляет баланс пользователя"""
#         self.sql_update_user_coins(user_id, new_balance)
#
#     # ==================== TRANSACTION METHODS ====================
#
#     def sql_insert_transaction(self, from_user_id, to_user_id, amount, description=""):
#         """Добавляет транзакцию"""
#         self.cursor.execute(
#             sql_queries.INSERT_TRANSACTION_QUERY,
#             (None, from_user_id, to_user_id, amount, description)
#         )
#         self.connection.commit()
#
#     def sql_select_user_transactions(self, user_id):
#         """Получает транзакции пользователя"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "id": row[0],
#             "from_user_id": row[1],
#             "to_user_id": row[2],
#             "amount": row[3],
#             "timestamp": row[4],
#             "description": row[5]
#         }
#         return self.cursor.execute(
#             sql_queries.SELECT_USER_TRANSACTIONS_QUERY, (user_id, user_id)
#         ).fetchall()
#
#     def create_roulette_transaction(self, user_id: int, amount: int, is_win: bool,
#                                     bet_type: str = None, bet_value: str = None,
#                                     result_number: int = None, profit: int = None):
#         """
#         Создает запись о рулеточной транзакции
#         Поддерживает как старые вызовы (3 параметра), так и новые (7 параметров)
#         """
#         try:
#             # Если вызван со старыми параметрами (только user_id, amount, is_win)
#             if bet_type is None and bet_value is None and result_number is None and profit is None:
#                 description = "выигрыш в рулетку" if is_win else "проигрыш в рулетку"
#                 if is_win:
#                     self.sql_insert_transaction(0, user_id, amount, description)
#                 else:
#                     self.sql_insert_transaction(user_id, 0, amount, description)
#                 return True
#
#             # Если вызван с новыми параметрами - сохраняем в roulette_transactions
#             else:
#                 # Если profit не указан, рассчитываем автоматически
#                 if profit is None:
#                     profit = amount if is_win else -amount
#
#                 self.cursor.execute(
#                     sql_queries.INSERT_ROULETTE_TRANSACTION_QUERY,
#                     (user_id, amount, is_win, bet_type, bet_value, result_number, profit)
#                 )
#                 self.connection.commit()
#                 return True
#
#         except Exception as e:
#             print(f"❌ Ошибка создания рулеточной транзакции: {e}")
#             return False
#
#     # ==================== CHAT METHODS ====================
#
#     def sql_add_user_to_chat(self, chat_id: int, user_id: int):
#         """Добавляет пользователя в чат"""
#         self.cursor.execute(
#             sql_queries.INSERT_USER_TO_CHAT_QUERY,
#             (user_id, chat_id)
#         )
#         self.connection.commit()
#
#     def sql_get_top_rich_in_chat(self, chat_id: int, limit: int = 10):
#         """Получает топ пользователей по балансу в чате"""
#         self.cursor.execute(
#             sql_queries.SELECT_TOP_RICH_IN_CHAT_QUERY,
#             (chat_id, limit)
#         )
#         return self.cursor.fetchall()
#
#     # ==================== NEW METHODS FOR RICH TOP ====================
#
#     def sql_get_chat_users_count(self, chat_id: int) -> int:
#         """Получить общее количество пользователей в чате"""
#         query = "SELECT COUNT(*) FROM user_chats WHERE CHAT_ID = ?"
#         result = self.execute_query(query, (chat_id,), fetch=True)
#         return result[0][0] if result else 0
#
#     def sql_get_user_rank_in_chat(self, chat_id: int, user_id: int) -> int:
#         """Получить позицию пользователя в общем рейтинге чата"""
#         try:
#             query = """
#             SELECT position FROM (
#                 SELECT telegram_id, ROW_NUMBER() OVER (ORDER BY COINS DESC) as position
#                 FROM telegram_users
#                 WHERE telegram_id IN (SELECT USER_ID FROM user_chats WHERE CHAT_ID = ?)
#             ) ranked WHERE telegram_id = ?
#             """
#             result = self.execute_query(query, (chat_id, user_id), fetch=True)
#             return result[0][0] if result else None
#         except Exception as e:
#             print(f"❌ Ошибка получения ранга пользователя: {e}")
#             return None
#
#     def sql_get_user_data(self, user_id: int):
#         """Получить данные пользователя"""
#         try:
#             query = "SELECT TELEGRAM_ID, USERNAME, FIRST_NAME, COINS FROM telegram_users WHERE TELEGRAM_ID = ?"
#             result = self.execute_query(query, (user_id,), fetch=True)
#             return result[0] if result else None
#         except Exception as e:
#             print(f"❌ Ошибка получения данных пользователя: {e}")
#             return None
#
#     def sql_get_user_position_and_coins(self, chat_id: int, user_id: int):
#         """Получить позицию и количество монет пользователя в чате"""
#         try:
#             query = """
#             SELECT position, COINS FROM (
#                 SELECT
#                     TELEGRAM_ID,
#                     COINS,
#                     ROW_NUMBER() OVER (ORDER BY COINS DESC) as position
#                 FROM telegram_users
#                 WHERE TELEGRAM_ID IN (SELECT USER_ID FROM user_chats WHERE CHAT_ID = ?)
#             ) ranked WHERE TELEGRAM_ID = ?
#             """
#             result = self.execute_query(query, (chat_id, user_id), fetch=True)
#             if result:
#                 return result[0][0], result[0][1]  # position, coins
#             return None, 0
#         except Exception as e:
#             print(f"❌ Ошибка получения позиции пользователя: {e}")
#             return None, 0
#
#     def execute_query(self, query, params=(), fetch=False):
#         """Универсальный метод выполнения запроса"""
#         try:
#             self.cursor.execute(query, params)
#             if fetch:
#                 return self.cursor.fetchall()
#             self.connection.commit()
#             return True
#         except Exception as e:
#             print(f"❌ Ошибка выполнения запроса: {e}")
#             return None
#
#     # ==================== DAILY RECORDS METHODS ====================
#
#     def add_daily_record(self, user_id: int, username: str, first_name: str, amount: int, chat_id: int):
#         """Добавляет или обновляет ежедневный рекорд для конкретного чата"""
#         try:
#             today = datetime.now().date()
#
#             # Проверяем существующую запись
#             self.cursor.execute(
#                 sql_queries.SELECT_EXISTING_RECORD_QUERY,
#                 (user_id, today, chat_id)
#             )
#             existing = self.cursor.fetchone()
#
#             if existing:
#                 # Обновляем если новая сумма больше
#                 if amount > existing[0]:
#                     self.cursor.execute(
#                         sql_queries.UPDATE_DAILY_RECORD_QUERY,
#                         (amount, username, first_name, user_id, today, chat_id)
#                     )
#                     print(f"🔄 Обновлен рекорд в чате {chat_id}: {username} - {amount}")
#             else:
#                 # Добавляем новую запись
#                 self.cursor.execute(
#                     sql_queries.INSERT_DAILY_RECORD_QUERY,
#                     (user_id, username, first_name, amount, today, chat_id)
#                 )
#                 print(f"✅ Добавлен рекорд в чат {chat_id}: {username} - {amount}")
#
#             self.connection.commit()
#
#         except Exception as e:
#             print(f"❌ Ошибка добавления рекорда: {e}")
#
#     def get_top3_today(self, chat_id: int):
#         """Получает топ-3 рекордов за сегодня для конкретного чата"""
#         try:
#             today = datetime.now().date()
#             self.cursor.execute(sql_queries.SELECT_TOP3_TODAY_QUERY, (today, chat_id))
#             results = self.cursor.fetchall()
#
#             # Форматируем результат
#             top_scores = []
#             for row in results:
#                 username, first_name, amount = row
#                 display_name = first_name if first_name else username
#                 top_scores.append((display_name, amount))
#
#             return top_scores
#
#         except Exception as e:
#             print(f"❌ Ошибка получения топа рекордов: {e}")
#             return []
#
#     def sql_migrate_daily_records(self):
#         """Мигрирует таблицу daily_records, добавляя колонку chat_id если нужно"""
#         try:
#             # Проверяем существует ли колонка chat_id
#             self.cursor.execute("PRAGMA table_info(daily_records)")
#             columns = [column[1] for column in self.cursor.fetchall()]
#
#             if 'chat_id' not in columns:
#                 print("🔄 Добавляем колонку chat_id в daily_records...")
#                 # Добавляем колонку chat_id
#                 self.cursor.execute("ALTER TABLE daily_records ADD COLUMN chat_id INTEGER NOT NULL DEFAULT 0")
#                 self.connection.commit()
#                 print("✅ Колонка chat_id добавлена в daily_records")
#
#                 # Обновляем существующие записи (устанавливаем chat_id = 0 для старых записей)
#                 self.cursor.execute("UPDATE daily_records SET chat_id = 0 WHERE chat_id IS NULL")
#                 self.connection.commit()
#                 print("✅ Существующие записи обновлены")
#             else:
#                 print("✅ Колонка chat_id уже существует в daily_records")
#
#         except Exception as e:
#             print(f"❌ Ошибка миграции daily_records: {e}")
#
#     # ==================== ADMIN METHODS ====================
#
#     def sql_get_total_users(self):
#         """Получает общее количество пользователей"""
#         self.cursor.execute(sql_queries.COUNT_TOTAL_USERS_QUERY)
#         result = self.cursor.fetchone()
#         return result[0] if result else 0
#
#     def sql_get_total_coins(self):
#         """Получает общее количество монет в системе"""
#         self.cursor.execute(sql_queries.SUM_TOTAL_COINS_QUERY)
#         result = self.cursor.fetchone()
#         return result[0] if result and result[0] else 0
#
#     def sql_search_users(self, search_term):
#         """Ищет пользователей по имени или username"""
#         search_term = f"%{search_term}%"
#         self.cursor.row_factory = lambda cursor, row: {
#             "telegram_id": row[0],
#             "username": row[1],
#             "first_name": row[2],
#             "coins": row[3]
#         }
#         self.cursor.execute(
#             sql_queries.SEARCH_USERS_QUERY,
#             (search_term, search_term)
#         )
#         return self.cursor.fetchall()
#
#     def sql_get_all_users(self):
#         """Получает всех пользователей"""
#         self.cursor.row_factory = lambda cursor, row: {
#             "telegram_id": row[0]
#         }
#         self.cursor.execute("SELECT TELEGRAM_ID FROM telegram_users")
#         return self.cursor.fetchall()
#
#     def sql_get_user_registration_date(self, user_id):
#         """Получает дату регистрации пользователя"""
#         return self.sql_select_command("SELECT telegram_id, first_name, username FROM users")
#
#     # ==================== BET HISTORY METHODS ====================
#
#     def get_user_bet_history(self, user_id: int, limit: int = 10):
#         """Получает историю ставок пользователя"""
#         try:
#             # Устанавливаем формат строк
#             self.cursor.row_factory = lambda cursor, row: {
#                 "id": row[0],
#                 "user_id": row[1],
#                 "amount": row[2],
#                 "is_win": row[3],
#                 "bet_type": row[4],
#                 "bet_value": row[5],
#                 "result_number": row[6],
#                 "profit": row[7],
#                 "created_at": row[8]
#             }
#
#             return self.cursor.execute(
#                 sql_queries.SELECT_USER_BET_HISTORY_QUERY,
#                 (user_id, limit)
#             ).fetchall()
#
#         except Exception as e:
#             print(f"❌ Ошибка получения истории ставок: {e}")
#             return []
#
#     # Добавьте в класс Database:
#
#     def sql_create_user_purchases_table(self):
#         """Создает таблицу покупок пользователей"""
#         try:
#             self.cursor.execute("""
#                                 CREATE TABLE IF NOT EXISTS user_purchases
#                                 (
#                                     id
#                                     INTEGER
#                                     PRIMARY
#                                     KEY
#                                     AUTOINCREMENT,
#                                     user_id
#                                     INTEGER
#                                     NOT
#                                     NULL,
#                                     item_id
#                                     INTEGER
#                                     NOT
#                                     NULL,
#                                     item_name
#                                     TEXT
#                                     NOT
#                                     NULL,
#                                     price
#                                     INTEGER
#                                     NOT
#                                     NULL,
#                                     purchased_at
#                                     DATETIME
#                                     DEFAULT
#                                     CURRENT_TIMESTAMP,
#                                     UNIQUE
#                                 (
#                                     user_id,
#                                     item_id
#                                 )
#                                     )
#                                 """)
#             self.connection.commit()
#             print("✅ Таблица user_purchases создана/проверена")
#         except Exception as e:
#             print(f"❌ Ошибка создания таблицы покупок: {e}")
#
#     def sql_create_transfer_limits_table(self):
#         """Создает таблицу для хранения лимитов переводов"""
#         try:
#             self.cursor.execute("""
#                                 CREATE TABLE IF NOT EXISTS transfer_limits
#                                 (
#                                     id
#                                     INTEGER
#                                     PRIMARY
#                                     KEY
#                                     AUTOINCREMENT,
#                                     user_id
#                                     INTEGER
#                                     NOT
#                                     NULL,
#                                     amount
#                                     INTEGER
#                                     NOT
#                                     NULL,
#                                     transfer_time
#                                     DATETIME
#                                     NOT
#                                     NULL,
#                                     created_at
#                                     DATETIME
#                                     DEFAULT
#                                     CURRENT_TIMESTAMP
#                                 )
#                                 """)
#             self.connection.commit()
#             print("✅ Таблица transfer_limits создана/проверена")
#         except Exception as e:
#             print(f"❌ Ошибка создания таблицы transfer_limits: {e}")
#
#     def sql_insert_user_purchase(self, user_id: int, item_id: int, item_name: str, price: int):
#         """Добавляет покупку пользователя"""
#         try:
#             self.cursor.execute(
#                 "INSERT OR IGNORE INTO user_purchases (user_id, item_id, item_name, price) VALUES (?, ?, ?, ?)",
#                 (user_id, item_id, item_name, price)
#             )
#             self.connection.commit()
#             return True
#         except Exception as e:
#             print(f"❌ Ошибка добавления покупки: {e}")
#             return False
#
#     def sql_get_user_purchases(self, user_id: int):
#         """Получает все покупки пользователя"""
#         try:
#             self.cursor.execute("SELECT item_id FROM user_purchases WHERE user_id = ?", (user_id,))
#             rows = self.cursor.fetchall()
#
#             purchases = []
#             for row in rows:
#                 if row and len(row) > 0:
#                     purchases.append(row[0])
#
#             print(f"🔍 Найдено покупок для {user_id}: {purchases}")
#             return purchases
#
#         except Exception as e:
#             print(f"❌ Ошибка получения покупок: {e}")
#             return []
#
#     def sql_insert_transfer_limit(self, user_id: int, amount: int, transfer_time):
#         """Добавляет запись о переводе для лимитов"""
#         try:
#             self.cursor.execute(
#                 "INSERT INTO transfer_limits (user_id, amount, transfer_time) VALUES (?, ?, ?)",
#                 (user_id, amount, transfer_time)
#             )
#             self.connection.commit()
#             return True
#         except Exception as e:
#             print(f"❌ Ошибка добавления перевода в лимиты: {e}")
#             return False
#
#     def sql_get_user_transfers_last_6h(self, user_id: int):
#         """Получает все переводы пользователя за последние 6 часов"""
#         try:
#             self.cursor.row_factory = lambda cursor, row: {
#                 "amount": row[0],
#                 "transfer_time": row[1]
#             }
#             transfers = self.cursor.execute(
#                 "SELECT amount, transfer_time FROM transfer_limits WHERE user_id = ? AND transfer_time >= datetime('now', '-6 hours') ORDER BY transfer_time DESC",
#                 (user_id,)
#             ).fetchall()
#             self.cursor.row_factory = None
#             return transfers
#         except Exception as e:
#             print(f"❌ Ошибка получения переводов за 6 часов: {e}")
#             return []
#
#     def sql_clean_old_transfers(self):
#         """Очищает старые записи о переводах (старше 7 дней)"""
#         try:
#             self.cursor.execute("DELETE FROM transfer_limits WHERE transfer_time < datetime('now', '-7 days')")
#             self.connection.commit()
#             deleted_count = self.cursor.rowcount
#             if deleted_count > 0:
#                 print(f"🗑️ Удалено {deleted_count} старых записей о переводах")
#         except Exception as e:
#             print(f"❌ Ошибка очистки старых переводов: {e}")