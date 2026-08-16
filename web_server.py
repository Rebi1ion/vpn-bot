import logging
import uuid
from datetime import datetime, timedelta
import aiohttp
from aiohttp import web
from config.settings import settings
from database import AsyncSessionLocal
from database.operations import create_payment, extend_subscription, get_user_config
from sqlalchemy import select, or_
from database.models import User, VpnServer, TrialUser
from database.server_operations import get_optimal_server, increment_server_users
import os

logger = logging.getLogger(__name__)


def get_client_ip(request: web.Request) -> str:
    """Извлекает реальный IP адрес клиента из заголовков."""
    # 1. Cloudflare
    ip = request.headers.get("CF-Connecting-IP")
    if ip:
        return ip
    # 2. X-Real-IP (часто ставит Nginx)
    ip = request.headers.get("X-Real-IP")
    if ip:
        return ip
    # 3. X-Forwarded-For
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Может содержать список IP через запятую: "client_ip, proxy1_ip, proxy2_ip"
        return forwarded_for.split(",")[0].strip()
    
    return request.remote or "unknown"


async def handle_platega_callback(request: web.Request):
    """
    Обработчик callback от Platega.io.
    Принимает POST запрос с JSON:
    {id, amount, currency, status, paymentMethod, payload}
    Заголовки: X-MerchantId, X-Secret
    """
    try:
        # 1. Проверка заголовков авторизации
        merchant_id = request.headers.get("X-MerchantId")
        secret = request.headers.get("X-Secret")

        if not merchant_id or not secret:
            logger.warning("Platega Callback: Отсутствуют заголовки авторизации")
            return web.Response(status=400, text="missing auth headers")

        if merchant_id != settings.PLATEGA_MERCHANT_ID:
            logger.warning(f"Platega Callback: Неверный MerchantId ({merchant_id})")
            return web.Response(status=401, text="wrong merchant_id")

        if secret != settings.PLATEGA_SECRET:
            logger.warning("Platega Callback: Неверный Secret")
            return web.Response(status=401, text="wrong secret")

        # 2. Читаем JSON тело
        data = await request.json()

        transaction_id = data.get("id")
        amount = data.get("amount")
        currency = data.get("currency")
        status_value = data.get("status")
        payment_method = data.get("paymentMethod")
        payload = data.get("payload", "")

        logger.info(
            f"Platega Callback: id={transaction_id}, amount={amount}, status={status_value}, payload={payload}"
        )

        # 3. Обрабатываем только CONFIRMED
        if status_value != "CONFIRMED":
            logger.info(f"Platega Callback: Статус {status_value}, пропускаем")
            return web.json_response({"ok": True})

        # 4. Парсим payload (формат: TGID_MONTHS или app_DBID_MONTHS)
        db_user_id = None
        user_id_tg = None
        try:
            if payload.startswith("app_"):
                # Мобильное приложение: app_{db_user_id}_{months}
                parts = payload.split("_")
                db_user_id = int(parts[1])
                months = int(parts[2])
            else:
                # Telegram-бот: {tg_id}_{months}
                parts = payload.split("_")
                user_id_tg = int(parts[0])
                months = int(parts[1])
        except (IndexError, ValueError):
            logger.error(f"Platega Callback: Неверный формат payload ({payload})")
            return web.json_response({"ok": True})

        # 5. Обрабатываем платеж в БД
        logger.info(
            f"Platega Callback: Успешная оплата {amount} {currency} для "
            f"{'db_id=' + str(db_user_id) if db_user_id else 'tg_id=' + str(user_id_tg)} "
            f"на {months} мес."
        )

        async with AsyncSessionLocal() as session:
            # Находим пользователя
            if db_user_id:
                # Пользователь мобильного приложения — ищем по внутреннему ID
                user = await session.get(User, db_user_id)
                if user:
                    user_id_tg = user.telegram_id  # Может быть None
            else:
                # Пользователь Telegram-бота — ищем по telegram_id
                result = await session.execute(
                    select(User).where(User.telegram_id == user_id_tg)
                )
                user = result.scalar_one_or_none()

            if not user:
                logger.error(
                    f"Platega Callback: Пользователь {'db_id=' + str(db_user_id) if db_user_id else 'tg_id=' + str(user_id_tg)} не найден в БД"
                )
                return web.json_response({"ok": True})

            # Проверяем, не был ли этот платеж уже обработан
            from database.models import Payment

            existing_payment = await session.execute(
                select(Payment).where(
                    Payment.provider_payment_charge_id == str(transaction_id)
                )
            )
            if existing_payment.scalar_one_or_none():
                logger.info(
                    f"Platega Callback: Платеж {transaction_id} уже был обработан. Игнорируем дубликат."
                )
                return web.json_response({"ok": True})

            # Записываем платеж
            await create_payment(
                session=session,
                user_id=user.id,
                amount_stars=int(float(amount)),
                provider_payment_charge_id=str(transaction_id),
                telegram_payment_charge_id=f"platega_{transaction_id}",
                months_added=months,
            )

            # Выдаем подписку
            await extend_subscription(session, user.id, months=months)

            # Включаем конфиг (если был отключен)
            config = await get_user_config(session, user.id)
            if config and not config.is_active:
                if config.server_id is None:
                    # Конфиг был зачищен из-за неактивности, пересоздаем
                    from database.operations import recreate_user_config

                    success = await recreate_user_config(session, user, config)
                    if not success:
                        logger.error(
                            f"Platega Callback: Ошибка пересоздания конфига для {user_id_tg}"
                        )
                else:
                    from database.server_operations import increment_server_users
                    from xui_api.manager import ServerManagerFactory

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
                        success = await server_manager.enable_config(config.email)
                        if success:
                            config.is_active = True
                            await increment_server_users(session, server.id)

            await session.commit()

            # 6. Отправляем сообщение пользователю в Telegram (только если есть telegram_id)
            if user_id_tg:
                try:
                    bot = request.app["bot"]
                    await bot.send_message(
                        chat_id=user_id_tg,
                        text=f"🎉 <b>Оплата успешно получена!</b>\n\n"
                        f"Твоя подписка VPN продлена на <b>{months} мес.</b>\n"
                        f"Нажми <b>«🔑 Мой конфиг»</b>, чтобы проверить статус и получить доступ!",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(
                        f"Platega Callback: Не удалось отправить сообщение {user_id_tg}: {e}"
                    )
            else:
                logger.info(f"Platega Callback: Оплата от app-юзера db_id={user.id}, Telegram-уведомление пропущено")

        return web.json_response({"ok": True})

    except Exception as e:
        logger.error(f"Platega Callback Handler Error: {e}", exc_info=True)
        return web.Response(text="internal error", status=500)


async def handle_index(request: web.Request):
    """Отдача index.html для выдачи триала"""
    file_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="Упс, страница не найдена.", status=404)


