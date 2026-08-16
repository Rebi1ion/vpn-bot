"""
REST API v1 для мобильного приложения (Flutter / Hiddify-app форк).

Эндпоинты:
  POST /api/v1/auth/device   — регистрация / авторизация по Device ID
  GET  /api/v1/config        — получить VLESS конфиг (или 403 если подписка истекла)
  GET  /api/v1/status        — статус подписки и конфига
  POST /api/v1/payment/create — создать платёж Platega → redirect_url
"""

import logging
from datetime import datetime
from aiohttp import web
from sqlalchemy import select
import aiohttp as aiohttp_client

from database import AsyncSessionLocal
from database.models import User, VpnConfig, VpnServer
from database.operations import (
    get_user_config,
    create_vpn_config,
    extend_subscription,
    get_setting,
)
from database.server_operations import get_optimal_server, increment_server_users
from api.jwt_utils import create_token, decode_token
from config.settings import settings

logger = logging.getLogger(__name__)


# ═══════════════════ ХЕЛПЕРЫ ═══════════════════


async def get_user_from_request(request: web.Request) -> User | None:
    """
    Извлечь пользователя из JWT-токена в заголовке Authorization.

    Args:
        request: aiohttp запрос

    Returns:
        User или None если токен невалидный
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None

    token = auth[7:]
    payload = decode_token(token)
    if not payload:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return user


# ═══════════════════ POST /api/v1/auth/device ═══════════════════


async def handle_auth_device(request: web.Request):
    """
    Авторизация по Device ID.

    Body: { "device_id": "uuid-устройства" }

    Если device_id нет в БД → создаёт юзера + 7-дневный триал.
    Всегда возвращает JWT-токен и статус подписки.
    """
    try:
        data = await request.json()
        device_id = data.get("device_id", "").strip()

        if not device_id or len(device_id) < 8:
            return web.json_response(
                {"error": "device_id обязателен (мин. 8 символов)"}, status=400
            )

        async with AsyncSessionLocal() as session:
            # Ищем по device_id
            result = await session.execute(
                select(User).where(User.device_id == device_id)
            )
            user = result.scalar_one_or_none()
            created = False

            if not user:
                # Создаём нового пользователя (без telegram_id)
                user = User(
                    device_id=device_id,
                    telegram_id=None,
                    username=None,
                    first_name=f"app_{device_id[:8]}",
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                created = True

                # Выдаём 7-дневный триал
                user = await extend_subscription(session, user.id, days=7)
                logger.info(
                    f"📱 Новое устройство {device_id[:8]}... зарегистрировано, триал 7 дней"
                )

            # Генерируем JWT
            token = create_token(user.id)

            # Текущий статус подписки
            now = datetime.utcnow()
            is_active = (
                user.subscription_end_date is not None
                and user.subscription_end_date > now
            )

            return web.json_response(
                {
                    "token": token,
                    "created": created,
                    "subscription": {
                        "is_active": is_active,
                        "end_date": (
                            user.subscription_end_date.isoformat() + "Z"
                            if user.subscription_end_date
                            else None
                        ),
                    },
                }
            )

    except Exception as e:
        logger.error(f"Auth Device Error: {e}", exc_info=True)
        return web.json_response({"error": "Внутренняя ошибка сервера"}, status=500)


# ═══════════════════ GET /api/v1/config ═══════════════════


async def handle_get_config(request: web.Request):
    """
    Получить VLESS конфигурацию.

    Headers: Authorization: Bearer <JWT>

    200 → { config_url, is_active, subscription_end }
    403 → { error: "expired" }  — подписка истекла
    401 → { error: "unauthorized" }
    503 → { error: "server_unavailable" }
    """
    user = await get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    now = datetime.utcnow()

    # Проверка подписки
    if not user.subscription_end_date or user.subscription_end_date <= now:
        return web.json_response(
            {
                "error": "expired",
                "message": "Подписка истекла",
                "expired_at": (
                    user.subscription_end_date.isoformat() + "Z"
                    if user.subscription_end_date
                    else None
                ),
            },
            status=403,
        )

    async with AsyncSessionLocal() as session:
        # Обновляем user из свежей сессии
        user = await session.get(User, user.id)
        config = await get_user_config(session, user.id)

        # Конфиг есть и активен
        if config and config.is_active and config.config_url:
            return web.json_response(
                {
                    "config_url": config.config_url,
                    "is_active": True,
                    "subscription_end": user.subscription_end_date.isoformat() + "Z",
                }
            )

        # Конфиг есть, но деактивирован
        if config and not config.is_active:
            if config.server_id is None or not config.config_url:
                # Конфиг был зачищен — пересоздаём
                from database.operations import recreate_user_config

                success = await recreate_user_config(session, user, config)
                if success:
                    return web.json_response(
                        {
                            "config_url": config.config_url,
                            "is_active": True,
                            "subscription_end": user.subscription_end_date.isoformat()
                            + "Z",
                        }
                    )
                else:
                    return web.json_response(
                        {"error": "server_unavailable"}, status=503
                    )
            else:
                # Включаем существующий конфиг на сервере
                result = await session.execute(
                    select(VpnServer).where(VpnServer.id == config.server_id)
                )
                server = result.scalar_one_or_none()
                if server:
                    from xui_api.manager import ServerManagerFactory

                    manager = ServerManagerFactory.create_manager(
                        server.host,
                        server.username,
                        server.password,
                        server.inbound_id,
                    )
                    success = await manager.enable_config(config.email)
                    if success:
                        config.is_active = True
                        await increment_server_users(session, server.id)
                        await session.commit()
                        return web.json_response(
                            {
                                "config_url": config.config_url,
                                "is_active": True,
                                "subscription_end": user.subscription_end_date.isoformat()
                                + "Z",
                            }
                        )

                return web.json_response(
                    {"error": "server_unavailable"}, status=503
                )

        # Конфига вообще нет → создаём новый
        server = await get_optimal_server(session)
        if not server:
            return web.json_response({"error": "server_unavailable"}, status=503)

        from xui_api.manager import ServerManagerFactory

        device_id = user.device_id or f"app_{user.id}"
        email = f"app_{device_id[:16]}_{user.id}"
        manager = ServerManagerFactory.create_manager(
            server.host, server.username, server.password, server.inbound_id
        )
        config_url = await manager.create_config(email)

        if not config_url:
            return web.json_response(
                {"error": "config_creation_failed"}, status=500
            )

        config = await create_vpn_config(
            session,
            user_id=user.id,
            server_id=server.id,
            email=email,
            config_url=config_url,
        )
        await increment_server_users(session, server.id)

        logger.info(f"📱 Создан VPN конфиг для app-юзера {user.id}")

        return web.json_response(
            {
                "config_url": config_url,
                "is_active": True,
                "subscription_end": user.subscription_end_date.isoformat() + "Z",
            }
        )


# ═══════════════════ GET /api/v1/status ═══════════════════


async def handle_status(request: web.Request):
    """
    Статус подписки и конфига.

    Headers: Authorization: Bearer <JWT>
    """
    user = await get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    now = datetime.utcnow()
    is_active = (
        user.subscription_end_date is not None and user.subscription_end_date > now
    )

    async with AsyncSessionLocal() as session:
        config = await get_user_config(session, user.id)

    return web.json_response(
        {
            "subscription": {
                "is_active": is_active,
                "end_date": (
                    user.subscription_end_date.isoformat() + "Z"
                    if user.subscription_end_date
                    else None
                ),
            },
            "config": {
                "exists": config is not None,
                "is_active": config.is_active if config else False,
            },
        }
    )


# ═══════════════════ POST /api/v1/payment/create ═══════════════════


async def handle_create_payment(request: web.Request):
    """
    Создать платёж через Platega.io.

    Body: { "tariff_months": 1|6|12 }

    200 → { redirect_url, amount, months }
    """
    user = await get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        data = await request.json()
        tariff_months = data.get("tariff_months")

        if tariff_months not in (1, 6, 12):
            return web.json_response(
                {"error": "tariff_months должен быть 1, 6 или 12"}, status=400
            )

        # Получаем цену из БД
        async with AsyncSessionLocal() as session:
            price_map = {
                1: await get_setting(session, "price_1_month_rub", 150),
                6: await get_setting(session, "price_6_months_rub", 700),
                12: await get_setting(session, "price_12_months_rub", 1200),
            }

        amount = price_map[tariff_months]

        # Payload для Platega callback: app_{db_user_id}_{months}
        payload = f"app_{user.id}_{tariff_months}"

        async with aiohttp_client.ClientSession() as http_session:
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
                    "description": f"VPN подписка на {tariff_months} мес.",
                    "payload": payload,
                },
            )

            if resp.status != 200:
                error_text = await resp.text()
                logger.error(
                    f"Platega API error (app): {resp.status} - {error_text}"
                )
                return web.json_response(
                    {"error": "payment_creation_failed"}, status=502
                )

            result = await resp.json()

        redirect_url = result.get("redirect")
        if not redirect_url:
            logger.error(f"Platega API: нет redirect в ответе: {result}")
            return web.json_response({"error": "no_redirect_url"}, status=502)

        return web.json_response(
            {
                "redirect_url": redirect_url,
                "amount": amount,
                "months": tariff_months,
            }
        )

    except Exception as e:
        logger.error(f"App Payment Error: {e}", exc_info=True)
        return web.json_response({"error": "Внутренняя ошибка сервера"}, status=500)


# ═══════════════════ РЕГИСТРАЦИЯ РОУТОВ ═══════════════════


def register_api_routes(app: web.Application):
    """Регистрирует все API v1 роуты в aiohttp приложении."""
    app.router.add_post("/api/v1/auth/device", handle_auth_device)
    app.router.add_get("/api/v1/config", handle_get_config)
    app.router.add_get("/api/v1/status", handle_status)
    app.router.add_post("/api/v1/payment/create", handle_create_payment)

    logger.info("📱 API v1 роуты зарегистрированы")
