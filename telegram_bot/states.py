from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    """Состояния админа"""
    waiting_for_channel_username = State()
    waiting_for_invite_link = State()      # ← НОВОЕ состояние
    waiting_for_channel_name = State()

class ChannelStates(StatesGroup):
    """Состояния для добавления канала"""
    waiting_for_channel = State()


class ServerStates(StatesGroup):
    """Состояния для управления серверами"""
    waiting_for_name = State()
    waiting_for_ip = State()
    waiting_for_host = State()
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_inbound_id = State()
    
    # Для редактирования
    editing_field = State()

class UserManagementStates(StatesGroup):
    """Состояния для управления пользователями"""
    waiting_for_username = State()
    waiting_for_delete_username = State()  # ← ДОБАВЬ
    waiting_for_telegram_id = State()
    waiting_for_add_days = State()
    waiting_for_remove_days = State()

class AdminSettingsStates(StatesGroup):
    """Состояния для изменения настроек"""
    waiting_for_price_1m = State()
    waiting_for_price_6m = State()