async def handle_trial_request(request: web.Request):
    """
    Обработчик POST /api/trial
    Выдает 1-часовой VPN триал после проверки Cloudflare Turnstile и Fingerprint.
    """
    try:
        data = await request.json()
        turnstile_token = data.get("turnstile_token")
        fingerprint = data.get("fingerprint", "unknown")
        ip_address = get_client_ip(request)

        # Логируем заголовки для отладки, если IP локальный
        if ip_address in ["127.0.0.1", "unknown"]:
            logger.info(f"Missing real proxy headers. Headers received: {dict(request.headers)}")
            
        logger.info(f"Trial request from IP: {ip_address}, FP: {fingerprint}")

        if not turnstile_token or not fingerprint:
            return web.json_response(
                {"error": "Отсутствуют необходимые данные."}, status=400
            )

        # 1. Валидация Cloudflare Turnstile
        if (
            settings.TURNSTILE_SECRET_KEY
            and settings.TURNSTILE_SECRET_KEY != "your_secret_key_here"
        ):
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                    data={
                        "secret": settings.TURNSTILE_SECRET_KEY,
                        "response": turnstile_token,
                        "remoteip": ip_address,
                    },
                ) as resp:
                    turnstile_result = await resp.json()
                    if not turnstile_result.get("success"):
                        logger.warning(
                            f"Turnstile failed for IP {ip_address}: {turnstile_result}"
                        )
                        return web.json_response(
                            {"error": "Проверка на бота не пройдена"}, status=403
                        )

        # 2. Проверка анти-абуза в БД (SQLite)
        async with AsyncSessionLocal() as session:
            # Если IP 127.0.0.1, мы НЕ проверяем по IP (иначе все на сервере залочатся на один конфиг первого юзера)
            ip_condition = (TrialUser.ip_address == str(ip_address)) if ip_address not in ["127.0.0.1", "::1", "unknown"] else (TrialUser.id == -1)
            fp_condition = (TrialUser.fingerprint == str(fingerprint)) if fingerprint != "unknown" else (TrialUser.id == -1)

            existing_trial = await session.execute(
                select(TrialUser).where(
                    or_(
                        ip_condition,
                        fp_condition,
                    )
                )
            )
            trial = existing_trial.scalar_one_or_none()
            if trial:
                logger.warning(f"Abuse check failed for IP {ip_address} or FP {fingerprint}. Matched trial ID {trial.id} (IP: {trial.ip_address}, FP: {trial.fingerprint})")
                return web.json_response(
                    {"error": "Вы уже использовали тестовый период"}, status=403
                )

            # 3. Генерация конфига в 3x-ui
            server = await get_optimal_server(session)
            if not server:
                return web.json_response(
                    {"error": "Нет доступных серверов"}, status=503
                )

            from xui_api.manager import ServerManagerFactory

            server_manager = ServerManagerFactory.create_manager(
                server.host, server.username, server.password, server.inbound_id
            )

            email = f"trial_{uuid.uuid4().hex[:8]}"
            config_url = await server_manager.create_config(email)

            if not config_url:
                logger.error(
                    f"Failed to create trial config on server {server.id} for {email}"
                )
                return web.json_response(
                    {"error": "Ошибка генерации профиля на сервере"}, status=500
                )

            # 4. Сохранение в БД
            now = datetime.utcnow()
            expires_at = now + timedelta(hours=1)

            new_trial = TrialUser(
                ip_address=str(ip_address),
                fingerprint=str(fingerprint),
                email=email,
                config_url=config_url,
                created_at=now,
                expires_at=expires_at,
                is_active=True,
            )
            session.add(new_trial)
            await increment_server_users(session, server.id)
            await session.commit()

            return web.json_response({"url": config_url}, status=200)

    except Exception as e:
        logger.error(f"Trial API Error: {e}", exc_info=True)
        return web.json_response({"error": "Внутренняя ошибка сервера"}, status=500)


