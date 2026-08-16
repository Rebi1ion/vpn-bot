from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


# ============ ПОЛЬЗОВАТЕЛЬСКИЕ КЛАВИАТУРЫ ============


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню для пользователя"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📥 Получить VPN"),
                KeyboardButton(text="🎁 Пригласить друга"),
            ],
            [KeyboardButton(text="🔑 Мой конфиг")],
            [KeyboardButton(text="📖 Инструкция"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_channels_keyboard(channels: list) -> InlineKeyboardMarkup:
    """
    Клавиатура с каналами для подписки.

    Args:
        channels: Список объектов Channel из БД

    Returns:
        InlineKeyboardMarkup с кнопками-ссылками
    """
    buttons = []

    for channel in channels:
        # Используем channel_url для кнопки (это invite ссылка)
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📢 {channel.display_name}", url=channel.channel_url
                )
            ]
        )

    # Кнопка проверки
    buttons.append(
        [
            InlineKeyboardButton(
                text="✅ Проверить подписку", callback_data="check_subscription"
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_payment_keyboard(
    price_1_month: int, price_6_months: int
) -> InlineKeyboardMarkup:
    """Клавиатура с выбором тарифа для оплаты"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⭐ Купить 1 месяц ({price_1_month}₽)",
                    callback_data="buy_1_month",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⭐⭐ Купить 6 месяцев ({price_6_months}₽)",
                    callback_data="buy_6_months",
                )
            ],
        ]
    )


# ============ АДМИНСКИЕ КЛАВИАТУРЫ ============


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню для админа"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📥 Получить VPN"),
                KeyboardButton(text="🎁 Пригласить друга"),
            ],
            [KeyboardButton(text="🔑 Мой конфиг")],
            [KeyboardButton(text="📖 Инструкция"), KeyboardButton(text="❓ Помощь")],
            [KeyboardButton(text="⚙️ Админ панель")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    """Админ панель"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить канал")],
            [KeyboardButton(text="📋 Список каналов")],
            [KeyboardButton(text="🔔 Уведомить о новых каналах")],
            [KeyboardButton(text="🖥️ Управление серверами")],
            [KeyboardButton(text="🗑️ Удалить пользователя")],
            [
                KeyboardButton(text="💰 Настройки цен"),
                KeyboardButton(text="👥 Управление подписками"),
            ],
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="📣 Создать рекламный пост"),
            ],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить цену 1 мес", callback_data="admin_set_price_1m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить цену 6 мес", callback_data="admin_set_price_6m"
                )
            ],
        ]
    )
    return keyboard


def get_user_manage_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """Клавиатура управления подпиской пользователя"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить дни",
                    callback_data=f"admin_add_days_{telegram_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➖ Отнять дни",
                    callback_data=f"admin_remove_days_{telegram_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Выключить подписку",
                    callback_data=f"admin_disable_sub_{telegram_id}",
                )
            ],
        ]
    )
    return keyboard


def get_channel_actions_keyboard(
    channel_id: int, is_partner: bool = False
) -> InlineKeyboardMarkup:
    """Действия с каналом (inline кнопки)"""
    partner_text = "❌ Убрать партнёрку" if is_partner else "⭐️ Сделать партнёрским"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=partner_text,
                    callback_data=f"toggle_partner_channel:{channel_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить", callback_data=f"delete_channel:{channel_id}"
                )
            ],
        ]
    )
    return keyboard


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка отмены"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_user_management_keyboard() -> ReplyKeyboardMarkup:
    """Меню управления пользователями"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Найти пользователя")],
            [KeyboardButton(text="🗑️ Удалить пользователя")],  # ← НОВАЯ КНОПКА
            [KeyboardButton(text="🔙 Назад в админ панель")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_server_management_keyboard() -> ReplyKeyboardMarkup:
    """Меню управления серверами"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить сервер")],
            [KeyboardButton(text="📋 Список серверов")],
            [KeyboardButton(text="🔄 Синхронизировать счётчики")],
            [KeyboardButton(text="🔙 Назад в админ панель")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_server_actions_keyboard(server_id: int) -> InlineKeyboardMarkup:
    """Действия с сервером"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать", callback_data=f"edit_server:{server_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить", callback_data=f"delete_server:{server_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Синхронизировать", callback_data=f"sync_server:{server_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Выгрузить пользователей",
                    callback_data=f"export_users:{server_id}",
                )
            ],
        ]
    )
    return keyboard


def get_confirm_delete_server_keyboard(server_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления сервера с пользователями"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ Точно удалить",
                    callback_data=f"confirm_delete_server:{server_id}",
                )
            ],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")],
        ]
    )
    return keyboard
