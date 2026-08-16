from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from database.models import VpnServer, VpnConfig
import logging

logger = logging.getLogger(__name__)


async def get_optimal_server(session: AsyncSession) -> VpnServer:
    """Получить оптимальный сервер для нового пользователя"""
    result = await session.execute(
        select(VpnServer)
        .where(VpnServer.is_active == True)
        .where(VpnServer.current_users < VpnServer.max_users)
        .order_by(VpnServer.current_users.asc())
    )

    server = result.scalars().first()

    if not server:
        logger.error("❌ Нет доступных серверов!")
        return None

    logger.info(
        f"✅ Выбран сервер: {server.name} ({server.current_users}/{server.max_users})"
    )
    return server


async def get_server_by_id(session: AsyncSession, server_id: int) -> VpnServer:
    """Получить сервер по ID"""
    result = await session.execute(select(VpnServer).where(VpnServer.id == server_id))
    return result.scalars().first()


async def get_all_servers(session: AsyncSession) -> list:
    """Получить список всех серверов"""
    result = await session.execute(select(VpnServer))
    return result.scalars().all()


async def add_server(
    session: AsyncSession,
    name: str,
    ip: str,
    host: str,
    username: str,
    password: str,
    inbound_id: int,
    max_users: int = 100,
    # priority: int = 1  ← УБЕРИ ЕСЛИ ЕСТЬ
) -> VpnServer:
    """Добавить новый сервер"""
    server = VpnServer(
        name=name,
        ip=ip,
        host=host,
        username=username,
        password=password,
        inbound_id=inbound_id,
        max_users=max_users,
        current_users=0,
        is_active=True,
        # priority=priority  ← УБЕРИ ЕСЛИ ЕСТЬ
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


async def update_server(
    session: AsyncSession,
    server_id: int,
    name: str = None,
    ip: str = None,
    host: str = None,
    username: str = None,
    password: str = None,
    inbound_id: int = None,
    max_users: int = None,
    # priority: int = None,
    is_active: bool = None,
) -> bool:
    """Обновить данные сервера"""
    server = await get_server_by_id(session, server_id)

    if not server:
        return False

    if name is not None:
        server.name = name
    if ip is not None:
        server.ip = ip
    if host is not None:
        server.host = host
    if username is not None:
        server.username = username
    if password is not None:
        server.password = password
    if inbound_id is not None:
        server.inbound_id = inbound_id
    if max_users is not None:
        server.max_users = max_users
    # if priority is not None:
    #     server.priority = priority
    if is_active is not None:
        server.is_active = is_active

    await session.commit()
    logger.info(f"✅ Сервер {server.name} обновлён")
    return True


async def delete_server(
    session: AsyncSession, server_id: int, force: bool = False
) -> bool:
    """Удалить сервер"""
    server = await get_server_by_id(session, server_id)

    if not server:
        return False

    # Проверяем есть ли пользователи на этом сервере
    result = await session.execute(
        select(func.count(VpnConfig.id)).where(VpnConfig.server_id == server_id)
    )
    user_count = result.scalar()

    if user_count > 0 and not force:
        logger.warning(f"⚠️ На сервере {server.name} есть {user_count} пользователей")
        return False

    if user_count > 0 and force:
        logger.warning(
            f"⚠️ FORCE: Удаление {user_count} конфигов с сервера {server.name}"
        )
        from sqlalchemy import delete

        await session.execute(delete(VpnConfig).where(VpnConfig.server_id == server_id))

    await session.delete(server)
    await session.commit()

    logger.info(f"✅ Сервер {server.name} удалён")
    return True


async def increment_server_users(session: AsyncSession, server_id: int):
    """Увеличить счётчик пользователей"""
    await session.execute(
        update(VpnServer)
        .where(VpnServer.id == server_id)
        .values(current_users=VpnServer.current_users + 1)
    )
    await session.commit()


async def decrement_server_users(session: AsyncSession, server_id: int):
    """Уменьшить счётчик пользователей"""
    await session.execute(
        update(VpnServer)
        .where(VpnServer.id == server_id)
        .where(VpnServer.current_users > 0)
        .values(current_users=VpnServer.current_users - 1)
    )
    await session.commit()


async def sync_server_count(session: AsyncSession, server_id: int):
    """Синхронизировать счётчик с реальным количеством"""
    result = await session.execute(
        select(func.count(VpnConfig.id))
        .where(VpnConfig.server_id == server_id)
        .where(VpnConfig.is_active == True)
    )

    actual_count = result.scalar()

    await session.execute(
        update(VpnServer)
        .where(VpnServer.id == server_id)
        .values(current_users=actual_count)
    )
    await session.commit()

    logger.info(
        f"🔄 Синхронизирован счётчик сервера #{server_id}: {actual_count} пользователей"
    )
