from datetime import datetime
import os
from aiogram import Router, types, F
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters.command import Command, CommandObject
from telegram_bot.keyboards import (
    get_main_keyboard,
    get_admin_keyboard,
    get_channels_keyboard,
)
from xui_api.manager import Xui3Manager
from database import AsyncSessionLocal
from database.operations import (
    get_or_create_user,
    get_user_config,
    create_vpn_config,
    get_channels_batch,
    assign_channels_to_user,
    get_user_subscriptions,
    get_setting,
)
from database.models import Channel
from checker.subscription import SubscriptionChecker
from config.settings import settings
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)
router = Router()
xui_manager = Xui3Manager()

# subscription_checker будет инициализирован в main.py
subscription_checker = None


async def send_instruction_to_user(message: types.Message):
    """Отправить полную инструкцию с фото пользователю"""
    instruction_text = (
        "📖 <b>Инструкция по настройке VPN</b>\n\n"
        "<b>Шаг 1. Скачай приложение Hiddify</b>\n"
        "📱 <a href='https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532'>App Store (iOS)</a>\n"
        "📱 <a href='https://play.google.com/store/apps/details?id=app.hiddify.com'>Google Play (Android)</a>\n"
        "💻 <a href='https://github.com/hiddify/hiddify-next/releases'>GitHub (Windows/Mac/Linux)</a>\n\n"
        "Или любой другой клиент, поддерживающий протокол VLESS.\n\n"
        "<b>Шаг 2. Добавь конфиг</b>\n"
        "- Скопируй конфиг из бота (кнопка «Мой конфиг»)\n"
        "- Открой приложение Hiddify\n"
        "- Нажми кнопку <b>«+»</b> (плюс)\n"
        "- Выбери <b>«Добавить из буфера обмена»</b>\n\n"
        "<b>Шаг 3. Настрой приложение (для Hiddify)</b>\n"
        "- Рядом с кнопкой «+» нажми на <b>⚙️ Настройки</b>\n"
        "- Выбери режим: <b>VPN</b>\n"
        "- В дополнительных настройках укажи регион: <b>Другой</b>\n\n"
        "<b>Шаг 4. Готово!</b>\n"
        "- Нажми кнопку подключения\n"
        "- Разреши создание VPN профиля (при первом запуске)\n"
        "- Пользуйся интернетом без ограничений! 🚀\n\n"
        "⚠️ <b>ВАЖНО:</b>\n"
        "1. Один конфиг можно использовать <b>максимум на 3 устройствах</b>. При превышении лимита конфиг <b>безвозвратно блокируется</b>!\n"
        "2. Не отписывайся от спонсорских каналов — VPN отключится автоматически.\n\n"
        "💬 Если возникли проблемы — напиши <a href='https://t.me/rooters10'>Администратору</a>."
    )

    await message.answer(
        instruction_text, parse_mode="HTML", disable_web_page_preview=True
    )

    # Создаём media group (альбом)
    image_folder = "images"
    image_files = [
        ("1.jpg", "Шаг 1: Скачай Hiddify"),
        ("2.jpg", "Шаг 2: Добавь конфиг"),
        ("3.jpg", "Шаг 3: Настройки"),
        ("4.jpg", "Шаг 4: VPN режим"),
        ("5.jpg", "Шаг 5: Подключись"),
        ("6.jpg", "Шаг 6: Готово!"),
    ]

    media_group = []

    for filename, caption in image_files:
        image_path = os.path.join(image_folder, filename)

        if os.path.exists(image_path):
            media_group.append(
                InputMediaPhoto(media=FSInputFile(image_path), caption=caption)
            )

    # Отправляем альбом (все фото вместе)
    if media_group:
        try:
            await message.answer_media_group(media=media_group)
        except Exception as e:
            logger.error(f"Ошибка отправки альбома: {e}")
    else:
        await message.answer("⚠️ Изображения инструкции не найдены")





def is_subscription_expired(user) -> bool:
    if not user.subscription_end_date:
        return True
    return datetime.utcnow() >= user.subscription_end_date


# ============ КОМАНДЫ ============


