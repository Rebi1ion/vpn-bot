from config.settings import settings
from py3xui import AsyncApi, Client
import uuid
import logging
from typing import Optional
import urllib.parse

logger = logging.getLogger(__name__)


class Xui3Manager:
    """Менеджер для работы с 3x-ui (с динамическими параметрами)"""

    FLOW = "xtls-rprx-vision"
    LIMIT_IP = 2

    def __init__(
        self,
        host: str = None,
        username: str = None,
        password: str = None,
        inbound_id: int = None,
    ):
        """
        Инициализация менеджера

        Args:
            host: URL панели 3x-ui (если None — берётся из settings)
            username: Логин (если None — берётся из settings)
            password: Пароль (если None — берётся из settings)
            inbound_id: ID inbound (если None — берётся из settings)
        """
        self.host = host or settings.XUI_HOST
        self.username = username or settings.XUI_USERNAME
        self.password = password or settings.XUI_PASSWORD
        self.inbound_id = inbound_id or settings.XUI_INBOUND_ID

        self.api = AsyncApi(
            host=self.host,
            username=self.username,
            password=self.password,
            use_tls_verify=False,
        )

        self._is_authenticated = False

    async def authenticate(self) -> bool:
        """Аутентификация в 3x-ui"""
        if self._is_authenticated:
            return True

        try:
            await self.api.login()
            self._is_authenticated = True
            logger.info("Подключение к 3x-ui успешно")
            return True
        except Exception as e:
            logger.error(f"Ошибка аутентификации 3x-ui: {e}")
            return False

    async def create_config(self, email: str) -> Optional[str]:
        """Создание конфигурации VLESS"""
        if not await self.authenticate():
            return None

        try:
            client_id = str(uuid.uuid4())
            new_client = Client(
                id=client_id,
                email=email,
                enable=True,
                limitIp=self.LIMIT_IP,
                flow=self.FLOW,
            )

            logger.info(f"Создаем конфиг для {email}...")

            await self.api.client.add(
                inbound_id=self.inbound_id,
                clients=[new_client],
            )

            inbound_data = await self.api.inbound.get_by_id(inbound_id=self.inbound_id)
            config_url = self._build_config_url(
                inbound_data=inbound_data, email=email, client_id=client_id
            )

            if config_url:
                logger.info(f"Конфиг для {email} создан")
                return config_url
            else:
                logger.warning(f"Конфиг создан, но url не найден для {email}")
                return None

        except Exception as e:
            logger.error(f"Ошибка создания конфига для {email}: {e}")
            return None

    async def delete_config(self, email: str) -> bool:
        """Удалить конфигурацию по email"""
        if not await self.authenticate():
            return False

        try:
            logger.info(f"Удаляем конфиг {email}")

            inbound_data = await self.api.inbound.get_by_id(inbound_id=self.inbound_id)
            clients = inbound_data.settings.clients
            client_data_inbound = self._get_client_from_inbound(clients, email)

            if not client_data_inbound:
                logger.warning(f"Конфиг для {email} отсутствует")
                return False

            await self.api.client.delete(
                inbound_id=self.inbound_id, client_uuid=client_data_inbound.id
            )
            logger.info(f"Конфиг для {email} удален")
            return True

        except Exception as e:
            logger.error(f"Ошибка удаления конфига {email}: {e}")
            return False

    async def disable_config(self, email: str) -> bool:
        """Отключить конфигурацию"""
        return await self._set_config_state(email=email, enable=False)

    async def enable_config(self, email: str) -> bool:
        """Включить конфигурацию"""
        return await self._set_config_state(email=email, enable=True)

    def _build_config_url(
        self, inbound_data: dict, client_id: str, email: str
    ) -> Optional[str]:
        """Генерация VLESS URL"""
        try:
            # Извлекаем IP из host
            ip = (
                self.host.split("://")[1].split(":")[0]
                if "://" in self.host
                else self.host.split(":")[0]
            )

            url_settings = {
                "protocol": inbound_data.protocol,
                "client_id": client_id,
                "ip": ip,
                "port": inbound_data.port,
                "type": inbound_data.stream_settings.network,
                "security": inbound_data.stream_settings.security,
                "publicKey": inbound_data.stream_settings.reality_settings["settings"][
                    "publicKey"
                ],
                "fp": inbound_data.stream_settings.reality_settings["settings"][
                    "fingerprint"
                ],
                "sni": inbound_data.stream_settings.reality_settings["serverNames"][0],
                "sid": inbound_data.stream_settings.reality_settings["shortIds"][0],
                "spx": urllib.parse.quote(
                    inbound_data.stream_settings.reality_settings["settings"][
                        "spiderX"
                    ],
                    safe="",
                ),
                "flow": self.FLOW,
                "email": f"{inbound_data.remark}-{urllib.parse.quote(email)}",
            }

            return f"{url_settings['protocol']}://{url_settings['client_id']}@{url_settings['ip']}:{url_settings['port']}?type={url_settings['type']}&encryption=none&security={url_settings['security']}&pbk={url_settings['publicKey']}&fp={url_settings['fp']}&sni={url_settings['sni']}&sid={url_settings['sid']}&spx={url_settings['spx']}&flow={url_settings['flow']}#{url_settings['email']}"

        except Exception as e:
            logger.error(f"Ошибка создания URL: {e}")
            return None

    def _get_client_from_inbound(
        self, clients: list[Client], email: str
    ) -> Optional[Client]:
        """Найти клиента по email"""
        for client in clients:
            if client.email == email:
                return client
        return None

    async def _set_config_state(self, email: str, enable: bool) -> bool:
        """Изменить состояние конфигурации"""
        if not await self.authenticate():
            return False

        action = "Включаем" if enable else "Отключаем"

        try:
            logger.info(f"{action} конфиг для {email}")

            inbound_data = await self.api.inbound.get_by_id(inbound_id=self.inbound_id)
            clients = inbound_data.settings.clients
            client_data_inbound = self._get_client_from_inbound(clients, email)
            client_data_api = await self.api.client.get_by_email(email=email)

            if not client_data_inbound:
                logger.warning(f"Конфиг для {email} отсутствует")
                return False

            client_data_api.id = client_data_inbound.id
            client_data_api.enable = enable
            client_data_api.flow = self.FLOW
            client_data_api.limit_ip = self.LIMIT_IP

            await self.api.client.update(
                client_uuid=client_data_inbound.id, client=client_data_api
            )

            status = "включен" if enable else "отключен"
            logger.info(f"Конфиг для {email} {status}")
            return True

        except Exception as e:
            action_error = "включения" if enable else "отключения"
            logger.error(f"Ошибка {action_error} конфига {email}: {e}")
            return False


class ServerManagerFactory:
    """Фабрика для создания менеджеров серверов (с кэшированием)"""

    _cache = {}

    @staticmethod
    def create_manager(
        host: str, username: str, password: str, inbound_id: int = 1
    ) -> Xui3Manager:
        """Создать или получить из кэша менеджер для конкретного сервера"""
        cache_key = f"{host}_{inbound_id}"
        if cache_key not in ServerManagerFactory._cache:
            ServerManagerFactory._cache[cache_key] = Xui3Manager(
                host, username, password, inbound_id
            )
        return ServerManagerFactory._cache[cache_key]
