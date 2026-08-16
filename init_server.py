import asyncio
from database import AsyncSessionLocal
from database.server_operations import add_server, get_all_servers
from config.settings import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate_env_server():
    """
    Автоматически добавить сервер из .env в БД.
    Запускается один раз при первом запуске бота.
    """
    async with AsyncSessionLocal() as session:
        # Проверяем есть ли уже серверы в БД
        servers = await get_all_servers(session)
        
        if servers:
            logger.info(f"✅ Серверы уже в БД: {len(servers)} шт.")
            return
        
        # Если серверов нет — добавляем из .env
        logger.info("🔄 Серверов нет. Добавляю из .env...")
        
        try:
            # Извлекаем IP из HOST
            # Например: https://123.45.67.89:2053 → 123.45.67.89
            host = settings.XUI_HOST
            
            if "://" in host:
                ip = host.split("://")[1].split(":")[0]
            else:
                ip = host.split(":")[0]
            
            server = await add_server(
                session=session,
                name="Server 1 (Main)",
                ip=ip,
                host=settings.XUI_HOST,
                username=settings.XUI_USERNAME,
                password=settings.XUI_PASSWORD,
                inbound_id=1,  # По умолчанию
                max_users=350
                # priority=1  ← УБРАЛИ
            )
            
            logger.info(f"✅ Сервер из .env добавлен в БД: {server.name}")
            logger.info(f"   IP: {server.ip}")
            logger.info(f"   Host: {server.host}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления сервера из .env: {e}")

async def main():
    """Точка входа"""
    await migrate_env_server()
    logger.info("🎉 Инициализация завершена!")

if __name__ == "__main__":
    asyncio.run(main())