@router.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    """Обработка команды /start"""
    user_id_tg = message.from_user.id

    logger.info(f"🆕 /start от пользователя {user_id_tg}")

    # Реферальная система
    referred_by_id = None
    if command.args and command.args.startswith("ref_"):
        try:
            referred_by_id = int(command.args.split("_")[1])
            if referred_by_id == user_id_tg:
                referred_by_id = None
        except ValueError:
            pass

    # Сохраняем пользователя в БД
    async with AsyncSessionLocal() as session:
        user, created = await get_or_create_user(
            session,
            user_id_tg,
            message.from_user.username,
            message.from_user.first_name,
            referred_by_id=referred_by_id,
        )

    # Выбираем клавиатуру
    if user_id_tg == settings.ADMIN_USER_ID:
        keyboard = get_admin_keyboard()
    else:
        keyboard = get_main_keyboard()

    await message.answer(
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        f"🔐 Добро пожаловать в бот для получения бесплатного VPN!\n\n"
        f"<b>Как это работает:</b>\n"
        f"1️⃣ Подпишись на наши каналы\n"
        f"2️⃣ Получи VPN конфиг\n"
        f"3️⃣ Настрой приложение по инструкции\n"
        f"4️⃣ Пользуйся интернетом без ограничений!\n\n"
        f"💡 Нажми <b>«Получить VPN»</b> чтобы начать.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ============ ПОЛУЧЕНИЕ ПОДПИСКИ ============


@router.message(F.text == "📥 Получить VPN")
async def get_subscription(message: types.Message):
    user_id_tg = message.from_user.id
    logger.info(f"Запрос VPN от {user_id_tg}")

    async with AsyncSessionLocal() as session:
        user, created = await get_or_create_user(
            session,
            user_id_tg,
            message.from_user.username,
            message.from_user.first_name,
        )

        config = await get_user_config(session, user.id)

        # Если конфиг уже есть
        if config and config.is_active:
            # === ПРОВЕРКА ИСТЕЧЕНИЯ ПОДПИСКИ ===
            is_expired = is_subscription_expired(user)

            if is_expired:
                # Подписка истекла — отключаем конфиг на 3x-ui
                logger.info(f"⏳ Подписка {user_id_tg} истекла, отключаем VPN")
                from database.models import VpnServer
                from database.server_operations import decrement_server_users
                from xui_api.manager import ServerManagerFactory

                if config.server_id:
                    result = await session.execute(
                        select(VpnServer).where(VpnServer.id == config.server_id)
                    )
                    server = result.scalar_one_or_none()
                    if server:
                        server_manager = ServerManagerFactory.create_manager(
                            server.host,
                            server.username,
                            server.password,
                            server.inbound_id,
                        )
                        success = await server_manager.disable_config(config.email)
                        if success:
                            config.is_active = False
                            await decrement_server_users(session, config.server_id)
                            await session.commit()

                # Показываем кнопки оплаты
                from telegram_bot.keyboards import get_payment_keyboard

                price_1_month = await get_setting(session, "price_1_month_rub", 150)
                price_6_months = await get_setting(session, "price_6_months_rub", 700)

                reply_markup = get_payment_keyboard(price_1_month, price_6_months)

                sub_end = (
                    user.subscription_end_date.strftime("%d.%m.%Y %H:%M UTC")
                    if user.subscription_end_date
                    else "—"
                )
                await message.answer(
                    f"❌ <b>Твоя подписка истекла</b> ({sub_end})\n\n"
                    f"Для продолжения использования VPN продли подписку:",
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                return

            logger.info(f"Пользователь {user_id_tg} уже имеет активный конфиг")
            await message.answer(
                f"✅ <b>У тебя уже есть активный VPN!</b>\n\n"
                f"📱 <b>Твоя конфигурация:</b>\n"
                f"<code>{config.config_url}</code>\n\n"
                f"💡 Если не настроил VPN — нажми <b>«Инструкция»</b>",
                parse_mode="HTML",
            )
            return

        # Проверяем, есть ли назначенные каналы
        subscriptions = await get_user_subscriptions(session, user.id)

        if not subscriptions:
            # Первый батч для нового пользователя
            from database.operations import assign_initial_channels

            channels = await assign_initial_channels(session, user.id, count=3)

            if not channels:
                await message.answer("Нет доступных каналов.")
                return

            logger.info(
                f"Назначен первый батч ({len(channels)} каналов) пользователю {user_id_tg}"
            )
            subscriptions = await get_user_subscriptions(session, user.id)

        channel_ids = [sub.channel_id for sub in subscriptions]
        result = await session.execute(
            select(Channel).where(Channel.id.in_(channel_ids))
        )
        channels = result.scalars().all()

        logger.info(f"📢 Показываю {len(channels)} каналов пользователю {user_id_tg}")

        keyboard = get_channels_keyboard(channels)

        await message.answer(
            "📢 <b>Для получения VPN подпишись на наши каналы:</b>\n\n"
            "1. Нажми на каждый канал ниже и подпишись\n"
            "2. После подписки на все каналы нажми <b>«Проверить подписку»</b>\n\n"
            "⚠️ <b>Важно:</b> Если отпишешься — VPN отключится автоматически!",
            reply_markup=keyboard,
            parse_mode="HTML",
        )


@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: types.CallbackQuery):
    """Проверка подписок на каналы"""
    user_id_tg = callback.from_user.id
    logger.info(f"✅ Проверка подписки от пользователя {user_id_tg}")

    async with AsyncSessionLocal() as session:
        user, created = await get_or_create_user(
            session,
            user_id_tg,
            callback.from_user.username,
            callback.from_user.first_name,
        )

        # Получаем все выданные каналы пользователя
        from database.operations import get_user_subscriptions

        subscriptions = await get_user_subscriptions(session, user.id)

        if not subscriptions:
            await callback.message.answer("У тебя ещё нет назначенных каналов.")
            await callback.answer()
            return

        # Получаем каналы
        from database.models import Channel

        channel_ids = [sub.channel_id for sub in subscriptions]
        result = await session.execute(
            select(Channel).where(Channel.id.in_(channel_ids))
        )
        channels = result.scalars().all()

        # Проверяем подписки
        await subscription_checker.start()

        all_subscribed = True
        unsubscribed = []

        for channel in channels:
            is_subscribed = await subscription_checker.is_user_subscribed(
                user_id_tg,
                (
                    channel.channel_username
                    if channel.channel_username
                    else channel.channel_id
                ),
            )

            if not is_subscribed:
                all_subscribed = False
                unsubscribed.append((channel.display_name, channel.channel_url))

        if not all_subscribed:
            channels_text = "\n".join([f"- {ch}" for ch, _ in unsubscribed])
            await callback.message.answer(
                f"❌ <b>Не все подписки выполнены!</b>\n\n"
                f"{channels_text}\n\n"
                f"Подпишись на эти каналы и нажми <b>'Проверить подписку'</b> снова.",
                parse_mode="HTML",
            )
            await callback.answer()
            return

        # Все подписки выполнены — обновляем в БД
        from datetime import datetime

        for sub in subscriptions:
            sub.is_subscribed = True
            sub.last_checked_at = datetime.utcnow()
        await session.commit()

        # Получаем конфиг
        config = await get_user_config(session, user.id)

        if config:
            if config.is_active:
                # Конфиг уже активен
                await callback.message.answer(
                    f"✅ <b>Твой VPN уже активен!</b>\n\n"
                    f"📱 <b>Конфигурация:</b>\n"
                    f"<code>{config.config_url}</code>\n\n"
                    f"💡 Нажми <b>«Инструкция»</b> для настройки",
                    parse_mode="HTML",
                )
            else:
                # === ПРОВЕРКА ИСТЕЧЕНИЯ ПОДПИСКИ ПЕРЕД ВКЛЮЧЕНИЕМ ===
                is_expired = is_subscription_expired(user)

                if is_expired:
                    from telegram_bot.keyboards import get_payment_keyboard

                    price_1_month = await get_setting(session, "price_1_month_rub", 150)
                    price_6_months = await get_setting(
                        session, "price_6_months_rub", 700
                    )

                    reply_markup = get_payment_keyboard(price_1_month, price_6_months)

                    await callback.message.answer(
                        f"❌ <b>Подписка истекла!</b>\n\n"
                        f"Для включения VPN необходимо продлить подписку:",
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                    await callback.answer()
                    return

                # Нужно включить конфиг
                logger.info(f"🔄 Включаем конфиг для {user_id_tg}")

                if config.server_id is None:
                    # Конфиг был зачищен
                    from database.operations import recreate_user_config

                    success = await recreate_user_config(session, user, config)
                    if success:
                        await callback.message.answer(
                            f"🎉 <b>Отлично! Твой VPN снова активен!</b>\n\n"
                            f"📱 <b>Новая конфигурация:</b>\n"
                            f"<code>{config.config_url}</code>\n\n"
                            f"💡 Нажми <b>«Инструкция»</b> для настройки\n\n"
                            f"⚠️ Не отписывайся от каналов, иначе VPN отключится автоматически!",
                            parse_mode="HTML",
                        )
                    else:
                        await callback.message.answer(
                            "❌ <b>Ошибка!</b>\n\nНе удалось получить новый сервер. Обратись к администратору.",
                            parse_mode="HTML",
                        )
                    await callback.answer()
                    return

                # Получаем правильный сервер
                from database.models import VpnServer
                from xui_api.manager import ServerManagerFactory

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
                        logger.info(
                            f"Включаем конфиг на сервере {server.name} (ID: {server.id})"
                        )
                    else:
                        logger.error(
                            f"Сервер {config.server_id} не найден для {user_id_tg}"
                        )
                        await callback.message.answer(
                            "❌ <b>Ошибка!</b>\n\nСервер не найден. Обратись к администратору.",
                            parse_mode="HTML",
                        )
                        await callback.answer()
                        return
                else:
                    server_manager = xui_manager
                    logger.warning(
                        f"Конфиг {user_id_tg} без server_id, используем дефолтный сервер"
                    )

                # Включаем через правильный менеджер
                success = await server_manager.enable_config(config.email)

                if success:
                    config.is_active = True
                    await session.commit()

                    await callback.message.answer(
                        f"🎉 <b>Отлично! Твой VPN снова активен!</b>\n\n"
                        f"📱 <b>Конфигурация:</b>\n"
                        f"<code>{config.config_url}</code>\n\n"
                        f"💡 Нажми <b>«Инструкция»</b> для настройки\n\n"
                        f"⚠️ Не отписывайся от каналов, иначе VPN отключится автоматически!",
                        parse_mode="HTML",
                    )
                else:
                    await callback.message.answer(
                        "❌ Не удалось включить конфиг. Попробуй позже."
                    )
        else:
            # ===== КОНФИГА НЕТ — СОЗДАЁМ НОВЫЙ =====
            logger.info(f"🆕 Создаём конфиг для {user_id_tg}")

            from database.server_operations import (
                get_optimal_server,
                increment_server_users,
            )
            from database.operations import assign_initial_channels
            from xui_api.manager import ServerManagerFactory
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            server = await get_optimal_server(session)

            if not server:
                await callback.message.answer(
                    "❌ <b>Извини!</b>\n\n" "Все серверы заполнены. Попробуй позже.",
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            logger.info(
                f"Выбран сервер {server.name} ({server.current_users}/{server.max_users})"
            )

            # Создаём менеджер для выбранного сервера
            manager = ServerManagerFactory.create_manager(
                server.host, server.username, server.password, server.inbound_id
            )

            email = f"user_{user_id_tg}"
            config_url = await manager.create_config(email)

            if not config_url:
                await callback.message.answer(
                    "❌ <b>Ошибка создания конфига!</b>\n\n" "Попробуй позже.",
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            # Сохраняем конфиг в БД
            config = await create_vpn_config(
                session=session,
                user_id=user.id,
                server_id=server.id,
                email=email,
                config_url=config_url,
            )

            await increment_server_users(session, server.id)

            logger.info(f"✅ Конфиг создан для {user_id_tg} на сервере {server.name}")

            # --- БОНУСЫ И ТРИАЛ ---
            from database.operations import extend_subscription, add_referral_bonus

            # Выдаем триал на 7 дней
            user = await extend_subscription(session, user.id, days=7)

            # Если есть реферал, выдаем 3 дня обоим
            if user.referred_by_id:
                await add_referral_bonus(session, user.referred_by_id, user.id, days=3)
            # ----------------------

            # ===== ВЫДАЁМ ПЕРВЫЕ 3 КАНАЛА И СРАЗУ ОБНОВЛЯЕМ is_subscribed =====
            channels = await assign_initial_channels(session, user.id, count=3)

            # ===== ВАЖНО: Сразу обновляем is_subscribed в только что созданных подписках =====
            # Чтобы scheduler не отключил VPN сразу после создания
            from database.operations import get_user_subscriptions

            fresh_subscriptions = await get_user_subscriptions(session, user.id)

            for sub in fresh_subscriptions:
                sub.is_subscribed = (
                    True  # Считаем что пользователь только что подписался
                )
                sub.last_checked_at = datetime.utcnow()

            await session.commit()
            logger.info(f"✅ Подписки отмечены как активные для {user_id_tg}")

            # Отправляем уведомление
            await callback.message.answer(
                f"🎉 <b>Поздравляю! Твой VPN готов!</b>\n\n"
                f"📱 <b>Конфигурация:</b>\n<code>{config_url}</code>\n\n"
                f"⚠️ <b>ВАЖНО!</b>\n"
                f"- Один конфиг работает максимум на <b>3 устройствах</b>.\n"
                f"- ❗️ При превышении лимита устройств конфиг <b>безвозвратно блокируется</b>.\n"
                f"- Пожалуйста, никому не передавай свой конфиг.",
                parse_mode="HTML",
            )

            # Отправляем полную инструкцию с фото
            await send_instruction_to_user(callback.message)

    await callback.answer()


# ============ МОЙ КОНФИГ ============


@router.message(F.text == "🔑 Мой конфиг")
async def my_config(message: types.Message):
    """Показать профиль (конфиг, срок подписки)"""
    user_id_tg = message.from_user.id

    async with AsyncSessionLocal() as session:
        user, created = await get_or_create_user(
            session,
            user_id_tg,
            message.from_user.username,
            message.from_user.first_name,
        )

        config = await get_user_config(session, user.id)

        is_expired = is_subscription_expired(user)
        if user.subscription_end_date:
            sub_end = user.subscription_end_date.strftime("%d.%m.%Y %H:%M UTC")
            if is_expired:
                sub_end = f"❌ <b>Истекла</b> ({sub_end})"
        else:
            sub_end = "❌ Нет активной подписки"

        reply_markup = None
        if is_expired:
            from telegram_bot.keyboards import get_payment_keyboard

            price_1_month = await get_setting(session, "price_1_month_rub", 150)
            price_6_months = await get_setting(session, "price_6_months_rub", 700)

            reply_markup = get_payment_keyboard(price_1_month, price_6_months)

        if not config:
            await message.answer(
                f"⏳ <b>Подписка до:</b> {sub_end}\n\n"
                f"❌ <b>У тебя ещё нет конфига</b>\n"
                f"Нажми <b>«📥 Получить VPN»</b> чтобы создать конфиг.",
                parse_mode="HTML",
            )
            return

        if config and config.config_url == "":
            await message.answer(
                f"⏳ <b>Подписка до:</b> {sub_end}\n\n"
                f"❌ <b>Твой конфиг был удален из-за долгой неактивности.</b>\n"
                f"Оплати подписку или нажми <b>«Проверить подписку»</b>, чтобы мы выдали тебе новый конфиг.",
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return

        status = (
            "✅ <b>Активен</b>"
            if config.is_active and not is_expired
            else "❌ <b>Отключён</b>"
        )

        await message.answer(
            f"⏳ <b>Подписка до:</b> {sub_end}\n"
            f"Статус VPN: {status}\n\n"
            f"📱 <b>Конфигурация (нажми чтобы скопировать):</b>\n"
            f"<code>{config.config_url}</code>\n\n"
            f"⚠️ <b>ВАЖНО:</b> Конфиг можно использовать максимум на <b>3 устройствах</b>.\n"
            f"❗️ При превышении лимита конфиг <b>блокируется без возможности восстановления</b>.\n\n"
            f"💡 Для настройки нажми <b>«📖 Инструкция»</b>.",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


# ============ ПРИГЛАСИТЬ ДРУГА ============


@router.message(F.text == "🎁 Пригласить друга")
async def invite_friend(message: types.Message):
    """Обработчик кнопки Пригласить друга"""
    user_id_tg = message.from_user.id

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(
            session,
            user_id_tg,
            message.from_user.username,
            message.from_user.first_name,
        )
        from database.operations import get_referrals_count

        referrals_count = await get_referrals_count(session, user.id)

        bot_info = await message.bot.get_me()
        bot_username = bot_info.username
        referral_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        import urllib.parse

        # Кнопка для старого способа (Отправить через выбор чатов)
        share_text = urllib.parse.quote(
            "Привет! Держи отличный VPN. По моей ссылке ты получишь 7 бесплатных дней 🎉"
        )
        share_url = f"https://t.me/share/url?url={referral_link}&text={share_text}"

        share_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📤 Отправить другу", url=share_url)]
            ]
        )

        await message.answer(
            f"🎁 <b>Реферальная система</b>\n\n"
            f"Приглашай друзей и получай <b>+3 дня</b> бесплатного VPN за каждого, кто запустит бота и получит конфиг!\n\n"
            f"👥 Ты уже пригласил: {referrals_count} чел.\n\n"
            f"👇 <i>Перешли сообщение ниже своему другу:</i>",
            parse_mode="HTML",
        )

        # Сообщение специально для пересылки
        forward_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚀 Запустить бота и получить VPN", url=referral_link
                    )
                ]
            ]
        )

        await message.answer(
            f"Привет! 👋\n\n"
            f"Я нашел отличного бота для VPN. Он работает быстро и без перебоев.\n\n"
            f"🎁 <i>Переходи по кнопке ниже и получи 7 дней бесплатно!</i>",
            reply_markup=forward_markup,
            parse_mode="HTML",
        )


