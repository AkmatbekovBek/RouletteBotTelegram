# handlers/history_service.py
from datetime import datetime, date
from typing import List, Dict
from aiogram import types, Dispatcher
from aiogram.utils.markdown import escape_md
from database import get_db
from database.crud import UserRepository, TransactionRepository, GiftRepository


class HistoryHandler:
    """Handler for history-related bot commands"""

    def __init__(self):
        pass

    def _is_donation_transaction(self, transaction) -> bool:
        """Проверяет, является ли транзакция донатом"""
        donation_markers = [
            "админ пополнение",
            "админ награда",
            "💎 ДОНАТ от администратора",
            "donate",
            "донат"
        ]

        description = (transaction.description or "").lower()
        return any(marker.lower() in description for marker in donation_markers)

    def _is_gift_transaction(self, transaction) -> bool:
        """Проверяет, является ли транзакция подарком"""
        gift_markers = [
            "подарок",
            "подарил",
            "получил в подарок",
            "gift",
            "🎁"
        ]

        description = (transaction.description or "").lower()
        return any(marker in description for marker in gift_markers)

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

    def _get_user_display_name(self, user) -> str:
        """Оптимизированное получение отображаемого имени"""
        if not user:
            return "Аноним"

        if user.first_name:
            sanitized_name = self._sanitize_name(user.first_name)
            if sanitized_name != "Аноним":
                return sanitized_name

        if user.username:
            return f"@{user.username}"

        return "Аноним"

    def _sanitize_name(self, name: str) -> str:
        """Оптимизированная очистка имени от невидимых символов"""
        if not name:
            return "Аноним"

        cleaned = ''.join(c for c in name.strip()
                          if ord(c) >= 32 and c not in ['\u200B', '\u0000', '\x00'])[:100]
        return cleaned or "Аноним"

    async def show_complete_history(self, message: types.Message):
        """Show complete history with bets, transfers and gifts (max 12 lines)"""
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

            # Получаем историю подарков пользователя - ВСЕ подарки
            user_gifts = GiftRepository.get_user_gifts(db, user_id)

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

            # Обрабатываем транзакции (только за сегодня) - ВКЛЮЧАЕМ подарки
            if transactions:
                for transaction in transactions:
                    if not self._is_today(transaction.timestamp):
                        continue

                    time_str = self._format_time(transaction.timestamp)

                    # Проверяем, является ли транзакция донатом
                    if self._is_donation_transaction(transaction) and transaction.to_user_id == user_id:
                        all_history_entries.append({
                            'timestamp': transaction.timestamp,
                            'text': f"{time_str} 💎 Донат: +{transaction.amount:,}"
                        })
                    # Обрабатываем транзакции подарков
                    elif self._is_gift_transaction(transaction):
                        description = transaction.description or ""

                        if transaction.to_user_id == user_id and "получил в подарок" in description.lower():
                            # Получение подарка от другого игрока
                            gift_desc = description.replace("получил в подарок ", "").replace(" от игрока", "")
                            source_user = UserRepository.get_user_by_telegram_id(db, transaction.from_user_id)
                            source_name = self._get_user_display_name(source_user) if source_user else "Аноним"
                            all_history_entries.append({
                                'timestamp': transaction.timestamp,
                                'text': f"{time_str} 🎁 Получен подарок: {gift_desc} от {source_name}"
                            })
                        elif transaction.from_user_id == user_id and "подарил" in description.lower():
                            # Отправка подарка другому игроку
                            gift_desc = description.replace("подарил ", "").replace(" игроку", "")
                            target_user = UserRepository.get_user_by_telegram_id(db, transaction.to_user_id)
                            target_name = self._get_user_display_name(target_user) if target_user else "Аноним"
                            all_history_entries.append({
                                'timestamp': transaction.timestamp,
                                'text': f"{time_str} 🎁 Подарок отправлен: {gift_desc} для {target_name}"
                            })
                    elif transaction.from_user_id == user_id:
                        # Исходящая транзакция (кроме подарков)
                        if transaction.to_user_id:
                            target_user = UserRepository.get_user_by_telegram_id(db, transaction.to_user_id)
                            target_name = self._get_user_display_name(target_user) if target_user else "Аноним"
                            if transaction.amount > 0:
                                all_history_entries.append({
                                    'timestamp': transaction.timestamp,
                                    'text': f"{time_str} 💸 Перевод: -{transaction.amount:,} для {target_name}"
                                })
                    else:
                        # Входящая транзакция (кроме подарков)
                        if transaction.from_user_id:
                            source_user = UserRepository.get_user_by_telegram_id(db, transaction.from_user_id)
                            source_name = self._get_user_display_name(source_user) if source_user else "Аноним"
                            if transaction.amount > 0:
                                all_history_entries.append({
                                    'timestamp': transaction.timestamp,
                                    'text': f"{time_str} 💰 Получено: +{transaction.amount:,} от {source_name}"
                                })

            # Обрабатываем подарки из таблицы user_gifts (только за сегодня) - ТОЛЬКО покупки
            if user_gifts:
                for user_gift in user_gifts:
                    if not self._is_today(user_gift.created_at):
                        continue

                    time_str = self._format_time(user_gift.created_at)
                    gift = GiftRepository.get_gift_by_id(db, user_gift.gift_id)

                    if gift:
                        if user_gift.quantity > 0:
                            # ПОКУПКА подарка (положительное количество)
                            all_history_entries.append({
                                'timestamp': user_gift.created_at,
                                'text': f"{time_str} 🎁 Куплен подарок: {gift.name} x{user_gift.quantity}"
                            })
                        # НЕ обрабатываем отправку подарков здесь - они уже обработаны в транзакциях

            if not all_history_entries:
                await message.answer("📊 *История операций за сегодня:*\nПока нет записей")
                return

            # Сортируем все записи по времени (от старых к новым)
            all_history_entries.sort(key=lambda x: x['timestamp'])

            # Берем последние 12 записей (самые новые)
            recent_history = all_history_entries[-12:]

            # Формируем итоговый текст
            history_lines = [entry['text'] for entry in recent_history]

            history_text = f"📊 *История операций*\n" + "\n".join(history_lines)

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