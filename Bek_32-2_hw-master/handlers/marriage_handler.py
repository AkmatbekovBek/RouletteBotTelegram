# handlers/marriage_handler.py
import random
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any
from aiogram import types, Dispatcher
from database import get_db


class MarriageHandler:
    """Professional Marriage System with Enhanced UX"""

    def __init__(self):
        self.marriage_messages = {
            "proposal_received": [
                "💍 <b>Приглашение в вечность</b>\n\n{proposer} приглашает {target} разделить жизненный путь!\n\n✨ Судьба стучится в ваше сердце...",
                "🌹 <b>Предложение сердца</b>\n\n{proposer} предлагает {target} создать союз душ!\n\n💫 Ваш момент истины настал...",
                "💞 <b>Призыв судьбы</b>\n\n{proposer} желает пройти с {target} жизненный путь!\n\n🌟 Время сделать выбор...",
            ],
            "marriage_created": [
                "💒 <b>Союз скреплен!</b>\n\n{partner1} 💕 {partner2}\n🌟 Две души объединились в вечном танце!\n📅 {date}",
                "🌈 <b>Новая глава начинается!</b>\n\n{partner1} ✨ {partner2}\n💫 Судьба соединила сердца!\n🗓️ {date}",
                "🌠 <b>Вечность начинается сегодня!</b>\n\n{partner1} ❤️ {partner2}\n✨ Две звезды сошлись в небесах!\n📆 {date}",
            ],
            "divorce_completed": [
                "🌀 <b>Глава закрыта</b>\n\n{partner1} и {partner2} решили пойти разными путями.\n🕊️ Пусть каждый найдет свой новый свет...",
                "🌅 <b>Дороги разошлись</b>\n\n{partner1} и {partner2} завершили совместный путь.\n✨ Иногда расставание - начало новой истории...",
            ],
            "divorce_group_notification": [
                "💔 <b>Пара распалась</b>\n\n{partner1} и {partner2} официально расторгли свой брак.\n🕊️ Иногда пути расходятся, но жизнь продолжается...",
                "🌀 <b>Союз прекращен</b>\n\n{partner1} и {partner2} больше не вместе.\n✨ Пожелаем им найти новые пути к счастью!",
            ],
            "proposal_declined": [
                "💔 {respondent} отклонил(а) предложение руки и сердца от {proposer}\n🌟 Возможно, судьба приготовила другую встречу...",
                "🌀 {respondent} ответил(а) отказом на предложение {proposer}\n✨ Каждому предначертан свой путь...",
            ],
            "already_married": [
                "💍 <b>Вы уже в браке!</b>\n\nВы уже состоите в брачном союзе с {partner}.\n\n💔 Если хотите создать новый союз, сначала расторгните текущий брак командой:\n<code>/развод</code>",
                "💞 <b>Брачный статус: занят</b>\n\nВаше сердце уже принадлежит {partner}.\n\n🌀 Для нового предложения необходимо:\n<code>/развод</code> → затем новое предложение",
            ]
        }

        # Хранилище для отслеживания исходных чатов развода
        self.divorce_requests = {}

    def _get_random_message(self, category: str, **kwargs) -> str:
        """Get random message from category with formatting"""
        template = random.choice(self.marriage_messages[category])
        return template.format(**kwargs)

    def _get_time_difference(self, start_time: datetime) -> str:
        """Calculate human-readable time difference in days only"""
        try:
            now = datetime.now(timezone.utc)

            if start_time.tzinfo is not None:
                start_time_utc = start_time.astimezone(timezone.utc)
            else:
                start_time_utc = start_time.replace(tzinfo=timezone.utc)

            delta = now - start_time_utc
            days = delta.days

            if days < 0:
                return "сегодня"

            if days == 0:
                return "сегодня"
            elif days == 1:
                return "1 день"
            elif 2 <= days <= 4:
                return f"{days} дня"
            else:
                return f"{days} дней"

        except Exception as e:
            print(f"Time calculation error: {e}")
            return "неизвестно"

    def _create_user_link(self, user_id: int, first_name: str) -> str:
        """Create safe user profile link"""
        safe_name = first_name.replace('<', '&lt;').replace('>', '&gt;')
        return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

    def _get_marriage_data(self, user_id: int) -> Optional[Tuple]:
        """Get marriage data with error handling"""
        db = next(get_db())
        try:
            from sqlalchemy import text
            result = db.execute(
                text("""
                     SELECT id, user1, user2, married_at
                     FROM marriages
                     WHERE user1 = :user_id
                        OR user2 = :user_id
                     """),
                {"user_id": user_id}
            ).fetchone()
            return result
        except Exception as e:
            print(f"Database error: {e}")
            return None
        finally:
            db.close()

    def _is_user_married(self, user_id: int) -> bool:
        """Check if user is married"""
        return self._get_marriage_data(user_id) is not None

    def _get_partner_info(self, user_id: int) -> Tuple[Optional[int], Optional[datetime], Optional[int]]:
        """Get partner information"""
        marriage = self._get_marriage_data(user_id)
        if not marriage:
            return None, None, None
        marriage_id, u1, u2, married_at = marriage
        partner_id = u2 if u1 == user_id else u1
        return partner_id, married_at, marriage_id

    async def _get_user_display_info(self, bot, user_id: int, default_name: str = "Пользователь") -> Tuple[str, str]:
        """Get user info for display with fallbacks"""
        try:
            user_chat = await bot.get_chat(user_id)
            display_name = user_chat.first_name or user_chat.username or default_name
            user_link = self._create_user_link(user_id, display_name)
            return user_link, display_name
        except Exception:
            return default_name, default_name

    async def _validate_marriage_proposal(self, message: types.Message, target_id: int) -> Optional[str]:
        """Validate marriage proposal conditions"""
        proposer_id = message.from_user.id

        if self._is_user_married(proposer_id):
            partner_id, _, _ = self._get_partner_info(proposer_id)
            partner_link, _ = await self._get_user_display_info(message.bot, partner_id)

            already_married_msg = self._get_random_message(
                "already_married",
                partner=partner_link
            )
            return already_married_msg

        if proposer_id == target_id:
            return "🌀 Нельзя предложить брак самому себе."

        if self._is_user_married(target_id):
            return "💫 Этот пользователь уже нашел свою половинку."

        return None

    async def _store_divorce_request_context(self, requester_id: int, partner_id: int, chat_id: int, message_id: int):
        """Store divorce request context for group notifications"""
        key = f"{requester_id}_{partner_id}"
        self.divorce_requests[key] = {
            'chat_id': chat_id,
            'message_id': message_id,
            'timestamp': datetime.now()
        }

    async def _get_divorce_request_context(self, requester_id: int, partner_id: int):
        """Get stored divorce request context"""
        key = f"{requester_id}_{partner_id}"
        return self.divorce_requests.get(key)

    async def _cleanup_divorce_request_context(self, requester_id: int, partner_id: int):
        """Clean up stored divorce request context"""
        key = f"{requester_id}_{partner_id}"
        self.divorce_requests.pop(key, None)

    async def _send_group_divorce_notification(self, bot, chat_id: int, requester_link: str, partner_link: str):
        """Send divorce notification to original group chat"""
        try:
            notification_text = self._get_random_message(
                "divorce_group_notification",
                partner1=requester_link,
                partner2=partner_link
            )

            await bot.send_message(
                chat_id,
                notification_text,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Group notification error: {e}")

    async def propose_marriage(self, message: types.Message):
        """💍 Handle marriage proposal with enhanced UX"""

        # Check if user is already married (direct command)
        if self._is_user_married(message.from_user.id):
            partner_id, _, _ = self._get_partner_info(message.from_user.id)
            partner_link, _ = await self._get_user_display_info(message.bot, partner_id)

            already_married_msg = self._get_random_message(
                "already_married",
                partner=partner_link
            )
            await message.reply(already_married_msg, parse_mode="HTML")
            return

        if not message.reply_to_message:
            guidance = (
                "💌 <b>Как сделать предложение:</b>\n\n"
                "1. Найдите сообщение пользователя\n"
                "2. Ответьте на него командой\n"
                "3. Напишите <code>брак</code>\n\n"
                "✨ И пусть судьба улыбнется вам!"
            )
            await message.reply(guidance, parse_mode="HTML")
            return

        proposer = message.from_user
        target = message.reply_to_message.from_user

        # Validation
        validation_error = await self._validate_marriage_proposal(message, target.id)
        if validation_error:
            await message.reply(validation_error, parse_mode="HTML")
            return

        # Create proposal
        db = next(get_db())
        try:
            from sqlalchemy import text

            # Final conflict check
            existing = db.execute(
                text("SELECT id FROM marriages WHERE user1 IN (:u1, :u2) OR user2 IN (:u1, :u2)"),
                {"u1": proposer.id, "u2": target.id}
            ).fetchone()

            if existing:
                await message.reply("⚡ Обнаружен конфликт статусов.", parse_mode="HTML")
                return

            # Prepare user info with clickable names
            proposer_link, _ = await self._get_user_display_info(message.bot, proposer.id)
            target_link, _ = await self._get_user_display_info(message.bot, target.id)

            # Create proposal interface
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton(
                    "💖 Принять судьбу",
                    callback_data=f"marriage_accept_{proposer.id}_{target.id}"
                ),
                types.InlineKeyboardButton(
                    "💔 Отказаться",
                    callback_data=f"marriage_decline_{proposer.id}_{target.id}"
                )
            )

            # Use proposal message with both clickable names
            proposal_text = self._get_random_message(
                "proposal_received",
                proposer=proposer_link,
                target=target_link
            )

            # Send proposal silently (no confirmation to proposer)
            await message.reply_to_message.reply(
                proposal_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        except Exception as e:
            print(f"Proposal error: {e}")
            await message.reply("🌪️ Произошла непредвиденная ошибка.", parse_mode="HTML")
        finally:
            db.close()

    async def handle_marriage_response(self, callback: types.CallbackQuery):
        """🤵👰 Process marriage responses"""

        try:
            data_parts = callback.data.split("_")
            if len(data_parts) != 4:
                await callback.answer("Неверные данные", show_alert=True)
                return

            action_type = data_parts[1]
            proposer_id = int(data_parts[2])
            target_id = int(data_parts[3])
            respondent = callback.from_user

            if respondent.id != target_id:
                await callback.answer("Это предложение не для вас", show_alert=True)
                return

            db = next(get_db())
            try:
                from sqlalchemy import text

                # Get user info with clickable names
                proposer_link, _ = await self._get_user_display_info(callback.bot, proposer_id)
                respondent_link, _ = await self._get_user_display_info(callback.bot, respondent.id)

                if action_type == "accept":
                    # Final validation
                    conflict = db.execute(
                        text("SELECT id FROM marriages WHERE user1 IN (:u1, :u2) OR user2 IN (:u1, :u2)"),
                        {"u1": proposer_id, "u2": target_id}
                    ).fetchone()

                    if conflict:
                        await callback.answer("Конфликт статусов", show_alert=True)
                        await callback.message.edit_text(
                            "⚡ Предложение устарело",
                            reply_markup=None,
                            parse_mode="HTML"
                        )
                        return

                    # Create marriage
                    marriage_time = datetime.now()
                    db.execute(
                        text("INSERT INTO marriages (user1, user2, married_at) VALUES (:u1, :u2, :at)"),
                        {"u1": proposer_id, "u2": target_id, "at": marriage_time}
                    )
                    db.commit()

                    # Update message in original chat with both clickable names
                    marriage_text = self._get_random_message(
                        "marriage_created",
                        partner1=proposer_link,
                        partner2=respondent_link,
                        date=marriage_time.strftime('%d.%m.%Y в %H:%M')
                    )

                    await callback.message.edit_text(
                        marriage_text,
                        reply_markup=None,
                        parse_mode="HTML"
                    )

                    # Notify both users in private
                    try:
                        await callback.bot.send_message(
                            proposer_id,
                            f"💞 {respondent_link} принял(а) ваше предложение!\n✨ Теперь вы в браке!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                    await callback.answer("💍 Брак заключен!", show_alert=True)

                else:  # Decline
                    # Use decline message with both clickable names
                    decline_text = self._get_random_message(
                        "proposal_declined",
                        respondent=respondent_link,
                        proposer=proposer_link
                    )

                    await callback.message.edit_text(
                        decline_text,
                        reply_markup=None,
                        parse_mode="HTML"
                    )

                    try:
                        await callback.bot.send_message(
                            proposer_id,
                            f"💔 {respondent_link} отклонил(а) ваше предложение\n✨ Не отчаивайтесь - ваша половинка ждет вас!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                    await callback.answer("❌ Предложение отклонено", show_alert=True)

            except Exception as e:
                print(f"Response error: {e}")
                await callback.answer("Ошибка системы", show_alert=True)
            finally:
                db.close()

        except Exception as e:
            print(f"Callback error: {e}")
            await callback.answer("Критическая ошибка", show_alert=True)

    async def list_marriages(self, message: types.Message):
        """📊 Display marriages with enhanced design"""

        db = next(get_db())
        try:
            from sqlalchemy import text

            marriages = db.execute(
                text("SELECT user1, user2, married_at FROM marriages ORDER BY married_at DESC")
            ).fetchall()

            if not marriages:
                await message.reply(
                    "💫 <b>Пока тихо и пусто...</b>\nСтаньте первой парой, заключившей союз!",
                    parse_mode="HTML"
                )
                return

            total = len(marriages)
            display_text = f"💞 <b>Счастливые пары</b>\n📊 Всего союзов: {total}\n\n"

            for idx, (u1, u2, date) in enumerate(marriages, 1):
                u1_link, _ = await self._get_user_display_info(message.bot, u1)
                u2_link, _ = await self._get_user_display_info(message.bot, u2)
                duration = self._get_time_difference(date)

                icons = ["💕", "✨", "❤️", "🌟", "💞"]
                icon = random.choice(icons)

                display_text += (
                    f"{idx}. {u1_link} {icon} {u2_link}\n"
                    f"   ⏳ {duration} вместе\n"
                    f"   📅 {date.strftime('%d.%m.%Y')}\n\n"
                )

            display_text += f"✨ Всего счастливых историй: {total}"

            await message.reply(display_text, parse_mode="HTML")

        except Exception as e:
            print(f"List error: {e}")
            await message.reply("🌪️ Ошибка загрузки данных", parse_mode="HTML")
        finally:
            db.close()

    async def my_marriage(self, message: types.Message):
        """👰🤵 Display user's marriage info"""

        user_id = message.from_user.id
        marriage = self._get_marriage_data(user_id)

        if not marriage:
            await message.reply(
                "💫 <b>Вы свободны как ветер</b>\nНайдите свою половинку и создайте союз!",
                parse_mode="HTML"
            )
            return

        _, u1, u2, marriage_time = marriage
        partner_id = u2 if u1 == user_id else u1

        user_link, _ = await self._get_user_display_info(message.bot, user_id)
        partner_link, _ = await self._get_user_display_info(message.bot, partner_id)
        duration = self._get_time_difference(marriage_time)

        status_messages = [
            f"💞 <b>Ваш союз</b>\n\n{user_link} 💕 {partner_link}\n⏳ Вместе: {duration}\n📅 С: {marriage_time.strftime('%d.%m.%Y')}\n\n✨ Цените каждый момент!",
            f"🌟 <b>Ваша история</b>\n\n{user_link} ❤️ {partner_link}\n🕰️ Союз длится: {duration}\n🗓️ Начало: {marriage_time.strftime('%d.%m.%Y')}\n\n💫 Пусть любовь только крепнет!",
            f"💒 <b>Ваш брак</b>\n\n{user_link} ✨ {partner_link}\n⏱️ В браке: {duration}\n📆 С: {marriage_time.strftime('%d.%m.%Y')}\n\n🌈 Берегите ваш союз!"
        ]

        await message.reply(random.choice(status_messages), parse_mode="HTML")

    async def request_divorce(self, message: types.Message):
        """💔 Handle divorce with enhanced flow"""

        user_id = message.from_user.id

        if not self._is_user_married(user_id):
            await message.reply(
                "💫 <b>Нечего расторгать</b>\nВы не состоите в браке.",
                parse_mode="HTML"
            )
            return

        partner_id, marriage_time, _ = self._get_partner_info(user_id)

        db = next(get_db())
        try:
            from sqlalchemy import text

            # Check existing requests
            existing = db.execute(
                text("SELECT id FROM divorce_requests WHERE requester = :uid OR partner = :uid"),
                {"uid": user_id}
            ).fetchone()

            if existing:
                await message.reply(
                    "⏳ <b>Запрос уже отправлен</b>\nОжидайте ответа второй стороны.",
                    parse_mode="HTML"
                )
                return

            user_link, _ = await self._get_user_display_info(message.bot, user_id)
            partner_link, _ = await self._get_user_display_info(message.bot, partner_id)

            # Create divorce request
            db.execute(
                text("INSERT INTO divorce_requests (requester, partner, requested_at) VALUES (:r, :p, :at)"),
                {"r": user_id, "p": partner_id, "at": datetime.now()}
            )
            db.commit()

            # Store divorce request context for group notifications
            await self._store_divorce_request_context(
                user_id,
                partner_id,
                message.chat.id,
                message.message_id
            )

            # Create divorce interface
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton(
                    "💔 Подтвердить развод",
                    callback_data=f"divorce_yes_{user_id}_{partner_id}"
                ),
                types.InlineKeyboardButton(
                    "💖 Сохранить брак",
                    callback_data=f"divorce_no_{user_id}_{partner_id}"
                )
            )

            divorce_messages = [
                f"💔 <b>Запрос на развод</b>\n\n{user_link} хочет расторгнуть брак с {partner_link}.\n⏳ Вместе: {self._get_time_difference(marriage_time)}\n\n⚠️ Внимательно обдумайте решение...",
                f"🌀 <b>Кризис в отношениях</b>\n\n{user_link} подал(а) на развод с {partner_link}.\n🕰️ Длительность союза: {self._get_time_difference(marriage_time)}\n\n💫 Возможно, это повод для диалога...",
                f"🌅 <b>Переломный момент</b>\n\n{user_link} желает завершить брак с {partner_link}.\n⏱️ В браке: {self._get_time_difference(marriage_time)}\n\n✨ Примите мудрое решение..."
            ]

            # Send to partner
            try:
                await message.bot.send_message(
                    partner_id,
                    random.choice(divorce_messages),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

                # Notify requester
                await message.reply(
                    "💌 <b>Запрос отправлен</b>\nОжидайте решения второй стороны...",
                    parse_mode="HTML"
                )

            except Exception:
                await message.reply(
                    "❌ Не удалось уведомить партнера",
                    parse_mode="HTML"
                )
                # Cleanup
                db.execute(
                    text("DELETE FROM divorce_requests WHERE requester = :r AND partner = :p"),
                    {"r": user_id, "p": partner_id}
                )
                db.commit()
                await self._cleanup_divorce_request_context(user_id, partner_id)

        except Exception as e:
            print(f"Divorce request error: {e}")
            await message.reply("🌪️ Ошибка системы", parse_mode="HTML")
        finally:
            db.close()

    async def handle_divorce_response(self, callback: types.CallbackQuery):
        """⚖️ Process divorce responses with group notifications"""

        try:
            data_parts = callback.data.split("_")
            if len(data_parts) != 4:
                await callback.answer("Неверные данные", show_alert=True)
                return

            response_type = data_parts[1]
            requester_id = int(data_parts[2])
            partner_id = int(data_parts[3])
            respondent = callback.from_user

            if respondent.id != partner_id:
                await callback.answer("Это не ваш запрос", show_alert=True)
                return

            db = next(get_db())
            try:
                from sqlalchemy import text

                # Validate request
                divorce_req = db.execute(
                    text("SELECT id FROM divorce_requests WHERE requester = :r AND partner = :p"),
                    {"r": requester_id, "p": partner_id}
                ).fetchone()

                if not divorce_req:
                    await callback.answer("Запрос устарел", show_alert=True)
                    return

                requester_link, _ = await self._get_user_display_info(callback.bot, requester_id)
                respondent_link, _ = await self._get_user_display_info(callback.bot, respondent.id)

                if response_type == "yes":
                    # Process divorce
                    db.execute(
                        text("DELETE FROM marriages WHERE (user1 = :u1 AND user2 = :u2) OR (user1 = :u2 AND user2 = :u1)"),
                        {"u1": requester_id, "u2": partner_id}
                    )
                    db.execute(
                        text("DELETE FROM divorce_requests WHERE id = :id"),
                        {"id": divorce_req[0]}
                    )
                    db.commit()

                    # Get stored group chat context
                    group_context = await self._get_divorce_request_context(requester_id, partner_id)

                    # Send notification to original group chat if available
                    if group_context:
                        await self._send_group_divorce_notification(
                            callback.bot,
                            group_context['chat_id'],
                            requester_link,
                            respondent_link
                        )

                    # Update callback message
                    divorce_text = self._get_random_message(
                        "divorce_completed",
                        partner1=requester_link,
                        partner2=respondent_link
                    )

                    await callback.message.edit_text(
                        divorce_text,
                        reply_markup=None,
                        parse_mode="HTML"
                    )

                    # Notify both users
                    try:
                        await callback.bot.send_message(
                            requester_id,
                            f"💔 {respondent_link} подтвердил(а) развод\n🕊️ Брак расторгнут.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                    # Cleanup stored context
                    await self._cleanup_divorce_request_context(requester_id, partner_id)

                    await callback.answer("💔 Брак расторгнут", show_alert=True)

                else:  # Decline divorce
                    db.execute(
                        text("DELETE FROM divorce_requests WHERE id = :id"),
                        {"id": divorce_req[0]}
                    )
                    db.commit()

                    # Cleanup stored context
                    await self._cleanup_divorce_request_context(requester_id, partner_id)

                    await callback.message.edit_text(
                        "💖 <b>Брак сохранен</b>\nВы сохранили ваш союз!",
                        reply_markup=None,
                        parse_mode="HTML"
                    )

                    try:
                        await callback.bot.send_message(
                            requester_id,
                            f"💞 {respondent_link} сохранил(а) ваш брак!\n✨ Дайте отношениям второй шанс!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                    await callback.answer("💖 Брак сохранен", show_alert=True)

            except Exception as e:
                print(f"Divorce processing error: {e}")
                await callback.answer("Ошибка системы", show_alert=True)
            finally:
                db.close()

        except Exception as e:
            print(f"Divorce callback error: {e}")
            await callback.answer("Критическая ошибка", show_alert=True)


def register_marriage_handlers(dp: Dispatcher):
    """🚀 Register marriage system handlers"""

    handler = MarriageHandler()

    # Command handlers with exact matching
    dp.register_message_handler(
        handler.propose_marriage,
        lambda msg: msg.text and msg.text.lower().strip() in ["брак", "!брак", "/брак"]
    )

    dp.register_message_handler(
        handler.list_marriages,
        lambda msg: msg.text and msg.text.lower().strip() in ["браки", "!браки", "/браки"]
    )

    dp.register_message_handler(
        handler.my_marriage,
        lambda msg: msg.text and msg.text.lower().strip() in ["мой брак", "!мой брак", "/мой брак"]
    )

    dp.register_message_handler(
        handler.request_divorce,
        lambda msg: msg.text and msg.text.lower().strip() in ["развод", "!развод", "/развод"]
    )

    # Callback handlers
    dp.register_callback_query_handler(
        handler.handle_marriage_response,
        lambda c: c.data and c.data.startswith(("marriage_accept_", "marriage_decline_"))
    )

    dp.register_callback_query_handler(
        handler.handle_divorce_response,
        lambda c: c.data and c.data.startswith(("divorce_yes_", "divorce_no_"))
    )

    print("💍 Marriage System: Clean Edition Activated")