# ============ ИНСТРУКЦИЯ ============


@router.message(F.text == "📖 Инструкция")
async def show_instruction(message: types.Message):
    """Показать инструкцию с фотографиями"""
    await send_instruction_to_user(message)


# ============ ПОМОЩЬ ============


@router.message(F.text == "❓ Помощь")
async def help_command(message: types.Message):
    """Показать справку"""
    await message.answer(
        "<b>📥 Получить VPN</b> — создать VPN конфиг\n"
        "<b>🔑 Мой конфиг</b> — посмотреть твой конфиг\n"
        "<b>📖 Инструкция</b> — как настроить VPN\n\n"
        "<b>🔐 Как работает бот:</b>\n"
        "1. Подпишись на наши каналы\n"
        "2. Получи VPN конфиг\n"
        "3. Настрой приложение по инструкции\n"
        "4. Пользуйся!\n\n"
        "<b>⚠️ Правила:</b>\n"
        "- Не отписывайся от каналов — VPN отключится\n"
        "- Один конфиг можно использовать максимум на <b>3 устройствах</b>\n"
        "- Быстрая блокировка конфига навсегда при превышении лимита устройств\n"
        "- При проблемах пиши администратору\n\n"
        "💬 Поддержка: @rooters10\n\n"
        "<b>Политика конфиденциальности</b>\n"
        "https://telegra.ph/Politika-konfidencialnosti-08-15-17\n"
        "https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10\n",
        parse_mode="HTML",
    )


