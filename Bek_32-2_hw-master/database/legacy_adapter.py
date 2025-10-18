# """
# Адаптер для постепенного перехода со старой системы на SQLAlchemy
# Позволяет использовать старые вызовы с новой базой
# """
# from database import get_db
# from database.crud import *
#
#
# class LegacyDatabaseAdapter:
#     """Адаптер, имитирующий старый интерфейс Database"""
#
#     def __init__(self):
#         self.db = next(get_db())
#
#     # ==================== USER METHODS ====================
#
#     def sql_insert_user_command(self, telegram_id, username, first_name, last_name):
#         UserRepository.get_or_create_user(self.db, telegram_id, username, first_name, last_name)
#
#     def sql_select_user_command(self, telegram_id):
#         user = UserRepository.get_user_by_telegram_id(self.db, telegram_id)
#         if user:
#             return [{
#                 "id": user.id,
#                 "telegram_id": user.telegram_id,
#                 "username": user.username,
#                 "first_name": user.first_name,
#                 "last_name": user.last_name,
#                 "link": user.reference_link,
#                 "coins": user.coins,
#                 "win_coins": user.win_coins,
#                 "defeat_coins": user.defeat_coins,
#                 "max_win_coins": user.max_win_coins,
#                 "min_win_coins": user.min_win_coins
#             }]
#         return []
#
#     def sql_admin_select_user_command(self):
#         users = UserRepository.get_all_users(self.db)
#         return [{
#             "telegram_id": user.telegram_id,
#             "username": user.username,
#             "first_name": user.first_name
#         } for user in users]
#
#     # ==================== REFERENCE METHODS ====================
#
#     def sql_update_user_by_link(self, link, telegram_id):
#         UserRepository.update_reference_link(self.db, telegram_id, link)
#
#     def sql_select_user_link_command(self, telegram_id):
#         user = UserRepository.get_user_by_telegram_id(self.db, telegram_id)
#         if user and user.reference_link:
#             return [{"link": user.reference_link}]
#         return []
#
#     def sql_select_owner_link_command(self, owner_link):
#         user = UserRepository.get_user_by_link(self.db, owner_link)
#         if user:
#             return [{"telegram_id": user.telegram_id}]
#         return []
#
#     def sql_insert_reference_users(self, owner_telegram_id, reference_telegram_users):
#         ReferenceRepository.add_reference(self.db, owner_telegram_id, reference_telegram_users)
#
#     def sql_select_existed_reference_command(self, reference_telegram_users):
#         exists = ReferenceRepository.check_reference_exists(self.db, reference_telegram_users)
#         return [{"id": 1}] if exists else []
#
#     def sql_select_all_reference_command(self, owner_telegram_id):
#         references = ReferenceRepository.get_user_references(self.db, owner_telegram_id)
#         return [{"id": ref.reference_telegram_id} for ref in references]
#
#     # ==================== COINS & STATS METHODS ====================
#
#     def sql_update_user_coins(self, telegram_id, coins):
#         UserRepository.update_user_balance(self.db, telegram_id, coins)
#
#     def sql_update_user_stats(self, telegram_id, win_coins, defeat_coins, max_win_coins, min_win_coins):
#         UserRepository.update_user_stats(self.db, telegram_id, win_coins, defeat_coins, max_win_coins, min_win_coins)
#
#     def get_user_balance(self, user_id: int) -> int:
#         user = UserRepository.get_user_by_telegram_id(self.db, user_id)
#         return user.coins if user else 0
#
#     def update_user_balance(self, user_id: int, new_balance: int):
#         UserRepository.update_user_balance(self.db, user_id, new_balance)
#
#     # ==================== TRANSACTION METHODS ====================
#
#     def sql_insert_transaction(self, from_user_id, to_user_id, amount, description=""):
#         TransactionRepository.create_transaction(self.db, from_user_id, to_user_id, amount, description)
#
#     def sql_select_user_transactions(self, user_id):
#         transactions = TransactionRepository.get_user_transactions(self.db, user_id)
#         return [{
#             "id": t.id,
#             "from_user_id": t.from_user_id,
#             "to_user_id": t.to_user_id,
#             "amount": t.amount,
#             "timestamp": t.timestamp,
#             "description": t.description
#         } for t in transactions]
#
#     def create_roulette_transaction(self, user_id: int, amount: int, is_win: bool,
#                                     bet_type: str = None, bet_value: str = None,
#                                     result_number: int = None, profit: int = None):
#         RouletteRepository.create_roulette_transaction(
#             self.db, user_id, amount, is_win, bet_type, bet_value, result_number, profit
#         )
#         return True
#
#     # ==================== CHAT METHODS ====================
#
#     def sql_add_user_to_chat(self, chat_id: int, user_id: int):
#         ChatRepository.add_user_to_chat(self.db, user_id, chat_id)
#
#     def sql_get_top_rich_in_chat(self, chat_id: int, limit: int = 10):
#         return ChatRepository.get_top_rich_in_chat(self.db, chat_id, limit)
#
#     def sql_get_chat_users_count(self, chat_id: int) -> int:
#         return ChatRepository.get_chat_users_count(self.db, chat_id)
#
#     def sql_get_user_rank_in_chat(self, chat_id: int, user_id: int) -> int:
#         return ChatRepository.get_user_rank_in_chat(self.db, chat_id, user_id)
#
#     def sql_get_user_data(self, user_id: int):
#         user = UserRepository.get_user_by_telegram_id(self.db, user_id)
#         if user:
#             return (user.telegram_id, user.username, user.first_name, user.coins)
#         return None
#
#     def sql_get_user_position_and_coins(self, chat_id: int, user_id: int):
#         position = ChatRepository.get_user_rank_in_chat(self.db, chat_id, user_id)
#         user = UserRepository.get_user_by_telegram_id(self.db, user_id)
#         coins = user.coins if user else 0
#         return position, coins
#
#     # ==================== DAILY RECORDS METHODS ====================
#
#     def add_daily_record(self, user_id: int, username: str, first_name: str, amount: int, chat_id: int):
#         DailyRecordRepository.add_or_update_daily_record(self.db, user_id, username, first_name, amount, chat_id)
#
#     def get_top3_today(self, chat_id: int):
#         return DailyRecordRepository.get_top3_today(self.db, chat_id)
#
#     # ==================== ADMIN METHODS ====================
#
#     def sql_get_total_users(self):
#         return UserRepository.get_total_users_count(self.db)
#
#     def sql_get_total_coins(self):
#         return UserRepository.get_total_coins_sum(self.db)
#
#     def sql_search_users(self, search_term):
#         users = UserRepository.search_users(self.db, search_term)
#         return [{
#             "telegram_id": user.telegram_id,
#             "username": user.username,
#             "first_name": user.first_name,
#             "coins": user.coins
#         } for user in users]
#
#     def sql_get_all_users(self):
#         users = UserRepository.get_all_users(self.db)
#         return [{"telegram_id": user.telegram_id} for user in users]
#
#     # ==================== BET HISTORY METHODS ====================
#
#     def get_user_bet_history(self, user_id: int, limit: int = 10):
#         bets = RouletteRepository.get_user_bet_history(self.db, user_id, limit)
#         return [{
#             "id": bet.id,
#             "user_id": bet.user_id,
#             "amount": bet.amount,
#             "is_win": bet.is_win,
#             "bet_type": bet.bet_type,
#             "bet_value": bet.bet_value,
#             "result_number": bet.result_number,
#             "profit": bet.profit,
#             "created_at": bet.created_at
#         } for bet in bets]
#
#     # ==================== SHOP METHODS ====================
#
#     def sql_insert_user_purchase(self, user_id: int, item_id: int, item_name: str, price: int):
#         ShopRepository.add_user_purchase(self.db, user_id, item_id, item_name, price)
#         return True
#
#     def sql_get_user_purchases(self, user_id: int):
#         return ShopRepository.get_user_purchases(self.db, user_id)
#
#     # ==================== TRANSFER LIMIT METHODS ====================
#
#     def sql_insert_transfer_limit(self, user_id: int, amount: int, transfer_time):
#         TransferLimitRepository.add_transfer_limit(self.db, user_id, amount, transfer_time)
#         return True
#
#     def sql_get_user_transfers_last_6h(self, user_id: int):
#         transfers = TransferLimitRepository.get_user_transfers_last_6h(self.db, user_id)
#         return [{
#             "amount": t.amount,
#             "transfer_time": t.transfer_time
#         } for t in transfers]
#
#     def sql_clean_old_transfers(self):
#         return TransferLimitRepository.clean_old_transfers(self.db)
#
#
# # Глобальный экземпляр для обратной совместимости
# db = LegacyDatabaseAdapter()