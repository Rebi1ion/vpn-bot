"""
JWT утилиты для аутентификации мобильного приложения.
Используется PyJWT для создания и валидации токенов.
"""

import jwt
import time
import logging
from config.settings import settings

logger = logging.getLogger(__name__)

# Секретный ключ — из .env (JWT_SECRET) или первые 32 символа PLATEGA_SECRET
JWT_SECRET = getattr(settings, "JWT_SECRET", None) or settings.PLATEGA_SECRET[:32]
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 30 * 24 * 3600  # 30 дней


def create_token(user_id: int) -> str:
    """
    Создать JWT-токен для пользователя.

    Args:
        user_id: Внутренний ID пользователя (users.id)

    Returns:
        Закодированный JWT-токен
    """
    payload = {
        "user_id": user_id,
        "exp": int(time.time()) + JWT_EXPIRE_SECONDS,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.debug(f"JWT создан для user_id={user_id}")
    return token


def decode_token(token: str) -> dict | None:
    """
    Декодировать и проверить JWT-токен.

    Args:
        token: JWT-токен из заголовка Authorization

    Returns:
        Payload словарь или None если токен невалидный/просрочен
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT токен просрочен")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Невалидный JWT: {e}")
        return None
