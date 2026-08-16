import os
import logging
from dotenv import load_dotenv

# загружаем переменные из .env
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# класс со всеми настройками приложения
class Settings:
    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
    TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

    # 3x-ui
    XUI_IP = os.getenv("XUI_IP")
    XUI_HOST = os.getenv("XUI_HOST")
    XUI_USERNAME = os.getenv("XUI_USERNAME")
    XUI_PASSWORD = os.getenv("XUI_PASSWORD")
    XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID"))

    # Platega.io
    PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID")
    PLATEGA_SECRET = os.getenv("PLATEGA_SECRET")
    PLATEGA_API_URL = "https://app.platega.io"
    WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 5050))

    # Cloudflare Turnstile
    TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY")
    TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY")

    # бд
    DATABASE_URL = os.getenv("DATABASE_URL")

    TEST_MODE = False
    CHECK_INTERVAL_MINUTES = 2
    ENABLE_BACKGROUND_CHECKS: bool = True  # Включить/выключить фоновую проверку

    BACKUP_INTERVAL: int = 86400  # 24 часа
    BACKUP_KEEP_COUNT: int = 7  # Хранить 7 последних бэкапов


settings = Settings()
