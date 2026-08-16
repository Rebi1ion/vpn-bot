import logging
from typing import Optional
from aiogram import Bot

logger = logging.getLogger(__name__)


class SubscriptionChecker:
    """Проверка подписок пользователей на каналы через Bot API"""
    
    def __init__(self, bot: Bot):
        """
        Инициализация чекера.
        
        Args:
            bot: Экземпляр aiogram Bot
        """
        self.bot = bot
        self._is_started = False
    
    async def start(self):
        """Запустить (заглушка для совместимости)"""
        self._is_started = True
        logger.info("✅ Subscription checker готов (Bot API)")
    
    async def stop(self):
        """Остановить (заглушка для совместимости)"""
        self._is_started = False
        logger.info("⏹️ Subscription checker остановлен")
    
    async def is_user_subscribed(
        self,
        user_id: int,
        channel_identifier: str | int
    ) -> Optional[bool]:
        """
        Проверить подписан ли пользователь на канал через Bot API.
        
        ТРЕБОВАНИЕ: Бот должен быть админом в канале.
        
        Args:
            user_id: Telegram ID пользователя
            channel_identifier: Username канала, ссылка или Chat ID (int)
        
        Returns:
            True - подписан, False - не подписан, None - ошибка
        """
        try:
            # Извлекаем username/chat_id
            channel = self._extract_username(channel_identifier)
            
            logger.info(f"🔍 Проверка: user={user_id}, channel={channel} (type={type(channel).__name__})")
            
            # Используем Bot API для проверки
            try:
                member = await self.bot.get_chat_member(
                    chat_id=channel,  # Теперь может быть int или str
                    user_id=user_id
                )
                
                logger.info(f"📊 Статус пользователя: {member.status}")
                
                # Проверяем статус пользователя
                if member.status in ['member', 'administrator', 'creator']:
                    logger.info(f"✅ Пользователь {user_id} ПОДПИСАН на канал {channel}")
                    return True
                elif member.status == 'left':
                    logger.info(f"❌ Пользователь {user_id} НЕ ПОДПИСАН (вышел из канала)")
                    return False
                elif member.status == 'kicked':
                    logger.info(f"❌ Пользователь {user_id} забанен в канале")
                    return False
                else:
                    logger.info(f"❌ Пользователь {user_id} НЕ ПОДПИСАН (статус: {member.status})")
                    return False
                    
            except Exception as e:
                error_str = str(e)
                logger.error(f"❌ Ошибка API: {error_str}")
                
                # Пользователь не найден = не подписан
                if "user not found" in error_str.lower() or "chat not found" in error_str.lower():
                    logger.info(f"❌ Канал/пользователь не найден")
                    return False
                
                # Бот не админ
                if "bot is not a member" in error_str.lower() or "forbidden" in error_str.lower():
                    logger.error(
                        f"⚠️ Бот НЕ является админом в канале {channel}\n"
                        f"   Решение: Добавь бота админом в этот канал"
                    )
                    return None
                
                raise
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка проверки подписки: {e}", exc_info=True)
            return None

    
    async def check_multiple_channels(
        self,
        user_id: int,
        channel_identifiers: list[str]
    ) -> dict[str, Optional[bool]]:
        """Проверить подписку на несколько каналов"""
        results = {}
        
        for channel_identifier in channel_identifiers:
            result = await self.is_user_subscribed(user_id, channel_identifier)
            results[channel_identifier] = result
        
        return results
    
    def _extract_username(self, channel_identifier: str | int) -> str | int:
        """
        Извлечь username из ссылки или преобразовать Chat ID в int.
        
        Args:
            channel_identifier: Ссылка, username или Chat ID
        
        Returns:
            Username канала для Bot API (str) или Chat ID (int)
        """
        # Если уже int (Chat ID) — возвращаем как есть
        if isinstance(channel_identifier, int):
            return channel_identifier
        
        channel_identifier = str(channel_identifier).strip()
        
        # ===== ПРИВАТНЫЙ КАНАЛ: Chat ID (начинается с -) =====
        if channel_identifier.startswith('-'):
            try:
                # Преобразуем в int для правильной работы Bot API
                chat_id = int(channel_identifier)
                logger.info(f"🔑 Приватный канал: Chat ID = {chat_id}")
                return chat_id
            except ValueError:
                logger.error(f"❌ Неверный формат Chat ID: {channel_identifier}")
                return channel_identifier
        
        # ===== ПРИВАТНАЯ INVITE-ССЫЛКА =====
        if '/+' in channel_identifier or 'joinchat/' in channel_identifier:
            logger.warning(f"⚠️ Приватные каналы по invite ссылке не поддерживаются через Bot API")
            return channel_identifier
        
        # ===== ПУБЛИЧНАЯ ССЫЛКА =====
        if 't.me/' in channel_identifier or 'telegram.me/' in channel_identifier:
            if 't.me/' in channel_identifier:
                parts = channel_identifier.split('t.me/')
            else:
                parts = channel_identifier.split('telegram.me/')
            
            if len(parts) == 2:
                username = parts[1].split('?')[0].strip('/')
                # Добавляем @ если нет
                if not username.startswith('@'):
                    username = f'@{username}'
                return username
        
        # ===== ПУБЛИЧНЫЙ USERNAME =====
        if not channel_identifier.startswith('@'):
            channel_identifier = f'@{channel_identifier}'
        
        return channel_identifier


