"""生产环境启动校验与安全辅助。"""

from __future__ import annotations

import logging
import re

from app.core.config import settings

logger = logging.getLogger(__name__)

_FLOWER_AUTH_PATTERN = re.compile(r"^[^:\s]+:.+")


def validate_flower_auth(*, strict: bool = False) -> None:
    """Flower 生产环境必须配置 basic_auth；开发环境缺失时仅告警。"""
    if not settings.flower_enabled:
        return
    auth = settings.flower_basic_auth.strip()
    if auth and not _FLOWER_AUTH_PATTERN.match(auth):
        raise RuntimeError("FLOWER_BASIC_AUTH 格式应为 user:password")
    if auth:
        return
    message = "Flower 已启用但未配置 FLOWER_BASIC_AUTH，禁止暴露到公网"
    if settings.is_production or strict:
        raise RuntimeError(f"生产环境：{message}")
    logger.warning(message)


_INSECURE_SECRET_KEYS = frozenset({"change-me", "secret", "dev", "test", ""})


def validate_security_baseline() -> None:
    """启动时校验 CORS / 调试开关等安全基线。"""
    if settings.is_production and settings.secret_key.strip().lower() in _INSECURE_SECRET_KEYS:
        raise RuntimeError("生产环境必须配置安全的 SECRET_KEY")
    if settings.is_production and len(settings.secret_key.strip()) < 32:
        logger.warning("生产环境 SECRET_KEY 长度建议不少于 32 字符")
    if settings.allow_credentials_with_wildcard_cors:
        raise RuntimeError("CORS 不允许 allow_credentials=True 与 origins=* 同时配置")
    if settings.is_production and settings.debug:
        logger.warning("生产环境 APP_ENV=production 但 DEBUG=true，建议关闭 debug")
    if settings.is_production and not settings.cors_origins:
        logger.warning("生产环境 cors_origins 为空，跨域请求将被拒绝")
    if settings.is_production and settings.trusted_hosts == ["127.0.0.1", "localhost"]:
        logger.warning("生产环境 trusted_hosts 仍为默认值，请配置真实域名")
    validate_flower_auth()


def openapi_enabled() -> bool:
    return not settings.is_production or settings.expose_openapi_in_production
