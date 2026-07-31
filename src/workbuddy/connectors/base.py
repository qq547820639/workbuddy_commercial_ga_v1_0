from __future__ import annotations

import jwt
from abc import ABC, abstractmethod
from cryptography.fernet import Fernet

from workbuddy.settings import Settings, settings


class BaseMailConnector(ABC):
    """邮件连接器抽象基类，提供 OAuth 与凭证通用逻辑模板。

    子类必须实现 normalize_message（各渠道消息归一化差异点）。
    """

    def __init__(self, cfg: Settings = settings):
        self.cfg = cfg
        self.cipher = Fernet(cfg.fernet_key)

    def decode_state(self, state: str) -> dict:
        """解码 OAuth state（两者实现完全相同）。"""
        return jwt.decode(state, self.cfg.app_secret, algorithms=["HS256"])

    @property
    @abstractmethod
    def configured(self) -> bool:
        """各渠道凭证配置检查。"""
        ...

    @abstractmethod
    def authorization_url(self, tenant_id: str, user_id: str, enable_send: bool = False) -> str:
        """生成 OAuth 授权 URL。"""
        ...

    @abstractmethod
    def exchange_code(self, code: str) -> dict:
        """用授权码换取 token。"""
        ...

    @abstractmethod
    def normalize_message(self, raw: dict) -> dict:
        """将渠道原始消息归一化为统一格式。"""
        ...
