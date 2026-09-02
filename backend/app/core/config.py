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
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_enabled: bool = True
    auth_csrf_enabled: bool = True
    auth_expose_token_in_body: bool = False

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
    celery_inspect_timeout_seconds: float = 1.5

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
    # 2026-08-27 - default 含矩阵/知识库/预热，阈值低于 sync
    celery_queue_default_warning: int = 30
    celery_queue_default_critical: int = 80
    # 2026-09-02 - backfill 浏览器任务，积压很快就会拖超时
    celery_queue_backfill_warning: int = 10
    celery_queue_backfill_critical: int = 30
    celery_pending_sync_task_warning: int = 80
    celery_pending_sync_task_critical: int = 200

    flower_enabled: bool = True
    flower_port: int = 5555
    flower_basic_auth: str = ""
    flower_url: str = "http://127.0.0.1:5555"

    monitor_webhook_url: str = ""
    monitor_alert_cooldown_seconds: int = 900

    trusted_hosts: list[str] = ["127.0.0.1", "localhost"]
    expose_openapi_in_production: bool = False

    cors_origins: list[str] = []
    molizhishu_base_url: str = "https://business-api.molizhishu.com/api/business/monitor"
    molizhishu_token: str = ""
    molizhishu_callback_url: str = ""
    # 回调鉴权：优先用本字段；为空则解析 molizhishu_callback_url 的 ?token=
    molizhishu_callback_token: str = ""
    molizhishu_timeout_seconds: float = 30.0
    # 2026-08-27 - 本地/试点：非空时仅列出的企业 code 或 id 可向模力提交；其它企业跳过
    molizhishu_submit_tenant_allowlist: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 60.0
    deepseek_sentiment_keyword_enabled: bool = True
    deepseek_report_enabled: bool = True
    deepseek_knowledge_parse_enabled: bool = True
    deepseek_knowledge_auto_parse_on_upload: bool = False
    deepseek_knowledge_parse_max_chars: int = 12000
    deepseek_rank_fallback_enabled: bool = False
    deepseek_rank_parse_max_chars: int = 8000
    # 2026-08-19 - 写路径改 LLM 分类排；规则函数保留。改回 rules 即恢复规则计位
    rank_engine: str = "llm"
    # Stuck "parsing" rows older than this are marked failed by beat sweeper.
    knowledge_parse_timeout_minutes: int = 10

    # 2026-08-31 - 9.9 H5 微信支付（艾迪亚服务号）
    wechat_pay_mch_id: str = ""
    wechat_pay_app_id: str = ""
    wechat_pay_api_v3_key: str = ""
    wechat_pay_cert_key_path: str = ""
    wechat_pay_cert_path: str = ""
    wechat_pay_notify_url: str = ""
    wechat_app_secret: str = ""
    wechat_h5_base_url: str = "https://www.aieokj.com/h5/diagnosis/"
    # 本地联调：跳过微信下单，直接 mock 支付成功
    wechat_pay_dev_mode: bool = False
    wechat_pay_dev_openid: str = "dev-openid-h5-diagnosis"

    # 2026-09-01 - H5 支付宝手机网站支付（艾迪亚 AppID）
    alipay_app_id: str = ""
    alipay_private_key_path: str = ""
    alipay_private_key: str = ""
    alipay_public_key_path: str = ""
    alipay_public_key: str = ""
    alipay_notify_url: str = ""
    alipay_return_url: str = "https://www.aieokj.com/api/v1/alipay/return"
    alipay_quit_url: str = "https://www.aieokj.com/h5/diagnosis/apply"
    alipay_dev_mode: bool = False

    h5_diagnosis_enabled: bool = True
    h5_diagnosis_price_fen: int = 990
    h5_diagnosis_schedule_days: int = 3
    # 2026-08-31 - H5 监测次数（优先于 days×3）
    h5_diagnosis_schedule_runs: int = 9
    h5_diagnosis_platforms: str = '["doubao","deepseek"]'
    # 2026-09-01 - H5 结果页短链有效天数；阿里云短信（ready 通知）
    h5_result_token_days: int = 30
    aliyun_sms_enabled: bool = False
    aliyun_sms_access_key_id: str = ""
    aliyun_sms_access_key_secret: str = ""
    aliyun_sms_sign_name: str = ""
    # 模板变量约定 ${brand} ${order}；链接须写死在模板正文（阿里云禁止变量传链）
    aliyun_sms_template_code_h5_ready: str = ""
    aliyun_sms_region_id: str = "cn-hangzhou"
    # 2026-09-01 - H5 落地页「一键体验」观察号（不暴露密码）
    h5_observer_demo_login_enabled: bool = True

    # 补录自截图目录（空=backend/storage/backfill_screenshots；生产经软链落 /data/geo/storage）
    backfill_screenshot_dir: str = ""

    # 快照补录通知规则（系统配置菜单 · 通知规则 可改）
    snapshot_backfill_weak_rank_after: int = 3
    snapshot_backfill_notify_owner: bool = True
    snapshot_backfill_notify_operation: bool = True
    snapshot_backfill_notify_admin: bool = True
    # 平台可用性/上下架通知：职位 ID JSON 列表，如 [1,2,3]
    platform_service_notify_position_ids: str = "[]"
    # 客户服务即将到期：提前 N 天；职位 ID JSON，空列表=不推送
    tenant_expiry_notify_days: int = 7
    tenant_expiry_notify_position_ids: str = "[]"

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

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return str(self.app_env or "").lower() in {"production", "prod"}

    @property
    def allow_credentials_with_wildcard_cors(self) -> bool:
        origins = self.cors_origins or []
        return "*" in origins

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
