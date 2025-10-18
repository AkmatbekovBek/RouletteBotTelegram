# handlers/history_service.py
from datetime import datetime, date
from typing import List, Dict
from aiogram import types, Dispatcher
from database import get_db
from database.crud import UserRepository, TransactionRepository


class HistoryHandler:
    """Handler for history-related bot commands"""

    def __init__(self):
        pass

    def _format_time(self, timestamp) -> str:
        """Format timestamp to [HH:MM:SS] format"""
        try:
            if not timestamp:
                return '[--:--:--]'

            if isinstance(timestamp, datetime):
                return timestamp.strftime('[%H:%M:%S]')

            if isinstance(timestamp, str):
                timestamp = timestamp.replace('T', ' ').replace('Z', '')

                formats = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%H:%M:%S',
                    '%H:%M:%S.%f'
                ]

                for fmt in formats:
                    try:
                        dt = datetime.strptime(timestamp, fmt)
                        return dt.strftime('[%H:%M:%S]')
                    except ValueError:
                        continue

            return '[--:--:--]'
        except Exception:
            return '[--:--:--]'

    def _is_today(self, timestamp) -> bool:
        """Check if timestamp is from today"""
        try:
            if isinstance(timestamp, datetime):
                return timestamp.date() == date.today()
            elif isinstance(timestamp, str):
                timestamp = timestamp.replace('T', ' ').replace('Z', '')
                formats = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f'
                ]
                for fmt in formats:
                    try:
                        dt = datetime.strptime(timestamp, fmt)
                        return dt.date() == date.today()
                    except ValueError:
                        continue
            return False
        except:
            return False

    def _calculate_net_profit_for_bet(self, bet):
        """Calculate NET profit for a single bet"""
        if bet.is_win:
            # ВЫИГРЫШ: чистая прибыль = (общий выигрыш - ставка)
            if hasattr(bet, 'profit') and bet.profit is not None:
                total_win = bet.profit  # Это общая сумма выигрыша
                net_profit = total_win - bet.amount  # Чистая прибыль = общий выигрыш - ставка
                return net_profit
            else:
                # Fallback если profit нет
                return bet.amount  # Стандартный выигрыш 2x: чистая прибыль = ставка
        else:
            # ПРОИГРЫШ: чистая прибыль = -ставка
            return -bet.amount

    async def show_complete_history(self, message: types.Message):
        """Show complete history with bets and transfers (max 12 lines)"""
        try:
            user_id = message.from_user.id

            db = next(get_db())
            user = UserRepository.get_user_by_telegram_id(db, user_id)
            if not user:
                await message.answer("Сначала зарегистрируйтесь через /start")
                return

            from database.crud import RouletteRepository

            # Получаем историю ставок
            bet_history = RouletteRepository.get_user_bet_history(db, user_id, 50)

            # Получаем историю транзакций
            transactions = TransactionRepository.get_user_transactions(db, user_id, limit=50)

            # Список для всех записей истории за сегодня
            all_history_entries = []

            # Обрабатываем ставки с чистой прибылью (только за сегодня)
            if bet_history:
                for bet in bet_history:
                    if not self._is_today(bet.created_at):
                        continue

                    net_profit = self._calculate_net_profit_for_bet(bet)
                    time_str = self._format_time(bet.created_at)

                    if net_profit > 0:
                        all_history_entries.append({
                            'timestamp': bet.created_at,
                            'text': f"{time_str} 🎰 Выигрыш: +{net_profit:,}"
                        })
                    elif net_profit < 0:
                        all_history_entries.append({
                            'timestamp': bet.created_at,
                            'text': f"{time_str} 🎰 Проигрыш: {net_profit:,}"
                        })
                    else:
                        all_history_entries.append({
                            'timestamp': bet.created_at,
                            'text': f"{time_str} 🎰 Ничья: 0"
                        })

            # Обрабатываем транзакции (только за сегодня)
            if transactions:
                for transaction in transactions:
                    if not self._is_today(transaction.timestamp):
                        continue

                    time_str = self._format_time(transaction.timestamp)

                    if transaction.from_user_id == user_id:
                        # Исходящая транзакция
                        if transaction.to_user_id:
                            target_user = UserRepository.get_user_by_telegram_id(db, transaction.to_user_id)
                            target_name = target_user.first_name if target_user else "Аноним"
                            if transaction.amount > 0:
                                all_history_entries.append({
                                    'timestamp': transaction.timestamp,
                                    'text': f"{time_str} 💸 Перевод: -{transaction.amount:,} для {target_name}"
                                })
                    else:
                        # Входящая транзакция
                        if transaction.from_user_id:
                            source_user = UserRepository.get_user_by_telegram_id(db, transaction.from_user_id)
                            source_name = source_user.first_name if source_user else "Аноним"
                            if transaction.amount > 0:
                                all_history_entries.append({
                                    'timestamp': transaction.timestamp,
                                    'text': f"{time_str} 💰 Получено: +{transaction.amount:,} от {source_name}"
                                })

            if not all_history_entries:
                await message.answer("📊 *История операций за сегодня:*\nПока нет записей")
                return

            # Сортируем все записи по времени (от старых к новым)
            all_history_entries.sort(key=lambda x: x['timestamp'])

            # Берем последние 12 записей (самые новые)
            recent_history = all_history_entries[-12:]

            # Формируем итоговый текст
            history_lines = [entry['text'] for entry in recent_history]

            history_text = f"📊 *История операций\n" + "\n".join(history_lines)

            await message.answer(history_text)

        except Exception as e:
            await message.answer("Произошла ошибка при получении истории")


def register_history_handlers(dp: Dispatcher):
    """Register all history handlers"""
    handler = HistoryHandler()

    dp.register_message_handler(
        handler.show_complete_history,
        lambda m: m.text and m.text.lower().strip() in ["история", "history", "ист", "полная история"]
    )