async def handle_trial_check(request: web.Request):
    """
    Проверяет, есть ли уже активный триал у этого Fingerprint / IP.
    Если есть, возвращает его URL и дату истечения, чтобы восстановить сессию на фронтенде.
    """
    try:
        data = await request.json()
        fingerprint = data.get("fingerprint")
        ip_address = get_client_ip(request)

        if not fingerprint:
            return web.json_response(
                {"error": "Отсутствуют необходимые данные."}, status=400
            )

        now = datetime.utcnow()

        async with AsyncSessionLocal() as session:
            # Восстанавливаем сессию только по нормальному IP или Fingerprint
            ip_condition = (TrialUser.ip_address == str(ip_address)) if ip_address not in ["127.0.0.1", "::1", "unknown"] else (TrialUser.id == -1)
            fp_condition = (TrialUser.fingerprint == str(fingerprint)) if fingerprint != "unknown" else (TrialUser.id == -1)
            
            result = await session.execute(
                select(TrialUser)
                .where(
                    or_(
                        ip_condition,
                        fp_condition,
                    )
                )
                .where(TrialUser.is_active == True)
            )
            existing_trial = result.scalar_one_or_none()

            if existing_trial and existing_trial.expires_at > now:
                # Триал еще жив
                return web.json_response(
                    {
                        "active": True,
                        "url": existing_trial.config_url,
                        "expires_at": existing_trial.expires_at.isoformat() + "Z",
                    },
                    status=200,
                )

            # Нет живого триала
            return web.json_response({"active": False}, status=200)

    except Exception as e:
        logger.error(f"Trial Check API Error: {e}", exc_info=True)
        return web.json_response({"error": "Внутренняя ошибка сервера"}, status=500)


async def handle_robots_txt(request: web.Request):
    """Отдача robots.txt"""
    file_path = os.path.join(os.path.dirname(__file__), "robots.txt")
    if os.path.exists(file_path):
        return web.FileResponse(file_path, headers={"Content-Type": "text/plain; charset=utf-8"})
    return web.Response(text="User-agent: *\nAllow: /\n", content_type="text/plain")


async def handle_sitemap_xml(request: web.Request):
    """Отдача sitemap.xml"""
    file_path = os.path.join(os.path.dirname(__file__), "sitemap.xml")
    if os.path.exists(file_path):
        return web.FileResponse(file_path, headers={"Content-Type": "application/xml; charset=utf-8"})
    return web.Response(text="Not found", status=404)


def create_web_app(bot):
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/platega/callback", handle_platega_callback)

    # API v1 для мобильного приложения
    from api.v1_routes import register_api_routes
    register_api_routes(app)

    # Новые роуты для лендинга
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/trial", handle_trial_request)
    app.router.add_post("/api/trial/check", handle_trial_check)

    # SEO-файлы
    app.router.add_get("/robots.txt", handle_robots_txt)
    app.router.add_get("/sitemap.xml", handle_sitemap_xml)

    # Статика (для картинок, фавикона)
    static_path = os.path.join(os.path.dirname(__file__), "images")
    if os.path.exists(static_path):
        app.router.add_static("/images/", path=static_path, name="images")

    return app
