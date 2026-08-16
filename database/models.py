from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class User(Base):
    """Таблица пользователей"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=True, index=True)
    device_id = Column(String, unique=True, nullable=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Подписка
    subscription_end_date = Column(DateTime, nullable=True)
    is_reminded_3d = Column(Boolean, default=False)

    # Реферальная система
    referred_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Связи
    vpn_config = relationship("VpnConfig", back_populates="user", uselist=False)

    # Рефералы
    referrals = relationship("User", backref="referred_by", remote_side=[id])

    payments = relationship("Payment", back_populates="user")

    channel_subscriptions = relationship(
        "UserChannelSubscription", back_populates="user"
    )


class VpnServer(Base):
    """Модель VPN сервера"""

    __tablename__ = "vpn_servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    ip = Column(String, nullable=False)
    host = Column(String, nullable=False)
    username = Column(String, nullable=False)
    password = Column(String, nullable=False)
    inbound_id = Column(Integer, nullable=False)
    max_users = Column(Integer, default=100)
    current_users = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    configs = relationship("VpnConfig", back_populates="server")


class VpnConfig(Base):
    """Модель VPN конфига"""

    __tablename__ = "vpn_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    server_id = Column(Integer, ForeignKey("vpn_servers.id"), nullable=True)
    email = Column(String, unique=True, nullable=False)
    config_url = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="vpn_config")
    server = relationship("VpnServer", back_populates="configs")


class Channel(Base):
    """Модель канала для подписки"""

    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_username = Column(String, unique=True, nullable=False)
    channel_url = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    order = Column(Integer, default=0)  # Порядок выдачи
    is_active = Column(Boolean, default=True)
    is_partner_channel = Column(Boolean, default=False)  # Дает неделю бесплатного VPN
    notified_users = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user_subscriptions = relationship(
        "UserChannelSubscription", back_populates="channel"
    )


class UserChannelSubscription(Base):
    """Связь пользователя с каналом"""

    __tablename__ = "user_channel_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)

    is_subscribed = Column(Boolean, default=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)  # Когда выдан канал
    last_checked_at = Column(DateTime, nullable=True)  # Последняя проверка подписки

    user = relationship("User", back_populates="channel_subscriptions")
    channel = relationship("Channel", back_populates="user_subscriptions")


class Payment(Base):
    """Модель платежей (Telegram Stars)"""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount_stars = Column(Integer, nullable=False)
    provider_payment_charge_id = Column(String, nullable=False, unique=True)
    telegram_payment_charge_id = Column(String, nullable=False, unique=True)
    months_added = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payments")


class BotSettings(Base):
    """Глобальные настройки бота (цены и т.д.)"""

    __tablename__ = "bot_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value_str = Column(String, nullable=True)
    value_int = Column(Integer, nullable=True)
    description = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrialUser(Base):
    """Модель пользователей, получивших бесплатный VPN на 1 час (Web Landing)"""

    __tablename__ = "trial_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String, nullable=False)
    fingerprint = Column(
        String, unique=True, nullable=False, index=True
    )  # Защита от создания нескольких триалов с 1 устройства
    email = Column(String, unique=True, nullable=False)  # ID клиента в X-UI
    config_url = Column(String, nullable=False)  # Ссылка для пользователя
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
