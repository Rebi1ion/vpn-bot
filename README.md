# VPN Bot

Telegram-бот и веб-сервис для выдачи VLESS-конфигураций через 3x-ui.
Проект также содержит веб-триал, оплату через Platega.io и API v1 для мобильного клиента.

## Возможности

- Telegram-бот с пробной подпиской и платными тарифами.
- Создание и отключение VLESS-конфигураций через 3x-ui.
- Автоматический контроль подписок, серверов и истёкших триалов.
- Веб-страница с выдачей часового триала.
- Webhook оплаты Platega.io.
- REST API v1 для мобильного приложения.
- SQLite или другая БД SQLAlchemy через `DATABASE_URL`.

## Требования

- Python 3.10 или новее.
- Telegram-бот и значения `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`.
- Доступная панель 3x-ui с настроенным inbound.
- Доступ к Platega.io для платных тарифов.
- Домен и HTTPS для внешнего webhook, если бот запускается не только локально.

## Установка

### Windows PowerShell

```powershell
git clone <URL_РЕПОЗИТОРИЯ>
cd vpn-bot
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requierments.txt
Copy-Item .env.example .env
notepad .env
```

Если PowerShell запрещает запуск скриптов активации, можно запускать команды напрямую:

```powershell
.\venv\Scripts\python.exe -m pip install -r requierments.txt
.\venv\Scripts\python.exe main.py
```

### Linux

```bash
git clone <URL_РЕПОЗИТОРИЯ>
cd vpn-bot
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requierments.txt
cp .env.example .env
nano .env
```

## Настройка `.env`

Перед запуском заполните `.env` реальными значениями:

| Переменная | Назначение |
| --- | --- |
| `BOT_TOKEN` | Токен Telegram-бота от BotFather |
| `ADMIN_USER_ID` | Telegram ID администратора |
| `TELEGRAM_API_ID` | API ID Telegram-приложения |
| `TELEGRAM_API_HASH` | API Hash Telegram-приложения |
| `XUI_IP` | IP сервера 3x-ui |
| `XUI_HOST` | URL панели 3x-ui, например `https://host:2053` |
| `XUI_USERNAME` | Логин панели 3x-ui |
| `XUI_PASSWORD` | Пароль панели 3x-ui |
| `XUI_INBOUND_ID` | ID inbound в 3x-ui |
| `DATABASE_URL` | URL базы, по умолчанию SQLite-файл `vpn_bot.db` |
| `PLATEGA_MERCHANT_ID` | Merchant ID в Platega.io |
| `PLATEGA_SECRET` | Секрет webhook Platega.io |
| `WEBHOOK_PORT` | Локальный порт веб-сервера, по умолчанию `5050` |
| `TURNSTILE_SITE_KEY` | Публичный ключ Cloudflare Turnstile |
| `TURNSTILE_SECRET_KEY` | Секретный ключ Cloudflare Turnstile |

## Первый запуск

Запустите бота из корня проекта:

```powershell
python main.py
```

При старте приложение:

1. Создаёт необходимые таблицы в БД.
2. Добавляет сервер из `.env`, если в БД ещё нет серверов.
3. Запускает фоновые проверки подписок и серверов.
4. Запускает Telegram polling.
5. Запускает веб-сервис на `0.0.0.0:<WEBHOOK_PORT>`.

Остановка — `Ctrl+C`.

## Веб-адреса

При локальном запуске доступны:

- `GET /` — веб-страница триала.
- `POST /api/trial` — выдача веб-триала.
- `POST /api/trial/check` — проверка веб-триала.
- `POST /platega/callback` — callback оплаты.
- `GET /api/v1/status` — статус подписки мобильного клиента.
- `GET /robots.txt` и `GET /sitemap.xml` — SEO-файлы.

Локальная проверка страницы: `http://127.0.0.1:5050/`.

Для Platega.io настройте внешний HTTPS-адрес callback:

```text
https://<ВАШ_ДОМЕН>/platega/callback
```

## Структура проекта

- `main.py` — точка входа.
- `telegram_bot/` — пользовательские и административные handlers.
- `web_server.py` — веб-страница, веб-триал и callback оплаты.
- `api/` — REST API v1.
- `database/` — модели и операции с БД.
- `xui_api/` — работа с 3x-ui.
- `background/` — фоновые задачи.
- `backup/` — резервное копирование БД из административного меню.
- `images/` — изображения веб-инструкции.

## Диагностика

Если приложение не запускается:

1. Проверьте, что `.env` находится в корне проекта.
2. Проверьте числовые значения `ADMIN_USER_ID`, `TELEGRAM_API_ID` и `XUI_INBOUND_ID`.
3. Проверьте доступность 3x-ui и правильность `XUI_HOST`.
4. Убедитесь, что порт `WEBHOOK_PORT` свободен.
5. Проверьте, что зависимости установлены в активированное виртуальное окружение.

Логи создаются в `logs/bot.log` во время работы приложения.
