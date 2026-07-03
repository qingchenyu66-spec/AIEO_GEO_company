from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GEO Monitor API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str
    access_token_expire_minutes: int = 480
    identity_ticket_expire_minutes: int = 30

    database_host: str = "127.0.0.1"
    database_port: int = 3306
    database_user: str
    database_password: str
    database_name: str

    redis_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = 2.0
    redis_key_prefix: str = "geo_monitor"
    redis_default_ttl_seconds: int = 60
    redis_scheduler_lock_ttl_seconds: int = 1800

    celery_enabled: bool = True
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"
    celery_submit_rate_limit: str = "10/m"
    celery_sync_rate_limit: str = "30/m"
    celery_scan_submit_max_prompts: int = 50
    celery_sync_batch_limit: int = 500
    celery_sync_terminal_grace_hours: int = 24

    schedule_tolerance_minutes: int = 60
    molizhishu_submit_rate_per_minute: int = 30
    molizhishu_sync_rate_per_minute: int = 60
    molizhishu_rate_limit_max_wait_seconds: float = 120.0
    http_login_rate_per_minute: int = 15
    http_overview_rate_per_minute: int = 30
    rate_limit_local_fallback_ratio: float = 0.5

    database_pool_size: int = 20
    database_max_overflow: int = 40

    celery_queue_submit_warning: int = 50
    celery_queue_submit_critical: int = 150
    celery_queue_sync_warning: int = 100
    celery_queue_sync_critical: int = 300

    flower_enabled: bool = True
    flower_port: int = 5555
    flower_basic_auth: str = ""
    flower_url: str = "http://127.0.0.1:5555"

    monitor_webhook_url: str = ""
    monitor_alert_cooldown_seconds: int = 900

    cors_origins: list[str] = []
    molizhishu_base_url: str = "https://business-api.molizhishu.com/api/business/monitor"
    molizhishu_token: str = ""
    molizhishu_callback_url: str = ""
    molizhishu_timeout_seconds: float = 30.0

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 60.0
    deepseek_sentiment_keyword_enabled: bool = True
    deepseek_report_enabled: bool = True
    deepseek_knowledge_parse_enabled: bool = True
    deepseek_knowledge_auto_parse_on_upload: bool = True
    deepseek_knowledge_parse_max_chars: int = 12000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def database_url(self) -> str:
        password = quote_plus(self.database_password)
        return (
            f"mysql+pymysql://{self.database_user}:{password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
            "?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
