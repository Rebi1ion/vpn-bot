import asyncio
import logging
from datetime import datetime, time, timezone, timedelta
from aiogram import Bot
from database import AsyncSessionLocal
from database.operations import (
    get_user_config,
    assign_next_channel,
    get_user_unsubscribed_channels,
)
from database.models import User, VpnConfig, VpnServer
from sqlalchemy import select
from checker.subscription import SubscriptionChecker
from xui_api.manager import Xui3Manager, ServerManagerFactory
from config.settings import settings
from database.operations import get_setting

logger = logging.getLogger(__name__)

MSK_TZ = timezone(timedelta(hours=3))

# Размер батча для параллельной проверки
BATCH_SIZE = 5
# Интервал проверки истечения подписок (в часах)
EXPIRATION_CHECK_INTERVAL_HOURS = 2
# Интервал мониторинга серверов (в часах)
SERVER_MONITOR_INTERVAL_HOURS = 4
# Порог нагрузки для уведомления админа (%)
SERVER_LOAD_THRESHOLD = 85


class BackgroundScheduler:
    """Планировщик с параллельной проверкой, частым мониторингом подписок и серверов"""

    def __init__(self, bot: Bot, subscription_checker: SubscriptionChecker):
        self.bot = bot
        self.subscription_checker = subscription_checker
        self.xui_manager = Xui3Manager()
        self.is_running = False

    async def start(self):
        """Запустить планировщик"""
        if not settings.ENABLE_BACKGROUND_CHECKS:
            logger.info("⏸️ Фоновые проверки отключены")
            return

        self.is_running = True
        logger.info("🕐 Планировщик запущен")

        # 1. Ежедневная проверка каналов в 20:00 МСК
        asyncio.create_task(self._daily_check_at_20_00())
        # 2. Проверка истечения подписок каждые 2 часа
        asyncio.create_task(self._expiration_check_loop())
        # 3. Мониторинг нагрузки серверов каждые 4 часа
        asyncio.create_task(self._server_monitor_loop())
        # 4. Проверка на 3 дня до истечения каждые 12 часов
        asyncio.create_task(self._reminder_check_loop())
        # 5. Очистка старых конфигов с серверов 3x-ui (более 3 дней неактивности)
        asyncio.create_task(self._cleanup_inactive_configs_loop())
        # 6. Очистка 1-часовых триалов
        asyncio.create_task(self._trial_expiration_check_loop())

    async def stop(self):
        """Остановить планировщик"""
        self.is_running = False
        logger.info("⏹️ Планировщик остановлен")

    # ==================== ЕЖЕДНЕВНАЯ ПРОВЕРКА КАНАЛОВ ====================

    async def _daily_check_at_20_00(self):
        """Ежедневная проверка в 20:00 МСК (или каждые N минут в TEST_MODE)"""
        while self.is_running:
            try:
                if settings.TEST_MODE:
                    logger.info(
                        f"🧪 TEST MODE: Проверка каждые {settings.CHECK_INTERVAL_MINUTES} минут"
                    )
                    await asyncio.sleep(settings.CHECK_INTERVAL_MINUTES * 60)
                    await self._perform_daily_check()
                else:
                    now = datetime.now(MSK_TZ)
                    target_time = time(20, 0)
                    target_datetime = datetime.combine(
                        now.date(), target_time, tzinfo=MSK_TZ
                    )

                    if now >= target_datetime:
                        target_datetime += timedelta(days=1)

                    sleep_seconds = (target_datetime - now).total_seconds()
                    logger.info(
                        f"⏰ Следующая проверка каналов в {target_datetime.strftime('%d.%m.%Y %H:%M')} МСК"
                    )

                    await asyncio.sleep(sleep_seconds)
                    await self._perform_daily_check()

            except Exception as e:
                logger.error(f"❌ Ошибка в планировщике (каналы): {e}", exc_info=True)
                await asyncio.sleep(3600)

    async def _perform_daily_check(self):
        """Выполнить ежедневную проверку всех пользователей (ПАРАЛЛЕЛЬНО)"""
        logger.info("🔍 ========== ЕЖЕДНЕВНАЯ ПРОВЕРКА 20:00 МСК ==========")

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).join(VpnConfig, User.id == VpnConfig.user_id)
            )
            users = result.scalars().all()

            logger.info(f"👥 Найдено {len(users)} пользователей для проверки")

            # Параллельная проверка батчами
            for i in range(0, len(users), BATCH_SIZE):
                batch = users[i : i + BATCH_SIZE]
                tasks = []
                for user in batch:
                    tasks.append(self._check_user_safe(session, user))
                await asyncio.gather(*tasks)

                # Небольшая пауза между батчами чтобы не перегружать API
                if i + BATCH_SIZE < len(users):
                    await asyncio.sleep(1)

        logger.info("✅ ========== ПРОВЕРКА ЗАВЕРШЕНА ==========")

    async def _check_user_safe(self, session, user: User):
        """Обёртка для безопасной проверки пользователя"""
        try:
            await self._check_user(session, user)
        except Exception as e:
            logger.error(f"❌ Ошибка проверки пользователя {user.telegram_id}: {e}")

    async def _check_user(self, session, user: User):
        """Проверить одного пользователя (каналы + подписка)"""
        now = datetime.utcnow()
        config = await get_user_config(session, user.id)

        # 1. Проверка срока подписки
        if user.subscription_end_date and now >= user.subscription_end_date:
            logger.info(
                f"⏳ {user.telegram_id}: подписка истекла {user.subscription_end_date}"
            )
            if config and config.is_active:
                await self._disable_user_vpn_expired(session, user, config)
            return

        # 2. Проверка подписок на каналы
        unsubscribed = await get_user_unsubscribed_channels(session, user.id)

        if not unsubscribed:
            logger.info(f"✅ {user.telegram_id}: подписан на все каналы")

            next_channel = await assign_next_channel(session, user.id)

            if next_channel:
                await self._send_new_channel_notification(user, next_channel)
                logger.info(
                    f"📢 {user.telegram_id}: выдан новый канал '{next_channel.display_name}'"
                )
            else:
                logger.info(f"🎉 {user.telegram_id}: получил все каналы")

        else:
            logger.warning(
                f"⚠️ {user.telegram_id}: не подписан на {len(unsubscribed)} каналов"
            )

            if config and config.is_active:
                await self._disable_user_vpn(session, user, config, unsubscribed)

    # ==================== ПРОВЕРКА ИСТЕЧЕНИЯ ПОДПИСОК (каждые 2 часа) ====================

    async def _expiration_check_loop(self):
        """Проверка истечения подписок каждые N часов"""
        # Первый запуск через 30 минут (чтобы не совпадать с daily check)
        await asyncio.sleep(30 * 60)

        while self.is_running:
            try:
                await self._check_expired_subscriptions()

                interval = (
                    settings.CHECK_INTERVAL_MINUTES * 60
                    if settings.TEST_MODE
                    else EXPIRATION_CHECK_INTERVAL_HOURS * 3600
                )
                logger.info(
                    f"⏰ Следующая проверка истечения через {interval // 3600} ч."
                )
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"❌ Ошибка проверки истечения: {e}", exc_info=True)
                await asyncio.sleep(1800)

    async def _check_expired_subscriptions(self):
        """Быстрая проверка: найти пользователей с истёкшей подпиской и активным конфигом"""
        logger.info("🔍 Проверка истечения подписок...")

        now = datetime.utcnow()
        disabled_count = 0

        async with AsyncSessionLocal() as session:
            # Одним запросом: пользователи с истёкшей подпиской и активным конфигом
            result = await session.execute(
                select(User, VpnConfig)
                .join(VpnConfig, User.id == VpnConfig.user_id)
                .where(VpnConfig.is_active == True)
                .where(User.subscription_end_date != None)
                .where(User.subscription_end_date <= now)
            )

            expired_pairs = result.all()

            if not expired_pairs:
                logger.info("✅ Нет истёкших подписок с активным VPN")
                return

            logger.info(
                f"⏳ Найдено {len(expired_pairs)} пользователей с истёкшей подпиской"
            )

            # Параллельная обработка батчами
            for i in range(0, len(expired_pairs), BATCH_SIZE):
                batch = expired_pairs[i : i + BATCH_SIZE]
                tasks = []
                for user, config in batch:
                    tasks.append(self._disable_expired_safe(session, user, config))
                await asyncio.gather(*tasks)

                if i + BATCH_SIZE < len(expired_pairs):
                    await asyncio.sleep(0.5)

            disabled_count = len(expired_pairs)

        logger.info(f"✅ Проверка истечения завершена. Отключено: {disabled_count}")

    async def _disable_expired_safe(self, session, user: User, config: VpnConfig):
        """Безопасная обёртка для отключения истёкших подписок"""
        try:
            await self._disable_user_vpn_expired(session, user, config)
        except Exception as e:
            logger.error(f"❌ Ошибка отключения {user.telegram_id}: {e}")

    # ==================== НАПОМИНАНИЕ ОБ ОКОНЧАНИИ (за 3 дня) ====================

    async def _reminder_check_loop(self):
        """Проверка и отправка напоминаний за 3 дня до конца подписки"""
        await asyncio.sleep(60 * 60)  # Старт через час
        while self.is_running:
            try:
                await self._check_upcoming_expirations()
                interval = (
                    settings.CHECK_INTERVAL_MINUTES * 60
                    if settings.TEST_MODE
                    else 12 * 3600
                )
                logger.info(
                    f"⏰ Следующая проверка напоминаний через {interval // 3600} ч."
                )
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"❌ Ошибка отправки напоминаний: {e}", exc_info=True)
                await asyncio.sleep(3600)

    async def _check_upcoming_expirations(self):
        logger.info("🔍 Проверка пользователей для напоминания за 3 дня...")
        now = datetime.utcnow()
        limit_3_days = now + timedelta(days=3)
        reminded_count = 0

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User, VpnConfig)
                .join(VpnConfig, User.id == VpnConfig.user_id)
                .where(VpnConfig.is_active == True)
                .where(User.subscription_end_date != None)
                .where(User.subscription_end_date > now)
                .where(User.subscription_end_date <= limit_3_days)
                .where(User.is_reminded_3d == False)
            )
            upcoming_pairs = result.all()

            if not upcoming_pairs:
                return

            logger.info(
                f"⏳ Найдено {len(upcoming_pairs)} пользователей для напоминания"
            )

            for user, config in upcoming_pairs:
                try:
                    await self._send_reminder_notification(session, user)
                    user.is_reminded_3d = True
                    reminded_count += 1
                except Exception as e:
                    logger.error(f"Ошибка отправки напоминания {user.telegram_id}: {e}")

            await session.commit()

        if reminded_count > 0:
            logger.info(f"✅ Напоминания отправлены: {reminded_count}")

    # ==================== ОЧИСТКА СТАРЫХ КОНФИГОВ (>3 ДНЕЙ НЕАКТИВНОСТИ) ====================

    async def _cleanup_inactive_configs_loop(self):
        """Очистка старых конфигов с серверов 3x-ui (более 3 дней неактивности)"""
        await asyncio.sleep(60 * 90)  # Старт через 1.5 часа
        while self.is_running:
            try:
                await self._cleanup_inactive_configs()
                interval = (
                    settings.CHECK_INTERVAL_MINUTES * 60
                    if settings.TEST_MODE
                    else 24 * 3600
                )
                logger.info(
                    f"⏰ Следующая зачистка старых конфигов через {interval // 3600} ч."
                )
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"❌ Ошибка зачистки старых конфигов: {e}", exc_info=True)
                await asyncio.sleep(3600)

    async def _cleanup_inactive_configs(self):
        logger.info("🧹 Запуск очистки конфигов (неактивность > 3 дней)...")
        now = datetime.utcnow()
        limit_3_days_ago = now - timedelta(days=3)
        cleaned_count = 0

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User, VpnConfig)
                .join(VpnConfig, User.id == VpnConfig.user_id)
                .where(VpnConfig.config_url != "")
                .where(User.subscription_end_date != None)
                .where(User.subscription_end_date <= limit_3_days_ago)
            )
            old_pairs = result.all()

            if not old_pairs:
                return

            logger.info(f"🗑 Найдено {len(old_pairs)} конфигов для очистки")

            from database.models import VpnServer
            from database.server_operations import decrement_server_users
            from xui_api.manager import ServerManagerFactory

            for user, config in old_pairs:
                try:
                    if config.server_id:
                        server_result = await session.execute(
                            select(VpnServer).where(VpnServer.id == config.server_id)
                        )
                        server = server_result.scalar_one_or_none()
                        if server:
                            server_manager = ServerManagerFactory.create_manager(
                                server.host,
                                server.username,
                                server.password,
                                server.inbound_id,
                            )
                            # Удаляем из панели 3x-ui
                            success = await server_manager.delete_config(config.email)
                            if success:
                                await decrement_server_users(session, server.id)

                    # В любом случае обнуляем в БД
                    config.server_id = None
                    config.config_url = ""
                    config.is_active = False

                    # Отправляем уведомление
                    try:
                        await self.bot.send_message(
                            chat_id=user.telegram_id,
                            text=f"🗑 <b>Твой VPN удален с сервера из-за неактивности</b>\n\n"
                            f"Не переживай, профиль сохранен в нашей системе!\n"
                            f"Оплати подписку, чтобы мы выдали тебе новый конфиг.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass

                    cleaned_count += 1
                except Exception as e:
                    logger.error(f"Ошибка очистки конфига {user.telegram_id}: {e}")

            await session.commit()

        if cleaned_count > 0:
            logger.info(f"✅ Очищено старых конфигов: {cleaned_count}")

    # ==================== МОНИТОРИНГ СЕРВЕРОВ (каждые 4 часа) ====================

    async def _server_monitor_loop(self):
        """Мониторинг нагрузки серверов"""
        # Первый запуск через 5 минут
        await asyncio.sleep(5 * 60)

        while self.is_running:
            try:
                await self._monitor_servers()

                interval = (
                    settings.CHECK_INTERVAL_MINUTES * 60
                    if settings.TEST_MODE
                    else SERVER_MONITOR_INTERVAL_HOURS * 3600
                )
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"❌ Ошибка мониторинга серверов: {e}", exc_info=True)
                await asyncio.sleep(3600)

    async def _monitor_servers(self):
        """Собрать статистику серверов и уведомить при высокой нагрузке"""
        logger.info("📊 ========== МОНИТОРИНГ СЕРВЕРОВ ==========")

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(VpnServer).where(VpnServer.is_active == True)
            )
            servers = result.scalars().all()

            if not servers:
                logger.warning("⚠️ Нет активных серверов для мониторинга")
                return

            alerts = []

            for server in servers:
                # Синхронизируем реальное количество пользователей
                from database.server_operations import sync_server_count

                await sync_server_count(session, server.id)
                await session.refresh(server)

                # Процент загрузки
                load_percent = (
                    (server.current_users / server.max_users * 100)
                    if server.max_users > 0
                    else 0
                )

                status_emoji = (
                    "🟢"
                    if load_percent < 70
                    else "🟡" if load_percent < SERVER_LOAD_THRESHOLD else "🔴"
                )

                logger.info(
                    f"{status_emoji} {server.name}: "
                    f"{server.current_users}/{server.max_users} ({load_percent:.0f}%) | "
                    f"IP: {server.ip}"
                )

                # Проверяем доступность сервера
                try:
                    manager = ServerManagerFactory.create_manager(
                        server.host, server.username, server.password, server.inbound_id
                    )
                    is_online = await manager.authenticate()

                    if not is_online:
                        alerts.append(
                            f"🔴 {server.name} — НЕ ДОСТУПЕН (ошибка авторизации)"
                        )
                        logger.error(f"🔴 Сервер {server.name} недоступен!")
                    else:
                        logger.info(f"  ↳ Подключение к 3x-ui: ✅")
                except Exception as e:
                    alerts.append(f"🔴 {server.name} — ОШИБКА: {str(e)[:50]}")
                    logger.error(f"🔴 Ошибка подключения к {server.name}: {e}")

                # Предупреждение о высокой нагрузке
                if load_percent >= SERVER_LOAD_THRESHOLD:
                    alerts.append(
                        f"⚠️ {server.name}: {server.current_users}/{server.max_users} ({load_percent:.0f}%)"
                    )

            # Уведомляем администратора если есть проблемы
            if alerts:
                await self._send_admin_alert(alerts)

        logger.info("📊 ========== МОНИТОРИНГ ЗАВЕРШЁН ==========")

    async def _send_admin_alert(self, alerts: list):
        """Отправить уведомление администратору о проблемах серверов"""
        alerts_text = "\n".join(alerts)

        try:
            await self.bot.send_message(
                chat_id=settings.ADMIN_USER_ID,
                text=(
                    f"🚨 <b>Мониторинг серверов</b>\n\n"
                    f"{alerts_text}\n\n"
                    f"<i>{datetime.now(MSK_TZ).strftime('%d.%m.%Y %H:%M')} МСК</i>"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Ошибка отправки алерта админу: {e}")

    # ==================== ОТКЛЮЧЕНИЕ VPN ====================

    async def _disable_user_vpn_expired(self, session, user: User, config: VpnConfig):
        """Отключить VPN пользователя по истечению срока подписки"""
        from database.server_operations import decrement_server_users

        # Получаем правильный сервер
        if config.server_id:
            result = await session.execute(
                select(VpnServer).where(VpnServer.id == config.server_id)
            )
            server = result.scalar_one_or_none()

            if server:
                server_manager = ServerManagerFactory.create_manager(
                    host=server.host,
                    username=server.username,
                    password=server.password,
                    inbound_id=server.inbound_id,
                )
            else:
                logger.error(
                    f"Сервер {config.server_id} не найден для {user.telegram_id}"
                )
                return
        else:
            server_manager = self.xui_manager

        success = await server_manager.disable_config(config.email)

        if success:
            config.is_active = False
            if config.server_id:
                await decrement_server_users(session, config.server_id)
            await session.commit()
            logger.info(f"🔴 VPN отключён (истекла подписка) для {user.telegram_id}")

            await self._send_payment_notification(user)
        else:
            logger.error(f"❌ Не удалось отключить VPN для {user.telegram_id}")

    async def _disable_user_vpn(
        self, session, user: User, config: VpnConfig, unsubscribed_channels: list
    ):
        """Отключить VPN пользователя за неподписку на каналы"""

        if config.server_id:
            result = await session.execute(
                select(VpnServer).where(VpnServer.id == config.server_id)
            )
            server = result.scalar_one_or_none()

            if server:
                server_manager = ServerManagerFactory.create_manager(
                    host=server.host,
                    username=server.username,
                    password=server.password,
                    inbound_id=server.inbound_id,
                )
            else:
                logger.error(
                    f"Сервер {config.server_id} не найден для {user.telegram_id}"
                )
                return
        else:
            server_manager = self.xui_manager

        success = await server_manager.disable_config(config.email)

        if success:
            config.is_active = False
            await session.commit()
            logger.info(f"🔴 VPN отключён для {user.telegram_id}")

            await self._send_vpn_disabled_notification(user, unsubscribed_channels)
        else:
            logger.error(f"❌ Не удалось отключить VPN для {user.telegram_id}")

    # ==================== УВЕДОМЛЕНИЯ ====================

    async def _send_new_channel_notification(self, user: User, channel):
        """Уведомление о новом канале"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"📢 {channel.display_name}", url=channel.channel_url
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✅ Проверить подписку", callback_data="check_subscription"
                    )
                ],
            ]
        )

        try:
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"⚠️ <b>VPN отключён!</b>\n\n"
                    f"Ты не подписан на обязательные каналы\n"
                    f"🔄 Подпишись и нажми 'Проверить подписку', чтобы восстановить доступ."
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления {user.telegram_id}: {e}")

    async def _send_vpn_disabled_notification(
        self, user: User, unsubscribed_channels: list
    ):
        """Уведомление об отключении VPN"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        buttons = []
        for channel in unsubscribed_channels:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"📢 {channel.display_name}", url=channel.channel_url
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Проверить подписку", callback_data="check_subscription"
                )
            ]
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        try:
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"⚠️ <b>VPN отключён!</b>\n\n"
                    f"Ты не подписан на обязательные каналы\n"
                    f"🔄 Подпишись и нажми 'Проверить подписку', чтобы восстановить доступ."
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления {user.telegram_id}: {e}")

    async def _send_payment_notification(self, user: User):
        """Уведомление об истечении подписки и предложение оплаты"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        async with AsyncSessionLocal() as session:
            price_1_month = await get_setting(session, "price_1_month_rub", 150)
            price_6_months = await get_setting(session, "price_6_months_rub", 700)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"⭐ Оплатить 1 месяц ({price_1_month} руб)",
                        callback_data="buy_1_month",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"⭐ Оплатить 6 месяцев ({price_6_months} руб)",
                        callback_data="buy_6_months",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🎁 Пригласить друга (+3 дня)",
                        callback_data="referral_link",
                    )
                ],
            ]
        )

        try:
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"⚠️ <b>Срок действия вашей подписки VPN истек!</b>\n\n"
                    f"Ваш доступ приостановлен.\n"
                    f"Для продолжения использования VPN выберите и оплатите тариф:\n\n"
                    f"🔹 1 месяц - {price_1_month} рублей\n"
                    f"🔹 6 месяцев - {price_6_months} рублей\n\n"
                    f"<i>Или пригласите друга и получите 3 дня бесплатно!</i>"
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(
                f"Ошибка отправки уведомления об оплате {user.telegram_id}: {e}"
            )

    async def _send_reminder_notification(self, session, user: User):
        """Уведомление за 3 дня до конца подписки"""
        from telegram_bot.keyboards import get_payment_keyboard

        price_1_month = await get_setting(session, "price_1_month_rub", 150)
        price_6_months = await get_setting(session, "price_6_months_rub", 700)

        keyboard = get_payment_keyboard(price_1_month, price_6_months)

        sub_end = user.subscription_end_date.strftime("%d.%m.%Y %H:%M UTC")
        text = (
            f"⏳ <b>До окончания вашей VPN подписки осталось менее 3-х дней!</b>\n\n"
            f"Дата отключения: <b>{sub_end}</b>\n\n"
            f"Продлите подписку сейчас, чтобы оставаться на связи без перебоев 👇"
        )

        await self.bot.send_message(
            chat_id=user.telegram_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    # ==================== ОЧИСТКА ВЕБ ТРИАЛОВ ====================

    async def _trial_expiration_check_loop(self):
        """Проверка истекших 1-часовых триалов каждые 5 минут"""
        from database.models import TrialUser, VpnServer
        from xui_api.manager import ServerManagerFactory
        from database.server_operations import decrement_server_users

        while self.is_running:
            try:
                now = datetime.utcnow()
                async with AsyncSessionLocal() as session:
                    # Ищем всех, у кого expires_at < now и кто еще активен
                    result = await session.execute(
                        select(TrialUser)
                        .where(TrialUser.expires_at < now)
                        .where(TrialUser.is_active == True)
                    )
                    expired_trials = result.scalars().all()

                    for trial in expired_trials:
                        logger.info(
                            f"⏳ Очистка истекшего веб-триала для IP: {trial.ip_address} (Email: {trial.email})"
                        )

                        servers_result = await session.execute(
                            select(VpnServer).where(VpnServer.is_active == True)
                        )
                        servers = servers_result.scalars().all()
                        deleted = False

                        for server in servers:
                            manager = ServerManagerFactory.create_manager(
                                server.host,
                                server.username,
                                server.password,
                                server.inbound_id,
                            )
                            # Пытаемся удалить. Если True - успех
                            success = await manager.delete_config(trial.email)
                            if success:
                                await decrement_server_users(session, server.id)
                                deleted = True
                                break

                        if not deleted:
                            logger.warning(
                                f"⚠️ Не удалось удалить веб-триал {trial.email} ни с одного сервера. Возможно он уже удален."
                            )

                        # Деактивируем локально, чтобы больше не проверять, но сохраняем для анти-абуза
                        trial.is_active = False

                    if len(expired_trials) > 0:
                        await session.commit()
                        logger.info(f"✅ Очищено веб-триалов: {len(expired_trials)}")

            except Exception as e:
                logger.error(
                    f"❌ Ошибка в _trial_expiration_check_loop: {e}", exc_info=True
                )

            # Проверять каждые 5 минут
            await asyncio.sleep(5 * 60)
