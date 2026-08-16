import asyncio
import logging
import platform
from logging.handlers import RotatingFileHandler
from aiogram import Dispatcher, Bot
from aiogram.types import ErrorEvent
from config.settings import settings
from telegram_bot import user_handlers, admin_handlers
from checker.subscription import SubscriptionChecker
from background.scheduler import BackgroundScheduler
import os
from aiohttp import web
from web_server import create_web_app

# Создай папки для логов и бэкапов
os.makedirs("logs", exist_ok=True)
os.makedirs("backups", exist_ok=True)

# Настройка логирования
log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = RotatingFileHandler(
    "logs/bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])

logger = logging.getLogger(__name__)


class GlobalErrorHandler:
    """Глобальный обработчик ошибок"""

    @staticmethod
    async def handle_error(event: ErrorEvent):
        """Обработать ошибку"""
        logger.error(f"Критическая ошибка: {event.exception}", exc_info=event.exception)


async def shutdown(bot: Bot, dp: Dispatcher, scheduler: BackgroundScheduler):
    """Корректное завершение работы бота"""
    logger.info("⏹️ Начинаю остановку бота...")

    try:
        if hasattr(bot, "webhook_runner"):
            await bot.webhook_runner.cleanup()
            logger.info("✅ Webhook сервер остановлен")
        await scheduler.stop()
        logger.info("✅ Планировщик остановлен")

        await dp.stop_polling()
        logger.info("✅ Polling остановлен")

        await bot.session.close()
        logger.info("✅ Сессия бота закрыта")

    except Exception as e:
        logger.error(f"❌ Ошибка при остановке: {e}")

    logger.info("🛑 Бот полностью остановлен")


async def main():
    """Главная функция бота"""

    logger.info("=" * 60)
    logger.info("🚀 Запуск VPN бота...")
    logger.info(f"📟 Платформа: {platform.system()} {platform.release()}")
    logger.info("=" * 60)

    # ============ ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ БД ============
    try:
        from database import engine, Base
        from database.operations import initialize_default_settings
        from database import AsyncSessionLocal

        logger.info("🔄 Проверка структуры БД...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            from sqlalchemy import text

            try:
                await conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN is_reminded_3d BOOLEAN DEFAULT 0;"
                    )
                )
            except Exception:
                pass
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE channels ADD COLUMN notified_users BOOLEAN DEFAULT 0;"
                    )
                )
            except Exception:
                pass
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN device_id VARCHAR UNIQUE;"
                    )
                )
            except Exception:
                pass

        async with AsyncSessionLocal() as session:
            await initialize_default_settings(session)

        from init_server import migrate_env_server

        logger.info("🔄 Проверяю серверы в БД...")
        await migrate_env_server()
    except Exception as e:
        logger.error(f"⚠️ Ошибка инициализации БД или серверов: {e}")

    # Инициализация бота
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()

    # Глобальный обработчик ошибок
    dp.error.register(GlobalErrorHandler.handle_error)

    # Подключаем роутеры
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    # Инициализируем checker
    user_handlers.subscription_checker = SubscriptionChecker(bot)
    await user_handlers.subscription_checker.start()

    # Инициализируем планировщик
    scheduler = BackgroundScheduler(bot, user_handlers.subscription_checker)
    await scheduler.start()

    # Запускаем Webhook сервер
    app = create_web_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.WEBHOOK_PORT)
    await site.start()
    bot.webhook_runner = runner
    logger.info(f"🌐 Webhook сервер запущен на порту {settings.WEBHOOK_PORT}")

    # Event для graceful shutdown
    shutdown_event = asyncio.Event()

    # Обработка сигналов остановки (работает на Linux/macOS)
    if platform.system() != "Windows":
        import signal

        def signal_handler():
            logger.warning("🛑 Получен сигнал остановки")
            shutdown_event.set()

        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)

        logger.info("✅ Обработчики сигналов зарегистрированы")
    else:
        logger.info(
            "ℹ️ Windows: сигналы не поддерживаются, используй Ctrl+C для остановки"
        )

    logger.info("🤖 Бот запущен и готов к работе!")
    logger.info("=" * 60)

    try:
        polling_task = asyncio.create_task(dp.start_polling(bot))

        if platform.system() != "Windows":
            shutdown_task = asyncio.create_task(shutdown_event.wait())

            done, pending = await asyncio.wait(
                [polling_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        else:
            await polling_task

    except KeyboardInterrupt:
        logger.info("⌨️ Прервано пользователем (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        await shutdown(bot, dp, scheduler)


if __name__ == "__main__":
    try:
        if platform.system() == "Windows":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Выход")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}", exc_info=True)
