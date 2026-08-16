import asyncio
import shutil
import glob
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BackupManager:
    """Управление резервными копиями БД"""
    
    def __init__(self, db_path: str = 'vpn_bot.db', backup_dir: str = 'backups'):
        self.db_path = db_path
        self.backup_dir = backup_dir
        
        # Создай папку если нет
        os.makedirs(backup_dir, exist_ok=True)
    
    async def create_backup(self) -> bool:
        """
        Создать резервную копию БД.
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            if not os.path.exists(self.db_path):
                logger.warning(f"⚠️ БД не найдена: {self.db_path}")
                return False
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(self.backup_dir, f"vpn_bot_{timestamp}.db")
            
            # Копируй БД
            await asyncio.to_thread(shutil.copy2, self.db_path, backup_file)
            
            file_size = os.path.getsize(backup_file) / 1024 / 1024  # MB
            logger.info(f"✅ Бэкап создан: {backup_file} ({file_size:.2f} MB)")
            
            # Удали старые бэкапы
            self.cleanup_old_backups()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания бэкапа: {e}", exc_info=True)
            return False
    
    def cleanup_old_backups(self, keep_count: int = 7):
        """
        Удалить старые бэкапы, оставив только последние N.
        
        Args:
            keep_count: Количество бэкапов которое нужно оставить
        """
        try:
            # Получи все бэкапы
            pattern = os.path.join(self.backup_dir, 'vpn_bot_*.db')
            backups = sorted(glob.glob(pattern), reverse=True)
            
            # Удали старые
            for old_backup in backups[keep_count:]:
                os.remove(old_backup)
                logger.info(f"🗑️ Удалён старый бэкап: {os.path.basename(old_backup)}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка очистки бэкапов: {e}")
    
    def get_backup_info(self) -> dict:
        """Получить информацию о бэкапах"""
        try:
            pattern = os.path.join(self.backup_dir, 'vpn_bot_*.db')
            backups = sorted(glob.glob(pattern), reverse=True)
            
            total_size = sum(os.path.getsize(f) for f in backups)
            
            return {
                'count': len(backups),
                'total_size_mb': total_size / 1024 / 1024,
                'latest': os.path.basename(backups[0]) if backups else None
            }
        except Exception as e:
            logger.error(f"Ошибка получения инфо о бэкапах: {e}")
            return {'count': 0, 'total_size_mb': 0, 'latest': None}


# Глобальный экземпляр
backup_manager = BackupManager()
