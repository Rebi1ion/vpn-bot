import time
import logging
from typing import Dict
from functools import wraps
from aiogram import types

logger = logging.getLogger(__name__)


class RateLimiter:
    """Защита от спама"""
    
    def __init__(self):
        self.user_last_request: Dict[int, float] = {}
        self.user_request_count: Dict[int, int] = {}
    
    def check_rate_limit(self, user_id: int, seconds: int = 3) -> bool:
        """
        Проверить частоту запросов.
        
        Args:
            user_id: ID пользователя
            seconds: Минимальный интервал между запросами
        
        Returns:
            True если можно обработать запрос, False если нужно подождать
        """
        current_time = time.time()
        
        if user_id in self.user_last_request:
            time_passed = current_time - self.user_last_request[user_id]
            
            if time_passed < seconds:
                # Слишком быстро
                self.user_request_count[user_id] = self.user_request_count.get(user_id, 0) + 1
                
                if self.user_request_count[user_id] > 5:
                    logger.warning(f"⚠️ Пользователь {user_id} спамит ({self.user_request_count[user_id]} запросов)")
                
                return False
        
        # Обновляем время последнего запроса
        self.user_last_request[user_id] = current_time
        self.user_request_count[user_id] = 0
        return True
    
    def reset(self, user_id: int):
        """Сбросить лимиты для пользователя"""
        self.user_last_request.pop(user_id, None)
        self.user_request_count.pop(user_id, None)


# Глобальный экземпляр
rate_limiter = RateLimiter()


def rate_limit(seconds: int = 3):
    """
    Декоратор для ограничения частоты запросов (для Message).
    
    Args:
        seconds: Минимальный интервал между запросами
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(message: types.Message, *args, **kwargs):
            user_id = message.from_user.id
            
            if not rate_limiter.check_rate_limit(user_id, seconds):
                await message.answer(
                    "⏳ Не торопись! Подожди немного перед следующим запросом."
                )
                return
            
            return await func(message, *args, **kwargs)
        return wrapper
    return decorator


def rate_limit_callback(seconds: int = 3):
    """
    Декоратор для ограничения частоты запросов (для CallbackQuery).
    
    Args:
        seconds: Минимальный интервал между запросами
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(callback: types.CallbackQuery, *args, **kwargs):
            user_id = callback.from_user.id
            
            if not rate_limiter.check_rate_limit(user_id, seconds):
                await callback.answer(
                    "⏳ Подожди немного!",
                    show_alert=True
                )
                return
            
            return await func(callback, *args, **kwargs)
        return wrapper
    return decorator
