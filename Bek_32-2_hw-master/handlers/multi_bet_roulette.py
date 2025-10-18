# import random
# from typing import List, Dict, Tuple
#
#
# class MultiBetRoulette:
#     def __init__(self):
#         self.players_bets = {}
#         self.winning_number = None
#
#     def place_bet(self, player_name: str, bet_type: str, amount: int, numbers=None):
#         """Размещение ставки игрока"""
#         if player_name not in self.players_bets:
#             self.players_bets[player_name] = []
#
#         bet = {
#             'type': bet_type,
#             'amount': amount,
#             'numbers': numbers if numbers else []
#         }
#
#         self.players_bets[player_name].append(bet)
#         return bet
#
#     def spin_roulette(self):
#         """Вращение рулетки - определение выигрышного номера"""
#         self.winning_number = random.randint(0, 36)
#         return self.winning_number
#
#     def calculate_payout(self, bet_type: str, bet_numbers: List[int], amount: int) -> int:
#         """Расчет выигрыша для ставки"""
#         if self.winning_number is None:
#             return 0
#
#         if bet_type == 'number':
#             # Ставка на конкретный номер (выигрыш 35:1)
#             if self.winning_number in bet_numbers:
#                 return amount * 36
#             return 0
#
#         elif bet_type == 'red':
#             # Ставка на красное (выигрыш 1:1)
#             red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
#             if self.winning_number in red_numbers:
#                 return amount * 2
#             return 0
#
#         elif bet_type == 'black':
#             # Ставка на черное (выигрыш 1:1)
#             black_numbers = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
#             if self.winning_number in black_numbers:
#                 return amount * 2
#             return 0
#
#         elif bet_type == 'zero':
#             # Ставка на зеро (выигрыш 35:1)
#             if self.winning_number == 0:
#                 return amount * 36
#             return 0
#
#         elif bet_type == 'range':
#             # Ставка на диапазон (например, 0-2)
#             if self.winning_number in bet_numbers:
#                 return amount * 3  # Для примера - зависит от диапазона
#             return 0
#
#         return 0
#
#     def process_all_bets(self) -> Dict[str, List[Tuple[Dict, int]]]:
#         """Обработка всех ставок и расчет выигрышей"""
#         if self.winning_number is None:
#             return {}
#
#         results = {}
#
#         for player_name, bets in self.players_bets.items():
#             player_results = []
#             for bet in bets:
#                 payout = self.calculate_payout(
#                     bet['type'],
#                     bet['numbers'],
#                     bet['amount']
#                 )
#                 player_results.append((bet, payout))
#
#             results[player_name] = player_results
#
#         return results
#
#     def clear_bets(self):
#         """Очистка всех ставок"""
#         self.players_bets = {}
#         self.winning_number = None
#
