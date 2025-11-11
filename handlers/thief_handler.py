# donate_product/thief_handler.py
import random
import logging
import re
from datetime import datetime, timedelta
from aiogram import types, Dispatcher
from database import get_db
from database.crud import ThiefRepository, DonateRepository, ShopRepository

logger = logging.getLogger(__name__)


class ThiefHandler:
    def __init__(self):
        self.logger = logger
        self.STEAL_COOLDOWN = 1800  # 30 минут в секундах
        self.VICTIM_COOLDOWN = 1800  # 30 минут защита жертвы
        self.MIN_STEAL_AMOUNT = 100  # Минимальная сумма для кражи
        self.MAX_STEAL_PERCENT = 0.6  # Максимум 60% от баланса
        self.cooldown_dict = {}

    def _check_cooldown(self, user_id: int) -> bool:
        """Проверка кулдауна для защиты от флуда"""
        current_time = datetime.now().timestamp()
        if user_id in self.cooldown_dict:
            if current_time - self.cooldown_dict[user_id] < 10:
                return False
        self.cooldown_dict[user_id] = current_time
        return True

    async def _check_thief_permission(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя права вора в законе"""
        db = next(get_db())
        try:
            # Получаем все привилегии пользователя
            user_purchases = ShopRepository.get_user_purchases(db, user_id)

            # ID привилегий из админ-панели
            PRIVILEGE_IDS = {
                "thief": 1,
                "police": 2,
                "unlimit": 3
            }

            # Проверяем наличие привилегии вора
            if PRIVILEGE_IDS["thief"] in user_purchases:
                # Дополнительно проверяем срок действия
                return await self._check_privilege_expiry(db, user_id, PRIVILEGE_IDS["thief"])

            return False
        except Exception as e:
            self.logger.error(f"Error checking thief permission: {e}")
            return False
        finally:
            db.close()

    async def _check_privilege_expiry(self, db, user_id: int, privilege_id: int) -> bool:
        """Проверяет, не истекла ли привилегия"""
        try:
            from sqlalchemy import text
            result = db.execute(
                text("""
                     SELECT expires_at
                     FROM user_purchases
                     WHERE user_id = :user_id
                       AND item_id = :item_id
                     """),
                {"user_id": user_id, "item_id": privilege_id}
            ).fetchone()

            if result and result[0]:
                # Если есть срок действия, проверяем его
                return result[0] > datetime.now()

            # Если срока нет, привилегия действует вечно
            return True

        except Exception as e:
            self.logger.error(f"Error checking privilege expiry: {e}")
            return True

    def _parse_steal_amount(self, text: str, victim_balance: int) -> int:
        """Парсит сумму кражи из текста команды"""
        try:
            # Убираем все пробелы для удобства парсинга
            text = text.replace(' ', '')

            # Ищем числа (включая отрицательные с дефисом)
            numbers = re.findall(r'-?\d+', text)
            if not numbers:
                return 0

            amount = int(numbers[0])

            # Если сумма отрицательная, берем по модулю
            if amount < 0:
                amount = abs(amount)

            # Проверяем минимальную сумму
            if amount < self.MIN_STEAL_AMOUNT:
                return 0

            return amount  # Возвращаем запрошенную сумму без ограничений
        except Exception as e:
            self.logger.error(f"Error parsing steal amount: {e}")
            return 0

    def _format_time_left(self, seconds: int) -> str:
        """Форматирует оставшееся время"""
        minutes = int(seconds // 60)
        return f"{minutes} минут"

    def _calculate_success_chance(self, steal_amount: int, victim_balance: int) -> float:
        """Рассчитывает шанс успешной кражи"""
        max_possible = int(victim_balance * self.MAX_STEAL_PERCENT)
        base_success_chance = 0.5

        if max_possible == 0:
            return base_success_chance

        amount_ratio = steal_amount / max_possible
        success_chance = base_success_chance * (1 - amount_ratio * 0.5)
        success_chance = max(success_chance, 0.25)

        return success_chance

    async def _perform_steal_attempt(self, thief_id: int, victim_id: int, steal_amount: int, message: types.Message):
        """Выполняет попытку кражи с учетом привилегий"""
        db = next(get_db())
        try:
            victim_balance = ThiefRepository.get_user_balance(db, victim_id) or 0

            # Проверяем, достаточно ли денег у жертвы
            if steal_amount > victim_balance:
                await message.reply(f"❌ У жертвы недостаточно денег! Баланс: {victim_balance:,} монет")
                return

            # Проверяем максимальный процент
            max_allowed = int(victim_balance * self.MAX_STEAL_PERCENT)
            if steal_amount > max_allowed:
                await message.reply(
                    f"❌ Нельзя украсть больше {self.MAX_STEAL_PERCENT * 100}% от баланса! Максимум: {max_allowed:,} монет")
                return

            # Проверяем, является ли жертва полицейским
            is_victim_police = await self._check_police_permission(victim_id)

            # Корректируем шанс успеха если жертва - полицейский
            success_chance = self._calculate_success_chance(steal_amount, victim_balance)
            if is_victim_police:
                success_chance *= 0.5  # Уменьшаем шанс против полицейского
                self.logger.info(f"Victim {victim_id} is police, reduced success chance to {success_chance}")

            is_success = random.random() < success_chance

            thief = await message.bot.get_chat(thief_id)
            victim = await message.bot.get_chat(victim_id)

            if is_success:
                thief_balance = ThiefRepository.get_user_balance(db, thief_id) or 0
                ThiefRepository.update_user_balance(db, victim_id, victim_balance - steal_amount)
                ThiefRepository.update_user_balance(db, thief_id, thief_balance + steal_amount)
                ThiefRepository.record_steal_attempt(db, thief_id, victim_id, True, steal_amount)

                # Сообщения об успехе с учетом полицейского
                if is_victim_police:
                    success_messages = [
                        f"🎯 {thief.full_name} смог обойти бдительность полицейского {victim.full_name} и украл {steal_amount:,}!",
                        f"🎯 Мастерство! {thief.full_name} провернул дело против полицейского {victim.full_name} на {steal_amount:,}!",
                        f"🎯 Невероятно! {thief.full_name} обманул полицейского {victim.full_name} и забрал {steal_amount:,}!",
                    ]
                else:
                    success_messages = [
                        f"✅ {thief.full_name} успешно украл {steal_amount:,} у {victim.full_name}",
                        f"✅ Удача! {thief.full_name} стащил {steal_amount:,} у {victim.full_name}",
                        f"✅ Чисто сработано! {thief.full_name} → {steal_amount:,} ← {victim.full_name}",
                    ]

                success_message = random.choice(success_messages)
                await message.reply(success_message)

            else:
                # Записываем неудачную попытку
                ThiefRepository.record_steal_attempt(db, thief_id, victim_id, False, steal_amount)

                # Сообщения о провале с учетом полицейского
                if is_victim_police:
                    fail_messages = [
                        f"🚨 Полицейский {victim.full_name} поймал {thief.full_name} с поличным!",
                        f"🚨 {thief.full_name}, тебя задержал полицейский {victim.full_name}!",
                        f"🚨 Провал! Полицейский {victim.full_name} был начеку и остановил {thief.full_name}!",
                    ]
                else:
                    fail_messages = [
                        f"❌ {thief.full_name}, тебя заметили! В следующий раз повезет!",
                        f"❌ {thief.full_name}, жертва была начеку! Попробуй еще раз!",
                        f"❌ {thief.full_name}, не повезло в этот раз! Удача ждет тебя!",
                    ]

                fail_message = random.choice(fail_messages)
                await message.reply(fail_message)

            db.commit()

        except Exception as e:
            db.rollback()
            self.logger.error(f"Database error in steal attempt: {e}")
            await message.reply("❌ Ошибка при попытке кражи.")
        finally:
            db.close()

    def _check_steal_cooldowns(self, db, thief_id: int, victim_id: int) -> tuple:
        """Проверяет все кулдауны для кражи"""
        try:
            # 🔥 ДОБАВЛЯЕМ проверку ареста
            try:
                from database.crud import PoliceRepository
                arrest = PoliceRepository.get_user_arrest(db, thief_id)
                if arrest and arrest.release_time > datetime.now():
                    time_left = arrest.release_time - datetime.now()
                    minutes_left = int(time_left.total_seconds() // 60)
                    hours_left = int(minutes_left // 60)
                    if hours_left > 0:
                        return False, f"🔒 Вы арестованы! Освобождение через {hours_left}ч {minutes_left % 60}м"
                    else:
                        return False, f"🔒 Вы арестованы! Освобождение через {minutes_left} минут"
            except Exception as arrest_error:
                self.logger.error(f"❌ Ошибка проверки ареста: {arrest_error}")
                # Продолжаем если ошибка

            # Убрали проверку ареста, так как ареста больше нет

            # Проверяем кулдаун вора
            last_steal = ThiefRepository.get_last_steal_time(db, thief_id)
            if last_steal:
                time_since_last_steal = datetime.now() - last_steal
                if time_since_last_steal.total_seconds() < self.STEAL_COOLDOWN:
                    time_left = self.STEAL_COOLDOWN - time_since_last_steal.total_seconds()
                    minutes_left = int(time_left // 60)
                    return False, f"⏳ Подождите еще {minutes_left} минут перед следующей попыткой!"

            # Проверяем кулдаун жертвы
            last_victim_steal = ThiefRepository.get_last_steal_time_by_victim(db, victim_id)
            if last_victim_steal:
                time_since_victim_steal = datetime.now() - last_victim_steal
                if time_since_victim_steal.total_seconds() < self.VICTIM_COOLDOWN:
                    time_left = self.VICTIM_COOLDOWN - time_since_victim_steal.total_seconds()
                    minutes_left = int(time_left // 60)
                    return False, f"🛡️ Этого пользователя недавно крали! Подождите еще {minutes_left} минут"

            return True, ""

        except Exception as e:
            self.logger.error(f"Error in _check_steal_cooldowns: {e}")
            # В случае ошибки разрешаем кражу, но логируем ошибку
            return True, ""

    async def _check_police_permission(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя права полицейского"""
        db = next(get_db())
        try:
            user_purchases = ShopRepository.get_user_purchases(db, user_id)
            POLICE_PRIVILEGE_ID = 2

            if POLICE_PRIVILEGE_ID in user_purchases:
                return await self._check_privilege_expiry(db, user_id, POLICE_PRIVILEGE_ID)

            return False
        except Exception as e:
            self.logger.error(f"Error checking police permission: {e}")
            return False
        finally:
            db.close()

    async def steal_money(self, message: types.Message):
        """Команда 'красть' - попытка украсть деньги у пользователя"""
        try:
            user_id = message.from_user.id

            if not await self._check_thief_permission(user_id):
                await message.reply("🚫 Эта команда доступна только для Воров в законе!")
                return

            if not self._check_cooldown(message.from_user.id):
                await message.reply("⏳ Подождите 10 секунд.")
                return

            if not message.reply_to_message:
                await message.reply("❗ Ответь на сообщение пользователя.")
                return

            thief = message.from_user
            victim = message.reply_to_message.from_user

            if thief.id == victim.id:
                await message.reply("❌ Нельзя красть у самого себя!")
                return

            bot_user = await message.bot.get_me()
            if victim.id == bot_user.id:
                await message.reply("❌ Нельзя красть у бота!")
                return

            db = next(get_db())
            try:
                # Проверка кулдаунов
                cooldown_ok, cooldown_message = self._check_steal_cooldowns(db, thief.id, victim.id)
                if not cooldown_ok:
                    await message.reply(cooldown_message)
                    return

                victim_balance = ThiefRepository.get_user_balance(db, victim.id) or 0
                if victim_balance < self.MIN_STEAL_AMOUNT:
                    await message.reply(f"⚠️ У жертвы недостаточно денег! Минимум: {self.MIN_STEAL_AMOUNT:,} монет")
                    return

                steal_amount = self._parse_steal_amount(message.text, victim_balance)
                specified_amount = steal_amount > 0

                if not specified_amount:
                    # Случайная сумма между MIN_STEAL_AMOUNT и 60% от баланса
                    min_amount = self.MIN_STEAL_AMOUNT
                    max_amount = int(victim_balance * self.MAX_STEAL_PERCENT)
                    steal_amount = random.randint(min_amount, max_amount)

                await self._perform_steal_attempt(thief.id, victim.id, steal_amount, message)

            except Exception as e:
                self.logger.error(f"Database error in steal_money: {e}")
                await message.reply("❌ Ошибка при попытке кражи.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in steal_money: {e}")
            await message.reply("❌ Ошибка при обработке команды.")

    async def steal_with_prefix(self, message: types.Message):
        """Обработчик для команд с префиксом '-' (например: '-5000')"""
        try:
            user_id = message.from_user.id

            if not await self._check_thief_permission(user_id):
                await message.reply("🚫 Эта команда доступна только для Воров в законе!")
                return

            if not self._check_cooldown(message.from_user.id):
                await message.reply("⏳ Подождите 10 секунд.")
                return

            if not message.reply_to_message:
                await message.reply("❗ Ответь на сообщение пользователя.")
                return

            thief = message.from_user
            victim = message.reply_to_message.from_user

            if thief.id == victim.id:
                await message.reply("❌ Нельзя красть у самого себя!")
                return

            bot_user = await message.bot.get_me()
            if victim.id == bot_user.id:
                await message.reply("❌ Нельзя красть у бота!")
                return

            db = next(get_db())
            try:
                # Проверка кулдаунов
                cooldown_ok, cooldown_message = self._check_steal_cooldowns(db, thief.id, victim.id)
                if not cooldown_ok:
                    await message.reply(cooldown_message)
                    return

                victim_balance = ThiefRepository.get_user_balance(db, victim.id) or 0
                if victim_balance < self.MIN_STEAL_AMOUNT:
                    await message.reply(f"⚠️ У жертвы недостаточно денег! Минимум: {self.MIN_STEAL_AMOUNT:,} монет")
                    return

                # Парсим сумму с префиксом '-'
                steal_amount = self._parse_steal_amount(message.text, victim_balance)

                if steal_amount == 0:
                    await message.reply(
                        f"❌ Минимальная сумма для кражи: {self.MIN_STEAL_AMOUNT:,} монет! (например: -5000)")
                    return

                await self._perform_steal_attempt(thief.id, victim.id, steal_amount, message)

            except Exception as e:
                self.logger.error(f"Database error in steal_with_prefix: {e}")
                await message.reply("❌ Ошибка при попытке кражи.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in steal_with_prefix: {e}")
            await message.reply("❌ Ошибка при обработке команды.")

    async def thief_stats(self, message: types.Message):
        """Показывает статистику по кражам"""
        try:
            user_id = message.from_user.id

            db = next(get_db())
            try:
                stats = ThiefRepository.get_user_thief_stats(db, user_id)

                result = f"📊 <b>Статистика кражей {message.from_user.full_name}</b>\n\n"
                result += f"✅ Успешных краж: {stats['successful_steals']}\n"
                result += f"❌ Неудачных попыток: {stats['failed_steals']}\n"
                result += f"💰 Всего украдено: {stats['total_stolen']:,} монет\n\n"

                if stats['last_steal_time']:
                    last_steal = stats['last_steal_time'].strftime("%d.%m.%Y %H:%M")
                    result += f"⏰ Последняя кража: {last_steal}\n"
                else:
                    result += "⏰ Последняя кража: никогда\n"

                # Проверяем кулдаун
                last_steal = ThiefRepository.get_last_steal_time(db, user_id)
                if last_steal:
                    time_since_last_steal = datetime.now() - last_steal
                    if time_since_last_steal.total_seconds() < self.STEAL_COOLDOWN:
                        time_left = self.STEAL_COOLDOWN - time_since_last_steal.total_seconds()
                        minutes_left = int(time_left // 60)
                        result += f"⏳ До следующей кражи: {minutes_left} минут\n"

                # Убрали проверку ареста
                result += f"\n🎯 <i>Удачи в следующих кражах!</i>"

                await message.reply(result, parse_mode="HTML")

            except Exception as e:
                self.logger.error(f"Database error in thief_stats: {e}")
                await message.reply("❌ Ошибка при получении статистики.")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Error in thief_stats: {e}")
            await message.reply("❌ Ошибка при обработке команды.")


def register_thief_handlers(dp: Dispatcher):
    """Регистрация обработчиков для команды 'красть'"""
    handler = ThiefHandler()

    # Обработчик для команд с "красть" + сумма
    dp.register_message_handler(
        handler.steal_money,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!красть") or
                msg.text.lower().startswith("/красть") or
                msg.text.lower().startswith("/steal") or
                msg.text.lower().startswith("красть")
        ),
        state="*"
    )

    # Обработчик для команд с префиксом '-' (например: "-5000")
    dp.register_message_handler(
        handler.steal_with_prefix,
        lambda msg: msg.text and msg.text.strip().startswith('-') and len(msg.text.strip()) > 1,
        state="*"
    )

    dp.register_message_handler(
        handler.thief_stats,
        lambda msg: msg.text and (
                msg.text.lower().startswith("!кражи") or
                msg.text.lower().startswith("/кражи") or
                msg.text.lower().startswith("/thief_stats") or
                msg.text.lower().startswith("кражи")
        ),
        state="*"
    )

    logger.info("✅ Обработчики 'кража' зарегистрированы (без ареста)")
