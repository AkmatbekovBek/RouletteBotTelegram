# # database/sql_queries.py
# """SQL queries for the bot database"""
#
# # ==================== TABLE CREATION QUERIES ====================
#
# CREATE_USER_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS telegram_users
# (
#     ID INTEGER PRIMARY KEY,
#     TELEGRAM_ID INTEGER,
#     USERNAME CHAR(50),
#     FIRST_NAME CHAR(50),
#     LAST_NAME CHAR(50),
#     REFERENCE_LINK TEXT NULL,
#     COINS INTEGER DEFAULT 5000,
#     WIN_COINS INTEGER DEFAULT 0,
#     DEFEAT_COINS INTEGER DEFAULT 0,
#     MAX_WIN_COINS INTEGER DEFAULT 0,
#     MIN_WIN_COINS INTEGER DEFAULT 0,
#     UNIQUE (TELEGRAM_ID)
# )
# """
#
# CREATE_REFERENCE_USERS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS reference_users
# (
#     ID INTEGER PRIMARY KEY,
#     OWNER_TELEGRAM_ID INTEGER,
#     REFERENCE_TELEGRAM_ID INTEGER
# )
# """
#
# CREATE_TRANSACTIONS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS transactions
# (
#     ID INTEGER PRIMARY KEY,
#     FROM_USER_ID INTEGER,
#     TO_USER_ID INTEGER,
#     AMOUNT INTEGER,
#     TIMESTAMP DATETIME DEFAULT CURRENT_TIMESTAMP,
#     DESCRIPTION TEXT
# )
# """
#
# CREATE_USER_CHATS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS user_chats
# (
#     ID INTEGER PRIMARY KEY,
#     USER_ID INTEGER,
#     CHAT_ID INTEGER,
#     JOINED_AT DATETIME DEFAULT CURRENT_TIMESTAMP,
#     UNIQUE (USER_ID, CHAT_ID)
# )
# """
#
# CREATE_DAILY_RECORDS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS daily_records
# (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL,
#     username TEXT NOT NULL,
#     first_name TEXT,
#     amount INTEGER NOT NULL,
#     record_date DATE NOT NULL,
#     chat_id INTEGER NOT NULL DEFAULT 0,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
# )
# """
#
# CREATE_ROULETTE_TRANSACTIONS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS roulette_transactions
# (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL,
#     amount INTEGER NOT NULL,
#     is_win BOOLEAN NOT NULL,
#     bet_type TEXT,
#     bet_value TEXT,
#     result_number INTEGER,
#     profit INTEGER,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
# )
# """
#
# # ==================== USER QUERIES ====================
#
# START_INSERT_USER_QUERY = """
# INSERT OR IGNORE INTO telegram_users
# VALUES (?,?,?,?,?,?,5000,0,0,0,0)
# """
#
# SELECT_USER_QUERY = "SELECT * FROM telegram_users WHERE TELEGRAM_ID = ?"
#
# SELECT_ALL_USERS_QUERY = "SELECT * FROM telegram_users"
#
# UPDATE_USER_BY_LINK_QUERY = """
# UPDATE telegram_users SET REFERENCE_LINK = ? WHERE TELEGRAM_ID = ?
# """
#
# SELECT_USER_LINK_QUERY = """
# SELECT REFERENCE_LINK FROM telegram_users WHERE TELEGRAM_ID = ?
# """
#
# SELECT_OWNER_LINK_QUERY = """
# SELECT TELEGRAM_ID FROM telegram_users WHERE REFERENCE_LINK = ?
# """
#
# UPDATE_USER_COINS_QUERY = """
# UPDATE telegram_users SET COINS = ? WHERE TELEGRAM_ID = ?
# """
#
# UPDATE_USER_STATS_QUERY = """
# UPDATE telegram_users SET WIN_COINS = ?, DEFEAT_COINS = ?,
# MAX_WIN_COINS = ?, MIN_WIN_COINS = ? WHERE TELEGRAM_ID = ?
# """
#
# SELECT_USER_BALANCE_QUERY = """
# SELECT COINS FROM telegram_users WHERE TELEGRAM_ID = ?
# """
#
# # ==================== REFERENCE QUERIES ====================
#
# INSERT_REFERENCE_USERS_QUERY = """
# INSERT OR IGNORE INTO reference_users VALUES (?,?,?)
# """
#
# SELECT_EXIST_REFERENCE_QUERY = """
# SELECT REFERENCE_TELEGRAM_ID FROM reference_users WHERE REFERENCE_TELEGRAM_ID = ?
# """
#
# SELECT_ALL_REFERENCE_QUERY = """
# SELECT * FROM reference_users WHERE OWNER_TELEGRAM_ID = ?
# """
#
# # ==================== TRANSACTION QUERIES ====================
#
# INSERT_TRANSACTION_QUERY = """
# INSERT INTO transactions VALUES (?, ?, ?, ?, datetime('now'), ?)
# """
#
# SELECT_USER_TRANSACTIONS_QUERY = """
# SELECT * FROM transactions
# WHERE FROM_USER_ID = ? OR TO_USER_ID = ?
# ORDER BY TIMESTAMP DESC
# LIMIT 10
# """
#
# # ==================== ROULETTE TRANSACTION QUERIES ====================
#
# INSERT_ROULETTE_TRANSACTION_QUERY = """
# INSERT INTO roulette_transactions
# (user_id, amount, is_win, bet_type, bet_value, result_number, profit, created_at)
# VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
# """
#
# SELECT_USER_BET_HISTORY_QUERY = """
# SELECT * FROM roulette_transactions
# WHERE user_id = ?
# ORDER BY created_at DESC
# LIMIT ?
# """
#
# # ==================== CHAT QUERIES ====================
#
# INSERT_USER_TO_CHAT_QUERY = """
# INSERT OR IGNORE INTO user_chats (USER_ID, CHAT_ID) VALUES (?, ?)
# """
#
# SELECT_TOP_RICH_IN_CHAT_QUERY = """
# SELECT tu.USERNAME, tu.FIRST_NAME, tu.COINS
# FROM telegram_users tu
# JOIN user_chats uc ON tu.TELEGRAM_ID = uc.USER_ID
# WHERE uc.CHAT_ID = ?
# ORDER BY tu.COINS DESC
# LIMIT ?
# """
#
# # ==================== DAILY RECORDS QUERIES ====================
#
# INSERT_DAILY_RECORD_QUERY = """
# INSERT INTO daily_records (user_id, username, first_name, amount, record_date, chat_id)
# VALUES (?, ?, ?, ?, ?, ?)
# """
#
# UPDATE_DAILY_RECORD_QUERY = """
# UPDATE daily_records SET amount = ?, username = ?, first_name = ?
# WHERE user_id = ? AND record_date = ? AND chat_id = ?
# """
#
# SELECT_EXISTING_RECORD_QUERY = """
# SELECT amount FROM daily_records WHERE user_id = ? AND record_date = ? AND chat_id = ?
# """
#
# SELECT_TOP3_TODAY_QUERY = """
# SELECT username, first_name, amount
# FROM daily_records
# WHERE record_date = ? AND chat_id = ?
# ORDER BY amount DESC LIMIT 3
# """
#
# # ==================== ADMIN QUERIES ====================
#
# COUNT_TOTAL_USERS_QUERY = "SELECT COUNT(*) FROM telegram_users"
#
# SUM_TOTAL_COINS_QUERY = "SELECT SUM(COINS) FROM telegram_users"
#
# SEARCH_USERS_QUERY = """
# SELECT TELEGRAM_ID, USERNAME, FIRST_NAME, COINS
# FROM telegram_users
# WHERE USERNAME LIKE ? OR FIRST_NAME LIKE ?
# """
#
# # ==================== ROULETTE GAME LOGS QUERIES ====================
#
# CREATE_ROULETTE_GAME_LOGS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS roulette_game_logs (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     chat_id INTEGER NOT NULL,
#     result INTEGER NOT NULL,
#     color_emoji TEXT NOT NULL,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
# )
# """
#
# INSERT_ROULETTE_GAME_LOG_QUERY = """
# INSERT INTO roulette_game_logs (chat_id, result, color_emoji, created_at)
# VALUES (?, ?, ?, datetime('now'))
# """
#
# SELECT_RECENT_GAME_LOGS_QUERY = """
# SELECT result, color_emoji, created_at
# FROM roulette_game_logs
# WHERE chat_id = ?
# ORDER BY created_at DESC
# LIMIT ?
# """
#
# SELECT_ALL_GAME_LOGS_QUERY = """
# SELECT result, color_emoji, created_at
# FROM roulette_game_logs
# WHERE chat_id = ?
# ORDER BY created_at DESC
# LIMIT 50
# """
#
# COUNT_GAME_LOGS_QUERY = """
# SELECT COUNT(*) FROM roulette_game_logs WHERE chat_id = ?
# """
#
# CREATE_TRANSFER_LIMITS_TABLE_QUERY = """
# CREATE TABLE IF NOT EXISTS transfer_limits (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL,
#     amount INTEGER NOT NULL,
#     transfer_time DATETIME NOT NULL,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
# )
# """
#
# INSERT_TRANSFER_LIMIT_QUERY = """
# INSERT INTO transfer_limits (user_id, amount, transfer_time)
# VALUES (?, ?, ?)
# """
#
# SELECT_USER_TRANSFERS_LAST_6H_QUERY = """
# SELECT amount, transfer_time
# FROM transfer_limits
# WHERE user_id = ? AND transfer_time >= datetime('now', '-6 hours')
# ORDER BY transfer_time DESC
# """
#
# DELETE_OLD_TRANSFERS_QUERY = """
# DELETE FROM transfer_limits
# WHERE transfer_time < datetime('now', '-7 days')
# """
