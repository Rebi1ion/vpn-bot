from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config.settings import settings

# Создаём движок базы данных
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

# Фабрика сессий
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Импортируем Base из models
from database.models import Base

# Экспортируем всё необходимое
__all__ = ['engine', 'AsyncSessionLocal', 'Base']
