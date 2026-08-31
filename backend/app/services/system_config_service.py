"""Runtime system configuration backed by sys_config with .env bootstrap."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ops import SystemConfig

ConfigCategory = Literal["secrets", "schedule", "cache_queue", "notification"]
ValueType = Literal["str", "int", "float", "bool"]

# ponytail: 2s 进程缓存；多 worker 最多延迟约 2s 对齐；upgrade=Redis pub/sub 立即失效。
_RUNTIME_CACHE_TTL_SECONDS = 2.0
_runtime_cache: dict[str, tuple[float, Any]] = {}


@dataclass(frozen=True)
class ConfigMeta:
    field: str
    category: ConfigCategory
    label: str
    description: str
    value_type: ValueType
    secret: bool = False


CONFIG_REGISTRY: dict[str, ConfigMeta] = {
    "molizhishu_token": ConfigMeta(
        field="molizhishu_token",
        category="secrets",
        label="监测服务 Token",
        description="GEO 监测任务提交与结果同步",
        value_type="str",
        secret=True,
    ),
    "deepseek_api_key": ConfigMeta(
        field="deepseek_api_key",
        category="secrets",
        label="DeepSeek API Key",
        description="报告撰写、知识库解析、情绪词增强",
        value_type="str",
        secret=True,
    ),
    "deepseek_base_url": ConfigMeta(
        field="deepseek_base_url",
        category="secrets",
        label="DeepSeek API 地址",
        description="默认 https://api.deepseek.com",
        value_type="str",
    ),
    "deepseek_model": ConfigMeta(
        field="deepseek_model",
        category="secrets",
        label="DeepSeek 模型",
        description="默认 deepseek-chat",
        value_type="str",
    ),
    "monitor_webhook_url": ConfigMeta(
        field="monitor_webhook_url",
        category="secrets",
        label="告警 Webhook",
        description="队列/余额异常推送地址，留空则不推送",
        value_type="str",
    ),
    "schedule_tolerance_minutes": ConfigMeta(
        field="schedule_tolerance_minutes",
        category="schedule",
        label="调度容差（分钟）",
        description="监测计划触发允许的时间窗口",
        value_type="int",
    ),
    "molizhishu_submit_rate_per_minute": ConfigMeta(
        field="molizhishu_submit_rate_per_minute",
        category="schedule",
        label="监测提交限速",
        description="每分钟最多提交次数",
        value_type="int",
    ),
    "molizhishu_sync_rate_per_minute": ConfigMeta(
        field="molizhishu_sync_rate_per_minute",
        category="schedule",
        label="监测同步限速",
        description="每分钟最多同步次数",
        value_type="int",
    ),
    "molizhishu_rate_limit_max_wait_seconds": ConfigMeta(
        field="molizhishu_rate_limit_max_wait_seconds",
        category="schedule",
        label="监测限速最大等待",
        description="触发限速时最长等待秒数",
        value_type="float",
    ),
    "celery_scan_submit_max_prompts": ConfigMeta(
        field="celery_scan_submit_max_prompts",
        category="schedule",
        label="单次扫描提交词组数",
        description="定时扫描每次最多提交的监测词组数量",
        value_type="int",
    ),
    "celery_sync_batch_limit": ConfigMeta(
        field="celery_sync_batch_limit",
        category="schedule",
        label="同步批大小",
        description="每轮 Celery 同步任务上限",
        value_type="int",
    ),
    "celery_sync_terminal_grace_hours": ConfigMeta(
        field="celery_sync_terminal_grace_hours",
        category="schedule",
        label="终态任务宽限（小时）",
        description="任务进入终态后继续同步的宽限时间",
        value_type="int",
    ),
    "redis_enabled": ConfigMeta(
        field="redis_enabled",
        category="cache_queue",
        label="启用 Redis",
        description="关闭后部分缓存与分布式锁不可用",
        value_type="bool",
    ),
    "redis_url": ConfigMeta(
        field="redis_url",
        category="cache_queue",
        label="Redis 地址",
        description="缓存与 Celery Broker 可共用实例不同 DB",
        value_type="str",
    ),
    "celery_enabled": ConfigMeta(
        field="celery_enabled",
        category="cache_queue",
        label="启用 Celery",
        description="关闭后定时提交/同步任务不会执行",
        value_type="bool",
    ),
    "celery_broker_url": ConfigMeta(
        field="celery_broker_url",
        category="cache_queue",
        label="Celery Broker",
        description="任务队列 Redis 地址",
        value_type="str",
    ),
    "celery_result_backend": ConfigMeta(
        field="celery_result_backend",
        category="cache_queue",
        label="Celery Result Backend",
        description="任务结果存储地址",
        value_type="str",
    ),
    "celery_queue_submit_warning": ConfigMeta(
        field="celery_queue_submit_warning",
        category="cache_queue",
        label="提交队列预警阈值",
        description="超过后在运营看板显示关注",
        value_type="int",
    ),
    "celery_queue_submit_critical": ConfigMeta(
        field="celery_queue_submit_critical",
        category="cache_queue",
        label="提交队列严重阈值",
        description="超过后在运营看板显示异常",
        value_type="int",
    ),
    "celery_queue_sync_warning": ConfigMeta(
        field="celery_queue_sync_warning",
        category="cache_queue",
        label="同步队列预警阈值",
        description="超过后在运营看板显示关注",
        value_type="int",
    ),
    "celery_queue_sync_critical": ConfigMeta(
        field="celery_queue_sync_critical",
        category="cache_queue",
        label="同步队列严重阈值",
        description="超过后在运营看板显示异常",
        value_type="int",
    ),
    "deepseek_sentiment_keyword_enabled": ConfigMeta(
        field="deepseek_sentiment_keyword_enabled",
        category="secrets",
        label="启用 DeepSeek 情绪词",
        description="品牌情绪词 AI 增强",
        value_type="bool",
    ),
    "deepseek_report_enabled": ConfigMeta(
        field="deepseek_report_enabled",
        category="secrets",
        label="启用 DeepSeek 报告",
        description="报告中心 AI 撰写",
        value_type="bool",
    ),
    "deepseek_knowledge_parse_enabled": ConfigMeta(
        field="deepseek_knowledge_parse_enabled",
        category="secrets",
        label="启用 DeepSeek 知识库解析",
        description="企业知识库结构化预览",
        value_type="bool",
    ),
    "snapshot_backfill_weak_rank_after": ConfigMeta(
        field="snapshot_backfill_weak_rank_after",
        category="notification",
        label="补录弱排名阈值",
        description="展示排名大于该值（默认3，即第4名及更后）计入「待补录」并推通知；Top1–TopN 不算待补录",
        value_type="int",
    ),
    "snapshot_backfill_notify_owner": ConfigMeta(
        field="snapshot_backfill_notify_owner",
        category="notification",
        label="补录通知归属销售",
        description="启用后站内铃铛通知企业归属销售（tenant.owner）或售前创建人；销售仅看名下",
        value_type="bool",
    ),
    "snapshot_backfill_notify_operation": ConfigMeta(
        field="snapshot_backfill_notify_operation",
        category="notification",
        label="补录通知运营",
        description="启用后「运营」职位（非管理员、非销售）可看全部待补录通知",
        value_type="bool",
    ),
    "snapshot_backfill_notify_admin": ConfigMeta(
        field="snapshot_backfill_notify_admin",
        category="notification",
        label="补录通知管理员",
        description="启用后「平台管理员」职位可看全部待补录通知",
        value_type="bool",
    ),
    "platform_service_notify_position_ids": ConfigMeta(
        field="platform_service_notify_position_ids",
        category="notification",
        label="平台服务通知职位",
        description="仅这些平台职位可见上下架/可用性铃铛。不选则默认销售+运营+管理员",
        value_type="str",
    ),
    "tenant_expiry_notify_days": ConfigMeta(
        field="tenant_expiry_notify_days",
        category="notification",
        label="客户即将到期 · 提前天数",
        description="服务结束日在今天起 N 天内（含今天）则推站内通知；默认 7",
        value_type="int",
    ),
    "tenant_expiry_notify_position_ids": ConfigMeta(
        field="tenant_expiry_notify_position_ids",
        category="notification",
        label="客户即将到期 · 通知职位",
        description="勾选的平台职位可见到期铃铛；销售仅收名下企业。不选则不推送",
        value_type="str",
    ),
    "h5_diagnosis_enabled": ConfigMeta(
        field="h5_diagnosis_enabled",
        category="schedule",
        label="H5 付费诊断开关",
        description="关闭后 H5 下单接口返回未开放",
        value_type="bool",
    ),
    "h5_diagnosis_price_fen": ConfigMeta(
        field="h5_diagnosis_price_fen",
        category="schedule",
        label="H5 诊断价格（分）",
        description="默认 990 即 9.9 元",
        value_type="int",
    ),
    "h5_diagnosis_schedule_days": ConfigMeta(
        field="h5_diagnosis_schedule_days",
        category="schedule",
        label="H5 诊断天数（由次数换算）",
        description="后台按监测次数配置，每天最多 3 档；天数=次数÷3，如 6 次=2 天、9 次=3 天",
        value_type="int",
    ),
    "h5_diagnosis_platforms": ConfigMeta(
        field="h5_diagnosis_platforms",
        category="schedule",
        label="H5 诊断平台",
        description='JSON 数组，如 ["doubao","deepseek"]；须在可提交平台目录内',
        value_type="str",
    ),
}


def coerce_config_value(raw: str, value_type: ValueType) -> Any:
    text = str(raw).strip()
    if value_type == "bool":
        lowered = text.lower()
        if lowered in {"1", "true", "yes", "on", "启用", "是"}:
            return True
        if lowered in {"0", "false", "no", "off", "停用", "否"}:
            return False
        raise ValueError("布尔配置请选择 是/否")
    if value_type == "int":
        return int(text)
    if value_type == "float":
        return float(text)
    return text


def invalidate_runtime_config_cache(config_key: str | None = None) -> None:
    if config_key is None:
        _runtime_cache.clear()
        return
    _runtime_cache.pop(config_key, None)


def get_runtime_config(config_key: str, db: Session | None = None) -> Any:
    """Read registry config with short process cache; prefers DB so multi-worker stays consistent."""
    meta = CONFIG_REGISTRY.get(config_key)
    if meta is None:
        raise KeyError(f"unknown config key: {config_key}")

    now = time.monotonic()
    hit = _runtime_cache.get(config_key)
    if hit is not None and now - hit[0] < _RUNTIME_CACHE_TTL_SECONDS:
        return hit[1]

    close_db = False
    session = db
    if session is None:
        from app.core.database import SessionLocal

        session = SessionLocal()
        close_db = True
    try:
        row = session.scalar(
            select(SystemConfig).where(
                SystemConfig.config_key == config_key,
                SystemConfig.status.is_(True),
            )
        )
        if row is not None and str(getattr(row, "config_value", None) or "").strip() != "":
            try:
                value = coerce_config_value(row.config_value, meta.value_type)
            except ValueError:
                value = getattr(settings, meta.field)
        else:
            value = getattr(settings, meta.field)
        object.__setattr__(settings, meta.field, value)
        _runtime_cache[config_key] = (now, value)
        return value
    finally:
        if close_db and session is not None:
            session.close()


def apply_config_value_to_settings(config_key: str, raw_value: str) -> None:
    meta = CONFIG_REGISTRY.get(config_key)
    if meta is None:
        return
    coerced = coerce_config_value(raw_value, meta.value_type)
    object.__setattr__(settings, meta.field, coerced)
    invalidate_runtime_config_cache(config_key)


def apply_all_configs_from_db(db: Session) -> int:
    rows = db.scalars(select(SystemConfig).where(SystemConfig.status.is_(True))).all()
    applied = 0
    for row in rows:
        if row.config_key not in CONFIG_REGISTRY:
            continue
        try:
            apply_config_value_to_settings(row.config_key, row.config_value)
            applied += 1
        except ValueError:
            continue
    return applied


def sync_registry_from_env(db: Session, *, overwrite: bool = False) -> int:
    """Persist current .env/runtime settings into sys_config."""
    bootstrap_system_configs(db)
    updated = 0
    for key, meta in CONFIG_REGISTRY.items():
        row = db.scalar(select(SystemConfig).where(SystemConfig.config_key == key))
        if row is None:
            continue
        serialized = _serialize_env_value(getattr(settings, meta.field, ""))
        should_write = overwrite or not str(row.config_value or "").strip()
        if not should_write:
            continue
        if row.config_value != serialized or row.scope != meta.category or row.description != meta.description:
            row.config_value = serialized
            row.scope = meta.category
            row.description = meta.description
            updated += 1
    if updated:
        db.commit()
    return updated


def bootstrap_system_configs(db: Session) -> None:
    """Ensure registry keys exist; seed empty rows from current .env values."""
    existing = {
        row.config_key: row
        for row in db.scalars(select(SystemConfig).where(SystemConfig.config_key.in_(CONFIG_REGISTRY.keys()))).all()
    }
    changed = False
    # 兼容旧 key：snapshot_backfill_notify_ops → operation / admin 双开关
    legacy_ops = db.scalar(
        select(SystemConfig).where(SystemConfig.config_key == "snapshot_backfill_notify_ops")
    )
    if legacy_ops is not None:
        legacy_value = str(legacy_ops.config_value or "true").strip() or "true"
        for key in ("snapshot_backfill_notify_operation", "snapshot_backfill_notify_admin"):
            if key in existing:
                continue
            meta = CONFIG_REGISTRY[key]
            row = SystemConfig(
                config_key=key,
                config_value=legacy_value,
                scope=meta.category,
                description=meta.description,
                status=True,
            )
            db.add(row)
            existing[key] = row
            changed = True
        if legacy_ops.status:
            legacy_ops.status = False
            changed = True
    for key, meta in CONFIG_REGISTRY.items():
        env_value = getattr(settings, meta.field, "")
        serialized = _serialize_env_value(env_value)
        row = existing.get(key)
        if row is None:
            db.add(
                SystemConfig(
                    config_key=key,
                    config_value=serialized,
                    scope=meta.category,
                    description=meta.description,
                    status=True,
                )
            )
            changed = True
            continue
        if not str(row.config_value or "").strip() and serialized:
            row.config_value = serialized
            row.scope = meta.category
            row.description = meta.description
            changed = True
    if changed:
        db.commit()


def _serialize_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def mask_secret_value(raw: str | None) -> str:
    text = str(raw or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}****{text[-2:]}"


def serialize_config_row(row: SystemConfig, *, reveal_secrets: bool = False) -> dict[str, Any]:
    meta = CONFIG_REGISTRY.get(row.config_key)
    is_secret = bool(meta.secret if meta else False)
    raw_value = row.config_value
    display_value = raw_value if (reveal_secrets or not is_secret) else mask_secret_value(raw_value)
    return {
        "id": row.id,
        "config_key": row.config_key,
        "config_name": meta.label if meta else row.config_key,
        "config_value": display_value,
        "category": meta.category if meta else row.scope,
        "scope": meta.category if meta else row.scope,
        "value_type": meta.value_type if meta else "str",
        "secret": is_secret,
        "status": "启用" if row.status else "停用",
        "remark": meta.description if meta else row.description,
        "updated_at": row.updated_at.isoformat(sep=" ", timespec="minutes"),
        "updated_by": row.updated_by,
    }


def list_system_configs(db: Session, category: str | None = None) -> list[dict[str, Any]]:
    bootstrap_system_configs(db)
    apply_all_configs_from_db(db)
    rows = db.scalars(select(SystemConfig).where(SystemConfig.config_key.in_(CONFIG_REGISTRY.keys())).order_by(SystemConfig.id.asc())).all()
    data = [serialize_config_row(row) for row in rows]
    if category:
        data = [item for item in data if item["category"] == category]
    return data


def update_system_config(db: Session, config_id: int, raw_value: str, *, updated_by: str | None = None) -> dict[str, Any]:
    config = db.scalar(select(SystemConfig).where(SystemConfig.id == config_id))
    if config is None:
        raise ValueError("配置项不存在")
    meta = CONFIG_REGISTRY.get(config.config_key)
    if meta is None:
        raise ValueError("该配置项不可在线修改")
    value = str(raw_value).strip()
    if not value:
        raise ValueError("配置值不能为空")
    coerce_config_value(value, meta.value_type)
    config.config_value = value
    if updated_by:
        config.updated_by = updated_by
    apply_config_value_to_settings(config.config_key, value)
    db.flush()
    return serialize_config_row(config)


def bootstrap_and_apply(db: Session) -> None:
    bootstrap_system_configs(db)
    apply_all_configs_from_db(db)
    invalidate_runtime_config_cache()