# ============ ОПЛАТА PLATEGA ============


@router.callback_query(F.data.in_(["buy_1_month", "buy_6_months"]))
async def process_buy_callback(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку покупки (Создание транзакции через Platega.io)"""
    action = callback.data
    user_id_tg = callback.from_user.id

    async with AsyncSessionLocal() as session:
        price_1_month = await get_setting(session, "price_1_month_rub", 150)
        price_6_months = await get_setting(session, "price_6_months_rub", 700)

    if action == "buy_1_month":
        months = 1
        amount = price_1_month
    else:
        months = 6
        amount = price_6_months

    import aiohttp

    # Payload для идентификации платежа: TGID_MONTHS
    payload = f"{user_id_tg}_{months}"

    # Создаём транзакцию через Platega API
    try:
        async with aiohttp.ClientSession() as http_session:
            resp = await http_session.post(
                f"{settings.PLATEGA_API_URL}/transaction/process",
                headers={
                    "X-MerchantId": settings.PLATEGA_MERCHANT_ID,
                    "X-Secret": settings.PLATEGA_SECRET,
                    "Content-Type": "application/json",
                },
                json={
                    "paymentMethod": 2,  # СБП QR
                    "paymentDetails": {"amount": amount, "currency": "RUB"},
                    "description": f"VPN подписка на {months} мес.",
                    "payload": payload,
                },
            )

            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"Platega API error: {resp.status} - {error_text}")
                await callback.message.answer(
                    "❌ Ошибка создания платежа. Попробуйте позже."
                )
                await callback.answer()
                return

            data = await resp.json()

        payment_url = data.get("redirect")

        if not payment_url:
            logger.error(f"Platega API: нет redirect в ответе: {data}")
            await callback.message.answer(
                "❌ Ошибка создания платежа. Попробуйте позже."
            )
            await callback.answer()
            return

        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💸 Оплатить (СБП)", url=payment_url)]
            ]
        )

        await callback.message.answer(
            f"⏳ <b>Оплата подписки на {months} мес.</b>\n\n"
            f"Сумма к оплате: <b>{amount} руб.</b>\n\n"
            f"Нажмите кнопку ниже для перехода к оплате через СБП.\n"
            f"После успешной оплаты подписка будет активирована автоматически.",
            reply_markup=markup,
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Ошибка создания платежа Platega: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка создания платежа. Попробуйте позже.")

    await callback.answer()
