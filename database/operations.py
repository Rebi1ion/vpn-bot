from datetime import datetime, timedelta
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from config import settings
from database.models import User, VpnConfig, Channel, UserChannelSubscription
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ==================== ПОЛЬЗОВАТЕЛИ ====================


async def get_user_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> Optional[User]:
    """
    Получить пользователя по Telegram ID.

    Args:
        session: Сессия БД
        telegram_id: Telegram ID пользователя

    Returns:
        User или None если не найден
    """
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str):
    """Получить пользователя по username"""
    result = await session.execute(select(User).where(User.username == username))
    return result.scalars().first()


async def create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    referred_by_id: Optional[int] = None,
) -> User:
    """
    Создать нового пользователя.

    Args:
        session: Сессия БД
        telegram_id: Telegram ID
        username: Username пользователя
        first_name: Имя пользователя
        referred_by_id: ID пользователя, который пригласил

    Returns:
        Созданный пользователь
    """
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        referred_by_id=referred_by_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)  # Обновляем объект (получаем ID)

    logger.info(f"✅ Создан пользователь: {telegram_id}")
    return user


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    referred_by_id: Optional[int] = None,
) -> tuple[User, bool]:
    """
    Получить пользователя или создать если не существует.

    Args:
        session: Сессия БД
        telegram_id: Telegram ID
        username: Username пользователя
        first_name: Имя пользователя
        referred_by_id: ID пользователя, который пригласил

    Returns:
        Кортеж (Пользователь, Был ли создан только что)
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if user:
        return user, False
    user = await create_user(session, telegram_id, username, first_name, referred_by_id)
    return user, True


# ==================== НАСТРОЙКИ БОТА ====================


async def get_setting(session: AsyncSession, key: str, default_value: int = 0) -> int:
    """Получить целочисленную настройку из БД"""
    from database.models import BotSettings

    result = await session.execute(select(BotSettings).where(BotSettings.key == key))
    setting = result.scalar_one_or_none()
    if setting is not None and setting.value_int is not None:
        return setting.value_int
    return default_value


async def set_setting(
    session: AsyncSession, key: str, value_int: int, description: str = None
):
    """Установить целочисленную настройку в БД"""
    from database.models import BotSettings

    result = await session.execute(select(BotSettings).where(BotSettings.key == key))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value_int = value_int
        if description:
            setting.description = description
    else:
        setting = BotSettings(key=key, value_int=value_int, description=description)
        session.add(setting)

    await session.commit()
    logger.info(f"Настройка {key} обновлена: {value_int}")


async def initialize_default_settings(session: AsyncSession):
    """Инициализация дефолтных цен, если их нет"""
    from database.models import BotSettings

    # Дефолтные значения (1 месяц = 150, 6 месяцев = 700, 12 месяцев = 1200)
    defaults = {
        "price_1_month_rub": (150, "Цена за 1 месяц (RUB)"),
        "price_6_months_rub": (700, "Цена за 6 месяцев (RUB)"),
        "price_12_months_rub": (1200, "Цена за 12 месяцев (RUB)"),
    }

    for key, (val, desc) in defaults.items():
        result = await session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        if not result.scalar_one_or_none():
            setting = BotSettings(key=key, value_int=val, description=desc)
            session.add(setting)
            logger.info(f"Создана базовая настройка {key}: {val}")

    await session.commit()


async def extend_subscription(
    session: AsyncSession, user_id: int, days: int = 0, months: int = 0
) -> User:
    """Продлить подписку пользователя"""
    user = await session.get(User, user_id)
    if not user:
        return None

    now = datetime.utcnow()
    # Если подписки нет или закончилась - продлеваем от текущего момента
    start_date = (
        user.subscription_end_date
        if user.subscription_end_date and user.subscription_end_date > now
        else now
    )

    import calendar

    # Высчитываем новый месяц
    month = start_date.month - 1 + months
    year = start_date.year + month // 12
    month = month % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])

    new_end_date = start_date.replace(year=year, month=month, day=day)

    if days > 0:
        new_end_date += timedelta(days=days)
    user.subscription_end_date = new_end_date
    user.is_reminded_3d = False  # Сброс флага напоминания
    await session.commit()
    logger.info(f"✅ Подписка пользователя {user_id} продлена до {new_end_date}")
    return user


async def get_referrals_count(session: AsyncSession, user_id: int) -> int:
    """Получить количество рефералов пользователя"""
    from sqlalchemy import func

    result = await session.execute(
        select(func.count(User.id)).where(User.referred_by_id == user_id)
    )
    return result.scalar()


async def add_referral_bonus(
    session: AsyncSession, referrer_id: int, referee_id: int, days: int = 3
):
    """Выдать бонус за реферала обоим пользователям"""
    await extend_subscription(session, referrer_id, days=days)
    await extend_subscription(session, referee_id, days=days)
    logger.info(
        f"🎁 Выдан реферальный бонус ({days} дней) пользователям {referrer_id} и {referee_id}"
    )


# ==================== VPN КОНФИГИ ====================


async def get_user_config(session: AsyncSession, user_id: int) -> Optional[VpnConfig]:
    """
    Получить VPN конфиг пользователя.

    Args:
        session: Сессия БД
        user_id: ID пользователя

    Returns:
        VpnConfig или None если нет конфига
    """
    result = await session.execute(
        select(VpnConfig).where(VpnConfig.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_vpn_config(
    session: AsyncSession,
    user_id: int,
    email: str,
    config_url: str,
    server_id: int = None,  # ← ДОБАВЬ ЭТО
) -> VpnConfig:
    """Создать VPN конфиг для пользователя"""

    config = VpnConfig(
        user_id=user_id,
        server_id=server_id,  # ← ДОБАВЬ ЭТО
        email=email,
        config_url=config_url,
        is_active=True,
    )

    session.add(config)
    await session.commit()
    await session.refresh(config)

    logger.info(f"✅ Создан конфиг для user_id={user_id}")
    return config


async def update_config_status(
    session: AsyncSession, config_id: int, is_active: bool
) -> bool:
    """
    Обновить статус конфига (включить/отключить).

    Args:
        session: Сессия БД
        config_id: ID конфига
        is_active: True = включить, False = отключить

    Returns:
        True если успешно, False если конфиг не найден
    """
    result = await session.execute(select(VpnConfig).where(VpnConfig.id == config_id))
    config = result.scalar_one_or_none()

    if not config:
        return False

    config.is_active = is_active
    await session.commit()

    status = "включён" if is_active else "отключен"
    logger.info(f"✅ Конфиг {config_id} {status}")
    return True


# ==================== КАНАЛЫ ====================


async def get_all_active_channels(session: AsyncSession) -> list[Channel]:
    """
    Получить все активные каналы, отсортированные по порядку.

    Args:
        session: Сессия БД

    Returns:
        Список каналов
    """
    result = await session.execute(
        select(Channel).where(Channel.is_active == True).order_by(Channel.order)
    )
    return result.scalars().all()


async def create_channel(
    session: AsyncSession,
    channel_username: str,
    channel_url: str,
    display_name: str,
    order: int = 0,
) -> Channel:
    """
    Создать новый канал для подписки.

    Args:
        session: Сессия БД
        channel_username: Username канала (для проверки подписки)
        channel_url: Invite URL канала
        display_name: Отображаемое имя
        order: Порядок отображения

    Returns:
        Созданный канал
    """
    channel = Channel(
        channel_username=channel_username,
        channel_url=channel_url,
        display_name=display_name,
        order=order,
        is_active=True,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    logger.info(f"✅ Создан канал: {display_name}")
    return channel


# ==================== ПОДПИСКИ ====================


async def assign_channels_to_user(
    session: AsyncSession, user_id: int, channel_ids: list[int]
) -> None:
    """
    Выдать каналы пользователю (добавить в историю подписок).

    Args:
        session: Сессия БД
        user_id: ID пользователя
        channel_ids: Список ID каналов для выдачи
    """
    for channel_id in channel_ids:
        subscription = UserChannelSubscription(
            user_id=user_id, channel_id=channel_id, is_subscribed=False
        )
        session.add(subscription)

    await session.commit()
    logger.info(f"✅ Выданы каналы пользователю {user_id}: {channel_ids}")


async def get_user_subscriptions(
    session: AsyncSession, user_id: int
) -> list[UserChannelSubscription]:
    """
    Получить все подписки пользователя.

    Args:
        session: Сессия БД
        user_id: ID пользователя

    Returns:
        Список подписок
    """
    result = await session.execute(
        select(UserChannelSubscription).where(
            UserChannelSubscription.user_id == user_id
        )
    )
    return result.scalars().all()


async def update_subscription_status(
    session: AsyncSession, subscription_id: int, is_subscribed: bool
) -> None:
    """
    Обновить статус подписки.

    Args:
        session: Сессия БД
        subscription_id: ID подписки
        is_subscribed: Подписан или нет
    """
    result = await session.execute(
        select(UserChannelSubscription).where(
            UserChannelSubscription.id == subscription_id
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription:
        subscription.is_subscribed = is_subscribed
        await session.commit()


# ==================== КАНАЛЫ (расширенные операции) ====================


async def delete_channel(session: AsyncSession, channel_id: int) -> bool:
    """
    Полностью удалить канал из БД (жёсткое удаление).

    Args:
        session: Сессия БД
        channel_id: ID канала

    Returns:
        True если успешно, False если нет
    """
    try:
        # Получаем канал
        result = await session.execute(select(Channel).where(Channel.id == channel_id))
        channel = result.scalar_one_or_none()

        if not channel:
            logger.warning(f"Канал {channel_id} не найден")
            return False

        channel_name = channel.display_name

        # Сначала удаляем все связанные подписки
        await session.execute(
            delete(UserChannelSubscription).where(
                UserChannelSubscription.channel_id == channel_id
            )
        )

        # Жёстко удаляем канал
        await session.delete(channel)
        await session.commit()

        logger.info(
            f"✅ Канал '{channel_name}' (ID: {channel_id}) полностью удалён из БД"
        )
        return True

    except Exception as e:
        await session.rollback()
        logger.error(f"❌ Ошибка удаления канала {channel_id}: {e}")
        return False


async def get_channels_batch(
    session: AsyncSession, batch_size: int = 3, offset: int = 0
) -> list[Channel]:
    """
    Получить батч каналов по порядку.

    Args:
        session: Сессия БД
        batch_size: Размер батча
        offset: Смещение (какой батч по счёту)

    Returns:
        Список каналов
    """
    result = await session.execute(
        select(Channel)
        .where(Channel.is_active == True)
        .order_by(Channel.created_at)  # Сортировка по времени создания
        .offset(offset)
        .limit(batch_size)
    )
    return result.scalars().all()


async def get_channel_by_username(
    session: AsyncSession, channel_username: str
) -> Optional[Channel]:
    """
    Получить канал по username.

    Args:
        session: Сессия БД
        channel_username: Username канала

    Returns:
        Channel или None
    """
    result = await session.execute(
        select(Channel).where(Channel.channel_username == channel_username)
    )
    return result.scalar_one_or_none()


async def count_active_channels(session: AsyncSession) -> int:
    """
    Посчитать количество активных каналов.

    Returns:
        Количество каналов
    """
    from sqlalchemy import func

    result = await session.execute(
        select(func.count(Channel.id)).where(Channel.is_active == True)
    )
    return result.scalar()


async def assign_next_channel_batch(
    session: AsyncSession, user_id: int, batch_size: int = 3
) -> list[Channel]:
    """
    Назначить следующий батч каналов пользователю.

    Args:
        session: Сессия БД
        user_id: ID пользователя
        batch_size: Количество каналов в батче (по умолчанию 3)

    Returns:
        Список назначенных каналов
    """
    from config.settings import settings
    from datetime import datetime, timedelta

    # Получаем пользователя
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Пользователь {user_id} не найден")
        return []

    current_batch = user.current_batch

    # Получаем каналы для текущего батча (порция с учётом offset)
    result = await session.execute(
        select(Channel)
        .where(Channel.is_active == True)
        .order_by(Channel.order)
        .offset(current_batch * batch_size)
        .limit(batch_size)
    )
    channels = result.scalars().all()

    if not channels:
        logger.info(f"Все каналы уже назначены пользователю {user_id}")

        # ===== ПРОВЕРЯЕМ НАЛИЧИЕ КОНФИГА ЧЕРЕЗ ЗАПРОС =====
        result = await session.execute(
            select(VpnConfig).where(VpnConfig.user_id == user_id)
        )
        config = result.scalar_one_or_none()

        # Если у пользователя есть конфиг, он становится "старым" пользователем
        if config:
            user.next_batch_date = None  # Больше не нужно проверять батчи
            await session.commit()
            logger.info(
                f"✅ Пользователь {user_id} помечен как 'старый' (все каналы назначены)"
            )

        return []

    # Текущее время уведомления
    notification_time = datetime.utcnow()

    # Устанавливаем дедлайн в зависимости от режима
    if settings.TEST_MODE:
        deadline = notification_time + timedelta(
            minutes=settings.SUBSCRIPTION_DEADLINE_MINUTES
        )
        logger.info(
            f"[TEST_MODE] Дедлайн через {settings.SUBSCRIPTION_DEADLINE_MINUTES} минут"
        )
    else:
        deadline = notification_time + timedelta(
            hours=settings.SUBSCRIPTION_DEADLINE_HOURS
        )
        logger.info(f"Дедлайн через {settings.SUBSCRIPTION_DEADLINE_HOURS} часов")

    # Создаем записи подписок для каждого канала в батче
    for channel in channels:
        subscription = UserChannelSubscription(
            user_id=user_id,
            channel_id=channel.id,
            batch_number=current_batch,
            notification_sent_at=notification_time,
            deadline_at=deadline,
            is_subscribed=False,
        )
        session.add(subscription)

    # Обновляем счётчик батчей у пользователя
    user.current_batch += 1

    # Устанавливаем дату следующего батча
    if settings.TEST_MODE:
        user.next_batch_date = datetime.utcnow() + timedelta(
            minutes=settings.BATCH_INTERVAL_MINUTES
        )
        logger.info(
            f"[TEST_MODE] Следующий батч через {settings.BATCH_INTERVAL_MINUTES} минут"
        )
    else:
        user.next_batch_date = datetime.utcnow() + timedelta(
            days=settings.BATCH_INTERVAL_DAYS
        )
        logger.info(f"Следующий батч через {settings.BATCH_INTERVAL_DAYS} дней")

    await session.commit()
    logger.info(
        f"✅ Назначен батч #{current_batch} ({len(channels)} каналов) пользователю {user_id}"
    )

    return channels


async def get_users_needing_new_channels(session: AsyncSession) -> list[User]:
    """
    Получить список новых пользователей, которым пора выдать следующий батч.

    Returns:
        Список пользователей
    """
    now = datetime.utcnow()

    result = await session.execute(
        select(User)
        .where(User.has_active_config == False)  # Только новые пользователи
        .where(
            User.next_batch_date != None
        )  # У которых установлена дата следующего батча
        .where(User.next_batch_date <= now)  # И время уже подошло
    )
    return result.scalars().all()


async def get_expired_subscriptions(
    session: AsyncSession,
) -> list[tuple[User, list[UserChannelSubscription]]]:
    """
    Получить пользователей с просроченными подписками.

    Returns:
        Список кортежей (User, список просроченных подписок)
    """
    now = datetime.utcnow()

    result = await session.execute(
        select(User, UserChannelSubscription)
        .join(UserChannelSubscription, User.id == UserChannelSubscription.user_id)
        .where(UserChannelSubscription.deadline_at <= now)
        .where(UserChannelSubscription.is_subscribed == False)
    )

    # Группируем по пользователям
    from collections import defaultdict

    users_subs = defaultdict(list)

    for user, sub in result.all():
        users_subs[user].append(sub)

    return list(users_subs.items())


async def notify_users_about_new_channels(
    session: AsyncSession, bot, channel_ids: list[int]
):
    """
    Уведомить пользователей с активными конфигами о новых каналах.
    Показывает ТОЛЬКО новые каналы.

    Args:
        session: Сессия БД
        bot: Экземпляр бота
        channel_ids: Список ID новых каналов
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from config.settings import settings
    from datetime import datetime, timedelta, timezone

    # Получаем пользователей с активными конфигами
    result = await session.execute(
        select(User)
        .join(VpnConfig, User.id == VpnConfig.user_id)
        .where(VpnConfig.is_active == True)
        .where(User.has_active_config == True)
    )
    users = result.scalars().all()

    # Получаем информацию о новых каналах
    result = await session.execute(select(Channel).where(Channel.id.in_(channel_ids)))
    channels = result.scalars().all()

    if not channels:
        logger.warning("Каналы для уведомления не найдены")
        return

    # MSK = UTC+3
    msk_tz = timezone(timedelta(hours=3))
    notification_time = datetime.now(msk_tz)

    # Устанавливаем дедлайн
    if settings.TEST_MODE:
        deadline = notification_time + timedelta(
            minutes=settings.SUBSCRIPTION_DEADLINE_MINUTES
        )
        deadline_text = f"{settings.SUBSCRIPTION_DEADLINE_MINUTES} минут"
    else:
        deadline = notification_time + timedelta(
            hours=settings.SUBSCRIPTION_DEADLINE_HOURS
        )
        deadline_text = f"{settings.SUBSCRIPTION_DEADLINE_HOURS} часов"

    logger.info(
        f"Уведомляем {len(users)} пользователей о {len(channels)} новых каналах"
    )

    for user in users:
        # Получаем подписки пользователя
        result = await session.execute(
            select(UserChannelSubscription).where(
                UserChannelSubscription.user_id == user.id
            )
        )
        user_subscriptions = result.scalars().all()
        subscribed_channel_ids = {sub.channel_id for sub in user_subscriptions}

        # Назначаем только те новые каналы, которых ещё нет у пользователя
        channels_to_assign = [
            ch for ch in channels if ch.id not in subscribed_channel_ids
        ]

        if not channels_to_assign:
            logger.info(
                f"Пользователь {user.telegram_id} уже имеет все новые каналы, пропускаем"
            )
            continue

        # Назначаем новые каналы
        for channel in channels_to_assign:
            subscription = UserChannelSubscription(
                user_id=user.id,
                channel_id=channel.id,
                batch_number=user.current_batch,
                notification_sent_at=notification_time,
                deadline_at=deadline,
                is_subscribed=False,
            )
            session.add(subscription)

        user.current_batch += 1

        # Формируем клавиатуру с кнопками каналов
        buttons = []
        for channel in channels_to_assign:
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

        # Отправляем уведомление
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"🆕 <b>Добавлены новые обязательные каналы!</b>\n\n"
                    f"Подпишись на них в течение <b>{deadline_text}</b>, "
                    f"иначе VPN будет отключён.\n\n"
                    f"<b>Новых каналов:</b> {len(channels_to_assign)}\n"
                    f"<b>Дедлайн:</b> {deadline.strftime('%d.%m.%Y %H:%M')} MSK\n\n"
                    f"💡 <i>Автоматическая проверка подписок происходит каждый день.</i>"
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            logger.info(
                f"✅ Уведомление отправлено {user.telegram_id} ({len(channels_to_assign)} новых каналов)"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки {user.telegram_id}: {e}")

    await session.commit()


# ==================== УПРОЩЁННАЯ СИСТЕМА КАНАЛОВ ====================


async def assign_initial_channels(
    session: AsyncSession, user_id: int, count: int = 3
) -> list[Channel]:
    """
    Выдать первые N каналов новому пользователю.

    Args:
        session: Сессия БД
        user_id: ID пользователя
        count: Количество каналов (по умолчанию 3)

    Returns:
        Список выданных каналов
    """
    # Получаем первые N каналов по порядку
    result = await session.execute(
        select(Channel)
        .where(Channel.is_active == True)
        .order_by(Channel.order)
        .limit(count)
    )
    channels = result.scalars().all()

    if not channels:
        logger.warning("Нет активных каналов для выдачи")
        return []

    # Назначаем каналы пользователю
    for channel in channels:
        subscription = UserChannelSubscription(
            user_id=user_id,
            channel_id=channel.id,
            is_subscribed=False,
            assigned_at=datetime.utcnow(),
        )
        session.add(subscription)

    await session.commit()
    logger.info(f"✅ Выдано {len(channels)} начальных каналов пользователю {user_id}")

    return channels


async def assign_next_channel(session: AsyncSession, user_id: int) -> Channel | None:
    """
    Выдать следующий канал пользователю.

    Args:
        session: Сессия БД
        user_id: ID пользователя

    Returns:
        Выданный канал или None если каналы закончились
    """
    # Получаем уже выданные каналы
    result = await session.execute(
        select(UserChannelSubscription.channel_id).where(
            UserChannelSubscription.user_id == user_id
        )
    )
    assigned_channel_ids = [row[0] for row in result.all()]

    # Получаем следующий невыданный канал
    result = await session.execute(
        select(Channel)
        .where(Channel.is_active == True)
        .where(
            Channel.id.not_in(assigned_channel_ids) if assigned_channel_ids else True
        )
        .order_by(Channel.order)
        .limit(1)
    )
    channel = result.scalar_one_or_none()

    if not channel:
        logger.info(f"Пользователю {user_id} выданы все каналы")
        return None

    # Назначаем канал
    subscription = UserChannelSubscription(
        user_id=user_id,
        channel_id=channel.id,
        is_subscribed=False,
        assigned_at=datetime.utcnow(),
    )
    session.add(subscription)
    await session.commit()

    logger.info(f"✅ Выдан канал '{channel.display_name}' пользователю {user_id}")

    return channel


async def get_user_unsubscribed_channels(
    session: AsyncSession, user_id: int
) -> list[Channel]:
    """
    Получить каналы, на которые пользователь не подписан.

    Args:
        session: Сессия БД
        user_id: ID пользователя

    Returns:
        Список каналов без подписки
    """
    result = await session.execute(
        select(Channel)
        .join(UserChannelSubscription, Channel.id == UserChannelSubscription.channel_id)
        .where(UserChannelSubscription.user_id == user_id)
        .where(UserChannelSubscription.is_subscribed == False)
        .order_by(Channel.order)
    )
    return result.scalars().all()


async def get_assigned_channels_count(session: AsyncSession, user_id: int) -> int:
    """
    Получить количество выданных каналов пользователю.

    Args:
        session: Сессия БД
        user_id: ID пользователя

    Returns:
        Количество выданных каналов
    """
    result = await session.execute(
        select(func.count(UserChannelSubscription.id)).where(
            UserChannelSubscription.user_id == user_id
        )
    )
    return result.scalar()


# ==================== ПЛАТЕЖИ И ПАРТНЕРСКИЕ КАНАЛЫ ====================


async def create_payment(
    session: AsyncSession,
    user_id: int,
    amount_stars: int,
    provider_payment_charge_id: str,
    telegram_payment_charge_id: str,
    months_added: int,
):
    from database.models import Payment

    payment = Payment(
        user_id=user_id,
        amount_stars=amount_stars,
        provider_payment_charge_id=provider_payment_charge_id,
        telegram_payment_charge_id=telegram_payment_charge_id,
        months_added=months_added,
    )
    session.add(payment)
    await session.commit()
    logger.info(
        f"✅ Создана запись об оплате {amount_stars} XTR для пользователя {user_id}"
    )
    return payment


async def get_partner_channel(session: AsyncSession):
    """Получить партнерский канал для выдачи бесплатной подписки (1 неделя)"""
    result = await session.execute(
        select(Channel)
        .where(Channel.is_partner_channel == True)
        .where(Channel.is_active == True)
    )
    return result.scalars().first()


async def recreate_user_config(
    session: AsyncSession, user: User, config: VpnConfig
) -> bool:
    """
    Пересоздает конфиг пользователя (если он был зачищен из-за неактивности).
    Ищет новый сервер, создает клиента в 3x-ui, сохраняет url.
    """
    from database.server_operations import get_optimal_server, increment_server_users
    from xui_api.manager import ServerManagerFactory

    server = await get_optimal_server(session)
    if not server:
        logger.error(
            f"recreate_user_config: Нет свободных серверов для пользователя {user.telegram_id}"
        )
        return False

    manager = ServerManagerFactory.create_manager(
        server.host, server.username, server.password, server.inbound_id
    )

    email = f"user_{user.telegram_id}"
    config_url = await manager.create_config(email)

    if not config_url:
        logger.error(
            f"recreate_user_config: Ошибка 3x-ui API при создании конфига {email}"
        )
        return False

    config.server_id = server.id
    config.config_url = config_url
    config.is_active = True

    await increment_server_users(session, server.id)
    await session.commit()

    logger.info(
        f"✅ Успешно пересоздан конфиг для {user.telegram_id} на сервере {server.name}"
    )
    return True
