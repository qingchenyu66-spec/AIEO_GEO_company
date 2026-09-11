"""站内系统通知：创建、列表、已读。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, Select, and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.notification import SystemNotification, SystemNotificationRead

logger = logging.getLogger(__name__)

NOTIFICATION_RETENTION_DAYS = 30

CUSTOMER_RESTRICTED_CATEGORIES = ("report_published",)
PLATFORM_RESTRICTED_CATEGORIES = (
    "operation_approval",
    "operation_approval_result",
    "celery_queue",
    "snapshot_backfill",
    "platform_service",
    "tenant_expiry",
    # 2026-09-11 - 转托管销售通知须按 owner_user_id 过滤，禁止全平台串客户
    "credit_billing_mode",
)


def can_view_notification_category(
    category: str,
    *,
    can_review_approvals: bool,
    can_view_ops_alerts: bool,
    can_view_snapshot_backfill: bool,
    can_view_customer_reports: bool = False,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> bool | None:
    """通知分类是否可见；None 表示需结合 payload 中的用户 ID 判断。"""
    if category == "operation_approval":
        return can_review_approvals
    if category == "operation_approval_result":
        return None
    if category == "celery_queue":
        return can_view_ops_alerts
    if category == "snapshot_backfill":
        if not can_view_snapshot_backfill:
            return False
        # 2026-07-28 - 补录通知可见性 - 销售看名下；运营看无人认领+自己名下；均需读 payload
        return None
    if category == "report_published":
        return can_view_customer_reports
    if category == "platform_service":
        return can_view_platform_service
    if category == "tenant_expiry":
        if not can_view_tenant_expiry:
            return False
        # 销售需按 owner_user_id 过滤；其他已勾职位看全部（含无归属）
        return None if tenant_expiry_owner_only else True
    # 2026-09-08 - 算力类通知原先落 unknown→False，客户看不到三日不足/拦截提醒
    if category in {
        "credit_runway",
        "credit_submit_block",
        "credit_platform_block",
        "credit_billing_mode",
        "credit_balance_capped",
        "credit_terms",
    }:
        return True
    return False


def _delete_notification(db: Session, row: SystemNotification, *, auto_commit: bool = True) -> None:
    db.execute(
        delete(SystemNotificationRead).where(SystemNotificationRead.notification_id == row.id)
    )
    db.delete(row)
    if auto_commit:
        db.commit()


def _notification_query_for_user(
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
) -> Select[tuple[SystemNotification]]:
    audience = "PLATFORM" if identity_type == "PLATFORM" else "CUSTOMER"
    stmt = select(SystemNotification).where(SystemNotification.audience_type == audience)
    if audience == "CUSTOMER":
        stmt = stmt.where(SystemNotification.tenant_id == tenant_id)
    else:
        stmt = stmt.where(SystemNotification.tenant_id.is_(None))
    read_exists = (
        select(SystemNotificationRead.id)
        .where(
            SystemNotificationRead.notification_id == SystemNotification.id,
            SystemNotificationRead.user_id == user_id,
        )
        .exists()
    )
    return stmt


def _owner_user_id_expr():
    return func.cast(
        func.json_unquote(func.json_extract(SystemNotification.payload_json, "$.owner_user_id")),
        Integer,
    )


def _payload_owner_user_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("owner_user_id")
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _snapshot_backfill_visible_to_user(
    payload: dict[str, Any],
    *,
    user_id: int,
    owner_only: bool,
) -> bool:
    """销售只看自己客户；运营看无人认领 + 自己名下。"""
    owner_id = _payload_owner_user_id(payload)
    if owner_id is not None:
        return owner_id == user_id
    return not owner_only


def _short_backfill_scope(scope: str) -> str:
    text = str(scope or "").strip() or "监测任务"
    for suffix in ("控股集团有限公司", "股份有限公司", "有限责任公司", "有限公司", "集团"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            return text[: -len(suffix)]
    return text


def _compose_batch_backfill_copy(
    *,
    scope: str,
    period: str,
    entries: list[dict[str, Any]],
    owner_user_id: int | None,
) -> tuple[str, str, dict[str, int]]:
    """标题/正文/平台计数。A+B：公司×具体场次时刻一条。"""
    platform_counts: dict[str, int] = {}
    platform_labels: dict[str, str] = {}
    for item in entries:
        code = str(item.get("platform") or "unknown").strip() or "unknown"
        label = str(item.get("platform_label") or code).strip() or code
        platform_counts[code] = platform_counts.get(code, 0) + 1
        platform_labels[code] = label
    parts = [
        f"{platform_labels[code]}{platform_counts[code]}"
        for code, _n in sorted(platform_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    breakdown = " · ".join(parts)
    short_scope = _short_backfill_scope(scope)
    count = len(entries)
    # 2026-07-28 - 标题写公司短名 - 「你的客户」扫铃铛分不清是哪家
    if short_scope and short_scope != "监测任务":
        title = f"待补录 · {short_scope}"
    elif owner_user_id:
        title = "待补录 · 你的客户"
    else:
        title = "待补录 · 无人认领"
    if breakdown:
        message = f"{short_scope} · {period} · 待补录{count}条（{breakdown}）"
    else:
        message = f"{short_scope} · {period} · 待补录{count}条"
    return title, message[:500], platform_counts


def _apply_notification_visibility_filter(
    stmt: Select[tuple[SystemNotification]],
    *,
    user_id: int,
    can_review_approvals: bool,
    can_view_ops_alerts: bool,
    can_view_snapshot_backfill: bool,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> Select[tuple[SystemNotification]]:
    """按角色过滤通知：审批、运维告警、补录待办、平台可用性、客户到期分别鉴权。"""
    clauses = [SystemNotification.category.not_in(PLATFORM_RESTRICTED_CATEGORIES)]
    if can_review_approvals:
        clauses.append(SystemNotification.category == "operation_approval")
    requester_id_expr = func.cast(
        func.json_unquote(func.json_extract(SystemNotification.payload_json, "$.requester_user_id")),
        Integer,
    )
    clauses.append(
        and_(
            SystemNotification.category == "operation_approval_result",
            requester_id_expr == user_id,
        )
    )
    if can_view_ops_alerts:
        clauses.append(SystemNotification.category == "celery_queue")
    if can_view_snapshot_backfill:
        owner_expr = _owner_user_id_expr()
        if snapshot_backfill_owner_only:
            # 销售：仅自己的客户
            clauses.append(
                and_(
                    SystemNotification.category == "snapshot_backfill",
                    owner_expr == user_id,
                )
            )
        else:
            # 2026-07-28 - 运营不再收 99+ 全量 - 无人认领或自己名下
            clauses.append(
                and_(
                    SystemNotification.category == "snapshot_backfill",
                    or_(owner_expr.is_(None), owner_expr == user_id),
                )
            )
    if can_view_platform_service:
        clauses.append(SystemNotification.category == "platform_service")
    if can_view_tenant_expiry:
        owner_expr = _owner_user_id_expr()
        if tenant_expiry_owner_only:
            # 2026-07-31 - 到期通知销售精细化 - 仅名下企业，无归属不推销售
            clauses.append(
                and_(
                    SystemNotification.category == "tenant_expiry",
                    owner_expr == user_id,
                )
            )
        else:
            clauses.append(SystemNotification.category == "tenant_expiry")
    # 2026-09-11 - 转托管销售铃铛仅负责销售可见（payload.owner_user_id）
    owner_expr = _owner_user_id_expr()
    clauses.append(
        and_(
            SystemNotification.category == "credit_billing_mode",
            owner_expr == user_id,
        )
    )
    return stmt.where(or_(*clauses))


def upsert_platform_service_notification(
    db: Session,
    *,
    event: str,
    title: str,
    message: str,
    payload: dict[str, Any],
    source_key: str,
    level: str = "info",
) -> SystemNotification:
    """平台上下架/可用性铃铛（P2 按职位过滤可见性）。"""
    del event
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = level
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing
    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="platform_service",
        level=level,
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _apply_customer_notification_visibility_filter(
    stmt: Select[tuple[SystemNotification]],
    *,
    can_view_customer_reports: bool,
) -> Select[tuple[SystemNotification]]:
    clauses = [SystemNotification.category.not_in(CUSTOMER_RESTRICTED_CATEGORIES)]
    if can_view_customer_reports:
        clauses.append(SystemNotification.category == "report_published")
    return stmt.where(or_(*clauses))


def _notification_retention_cutoff() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=NOTIFICATION_RETENTION_DAYS)


def _user_can_read_notification(
    row: SystemNotification,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool,
    can_view_ops_alerts: bool,
    can_view_snapshot_backfill: bool,
    can_view_customer_reports: bool,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> bool:
    if row.created_at < _notification_retention_cutoff():
        return False
    if identity_type == "CUSTOMER":
        if row.audience_type != "CUSTOMER" or row.tenant_id != tenant_id:
            return False
        allowed = can_view_notification_category(
            row.category,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=False,
            can_view_customer_reports=can_view_customer_reports,
        )
        return allowed is True

    if row.audience_type != "PLATFORM" or row.tenant_id is not None:
        return False
    if row.category == "operation_approval_result":
        if not row.payload_json:
            return False
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            return False
        return int(payload.get("requester_user_id") or 0) == user_id
    if row.category == "snapshot_backfill":
        allowed = can_view_notification_category(
            row.category,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
            snapshot_backfill_owner_only=snapshot_backfill_owner_only,
            can_view_platform_service=can_view_platform_service,
            can_view_tenant_expiry=can_view_tenant_expiry,
            tenant_expiry_owner_only=tenant_expiry_owner_only,
        )
        if allowed is False:
            return False
        if allowed is True:
            return True
        if not row.payload_json:
            return False
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            return False
        return _snapshot_backfill_visible_to_user(
            payload,
            user_id=user_id,
            owner_only=snapshot_backfill_owner_only,
        )
    if row.category == "tenant_expiry":
        allowed = can_view_notification_category(
            row.category,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
            can_view_platform_service=can_view_platform_service,
            can_view_tenant_expiry=can_view_tenant_expiry,
            tenant_expiry_owner_only=tenant_expiry_owner_only,
        )
        if allowed is False:
            return False
        if allowed is True:
            return True
        if not row.payload_json:
            return False
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            return False
        owner_id = _payload_owner_user_id(payload)
        return owner_id is not None and owner_id == user_id
    if row.category == "credit_billing_mode":
        # 平台侧销售通知：仅 owner；客户侧走下方 allowed is True
        if not row.payload_json:
            return False
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            return False
        owner_id = _payload_owner_user_id(payload)
        return owner_id is not None and owner_id == user_id
    allowed = can_view_notification_category(
        row.category,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
        snapshot_backfill_owner_only=snapshot_backfill_owner_only,
        can_view_platform_service=can_view_platform_service,
        can_view_tenant_expiry=can_view_tenant_expiry,
        tenant_expiry_owner_only=tenant_expiry_owner_only,
    )
    return allowed is True


def upsert_tenant_expiry_notification(
    db: Session,
    *,
    tenant_id: int,
    title: str,
    message: str,
    payload: dict[str, Any],
    level: str = "warning",
    auto_commit: bool = True,
) -> SystemNotification:
    """客户即将到期铃铛（按企业一条，销售靠 owner_user_id 过滤）。"""
    source_key = f"tenant_expiry:{tenant_id}"
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = level
        existing.category = "tenant_expiry"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        if auto_commit:
            db.commit()
            db.refresh(existing)
        return existing
    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="tenant_expiry",
        level=level,
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    if auto_commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def resolve_tenant_expiry_notifications(
    db: Session,
    *,
    active_tenant_ids: set[int],
    auto_commit: bool = True,
) -> int:
    """删除不在窗口内的到期通知。"""
    rows = list(
        db.scalars(
            select(SystemNotification).where(
                SystemNotification.audience_type == "PLATFORM",
                SystemNotification.category == "tenant_expiry",
                SystemNotification.tenant_id.is_(None),
            )
        )
    )
    cleared = 0
    for row in rows:
        tenant_id = None
        if row.payload_json:
            try:
                tenant_id = int(json.loads(row.payload_json).get("tenant_id") or 0) or None
            except (json.JSONDecodeError, TypeError, ValueError):
                tenant_id = None
        if tenant_id is None and row.source_key.startswith("tenant_expiry:"):
            try:
                tenant_id = int(row.source_key.split(":", 1)[1])
            except (TypeError, ValueError):
                tenant_id = None
        if tenant_id is not None and tenant_id in active_tenant_ids:
            continue
        _delete_notification(db, row, auto_commit=False)
        cleared += 1
    if auto_commit and cleared:
        db.commit()
    return cleared


def upsert_credit_block_notification(
    db: Session,
    *,
    tenant,
    block_reason: str,
    window_key: str,
) -> SystemNotification | None:
    """算力/平台余额拦截通知。"""
    from app.models.tenant import Tenant as TenantModel

    if not isinstance(tenant, TenantModel):
        return None
    if block_reason == "tenant_credit":
        source_key = f"credit:block:tenant:{tenant.id}:{window_key}"
        title = "监测未提交：算力不足"
        message = f"企业「{tenant.name}」窗口 {window_key} 因算力不足未提交监测，请充值。"
        audience = "CUSTOMER"
        category = "credit_submit_block"
        level = "warning"
        target_tenant_id = tenant.id
    else:
        source_key = f"credit:block:platform:{window_key}"
        title = "监测未提交：平台账户余额不足"
        message = f"窗口 {window_key} 因监测平台账户余额不足，全平台提交已拦截。"
        audience = "PLATFORM"
        category = "credit_platform_block"
        level = "critical"
        target_tenant_id = None

    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == audience,
        )
    )
    payload = json.dumps(
        {"tenant_id": tenant.id, "block_reason": block_reason, "window_key": window_key},
        ensure_ascii=False,
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.level = level
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        return existing
    row = SystemNotification(
        audience_type=audience,
        tenant_id=target_tenant_id,
        category=category,
        level=level,
        title=title,
        message=message,
        payload_json=payload,
        source_key=source_key,
    )
    db.add(row)
    db.flush()
    return row


def upsert_credit_balance_capped_notification(
    db: Session,
    *,
    tenant,
    window_key: str,
    requested: float,
    charged: float,
) -> SystemNotification | None:
    """结算少收（余额封顶）通知平台运营；同企业同窗去重。"""
    from app.models.tenant import Tenant as TenantModel

    if not isinstance(tenant, TenantModel):
        return None
    source_key = f"credit:balance_capped:{tenant.id}:{window_key}"
    title = "结算少收：余额不足已封顶"
    message = (
        f"企业「{tenant.name}」窗口 {window_key} 应扣 {requested:g}，"
        f"实扣 {charged:g}（余额封顶）。请核对充值与单价。"
    )
    payload = json.dumps(
        {
            "tenant_id": tenant.id,
            "block_reason": "balance_capped",
            "window_key": window_key,
            "requested_credits": requested,
            "charged_credits": charged,
        },
        ensure_ascii=False,
    )
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.level = "warning"
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        return existing
    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="credit_balance_capped",
        level="warning",
        title=title,
        message=message,
        payload_json=payload,
        source_key=source_key,
    )
    db.add(row)
    db.flush()
    return row


def notify_credit_terms_published(db: Session, terms) -> int:
    # 2026-09-08 - 服务条款仅门户查阅，发布不再推系统通知（原「请确认」已退役）
    del db, terms
    return 0


def scan_credit_terms_reminders(db: Session) -> int:
    # 2026-09-08 - 条款不再硬确认，停发生效前提醒
    del db
    return 0


def upsert_credit_three_day_shortfall_notification(
    db: Session,
    *,
    tenant,
    available: float,
    credits_per_day: float,
    need_three_days: float,
) -> SystemNotification | None:
    """可用算力不足以支撑约 3 日预估时通知该企业（按日去重）。"""
    from app.models.tenant import Tenant as TenantModel

    if not isinstance(tenant, TenantModel):
        return None
    today_key = datetime.now().date().isoformat()
    source_key = f"credit:runway3d:{tenant.id}:{today_key}"
    # 2026-09-08 - 客户通知：可用约数 + 约还能撑几天，催及时补充算力
    days_left = (available / credits_per_day) if credits_per_day > 0 else 0.0
    if days_left < 0.1:
        days_text = "已不足 1 天"
    else:
        days_text = f"大约还能支撑 {days_left:.1f} 天"
    title = "算力余量提醒"
    message = (
        f"根据当前监测配置，可用算力约 {available:.0f}，{days_text}（不足 3 天）。"
        f"为避免监测中止，请及时补充算力。"
    )
    payload = json.dumps(
        {
            "tenant_id": tenant.id,
            "available": available,
            "credits_per_day": credits_per_day,
            "need_three_days": need_three_days,
            "days_left": round(days_left, 2),
        },
        ensure_ascii=False,
    )
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "CUSTOMER",
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        return existing
    row = SystemNotification(
        audience_type="CUSTOMER",
        tenant_id=tenant.id,
        category="credit_runway",
        level="warning",
        title=title,
        message=message,
        payload_json=payload,
        source_key=source_key,
    )
    db.add(row)
    db.flush()
    return row


def notify_billing_mode_switched(db: Session, tenant, log, *, operator_name: str | None = None) -> int:
    """G7：模式切换后通知企业管理员。"""
    from app.models.credit import BillingModeChangeLog

    if not isinstance(log, BillingModeChangeLog):
        return 0
    mode_label = "算力自助" if log.to_mode == "credit" else "平台托管"
    title = f"计费模式已切换为{mode_label}"
    op = f"操作人：{operator_name}" if operator_name else "平台运营"
    message = f"企业计费模式已调整为{mode_label}。{op}。原因：{log.reason}"
    source_key = f"credit:billing_mode:{log.id}:tenant:{tenant.id}"
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "CUSTOMER",
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        return 1
    db.add(
        SystemNotification(
            audience_type="CUSTOMER",
            tenant_id=tenant.id,
            category="credit_billing_mode",
            level="info",
            title=title,
            message=message,
            payload_json=json.dumps(
                {"change_log_id": log.id, "from_mode": log.from_mode, "to_mode": log.to_mode},
                ensure_ascii=False,
            ),
            source_key=source_key,
        )
    )
    db.flush()
    return 1


def notify_billing_mode_switched_to_sales(db: Session, tenant, log, *, operator_name: str | None = None) -> int:
    """G7：转托管时通知负责销售（PLATFORM + owner_user_id 过滤）。"""
    from app.models.credit import BillingModeChangeLog

    if not isinstance(log, BillingModeChangeLog) or log.to_mode != "hosted":
        return 0
    owner_id = getattr(tenant, "owner_user_id", None)
    if not owner_id:
        return 0
    mode_label = "平台托管"
    op = f"操作人：{operator_name}" if operator_name else "平台运营"
    title = f"客户已转回托管：{tenant.name}"
    message = f"企业「{tenant.name}」计费模式已调整为{mode_label}。{op}。原因：{log.reason}"
    source_key = f"credit:billing_mode:sales:{log.id}:tenant:{tenant.id}"
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    payload = json.dumps(
        {"change_log_id": log.id, "tenant_id": tenant.id, "owner_user_id": owner_id, "to_mode": log.to_mode},
        ensure_ascii=False,
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        return 1
    db.add(
        SystemNotification(
            audience_type="PLATFORM",
            tenant_id=None,
            category="credit_billing_mode",
            level="info",
            title=title,
            message=message,
            payload_json=payload,
            source_key=source_key,
        )
    )
    db.flush()
    return 1


def upsert_credit_runway_alert(
    db: Session,
    *,
    runway_windows: float | None,
    runway_threshold: int,
    molizhishu_balance: float,
    next_window_yuan: float,
    platform_gate_ok: bool,
) -> SystemNotification | None:
    """B+4：runway 低于阈值或模力余额闸不通过时提醒平台运营。"""
    if platform_gate_ok and (runway_windows is None or runway_windows >= runway_threshold):
        return None
    source_key = "credit:runway:platform_alert"
    if platform_gate_ok:
        title = f"Runway 偏低（{runway_windows:.1f} 窗）"
        message = (
            f"模力账户余额 {molizhishu_balance:.2f} 元，下一窗预估 {next_window_yuan:.2f} 元，"
            f"Runway 约 {runway_windows:.1f} 窗，低于阈值 {runway_threshold} 窗。"
        )
        level = "warning"
    else:
        title = "模力余额不足，全平台提交可能被拦截"
        message = (
            f"模力账户余额 {molizhishu_balance:.2f} 元，下一窗预估 {next_window_yuan:.2f} 元，"
            f"未达 runway×预估+安全垫要求（阈值 {runway_threshold} 窗）。"
        )
        level = "critical"
    payload = json.dumps(
        {
            "runway_windows": runway_windows,
            "runway_threshold": runway_threshold,
            "molizhishu_balance": molizhishu_balance,
            "next_window_yuan": next_window_yuan,
            "platform_gate_ok": platform_gate_ok,
        },
        ensure_ascii=False,
    )
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.level = level
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        return existing
    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="credit_runway",
        level=level,
        title=title,
        message=message,
        payload_json=payload,
        source_key=source_key,
    )
    db.add(row)
    db.flush()
    return row


def upsert_monitor_alert_notification(db: Session, alert: dict[str, Any]) -> SystemNotification | None:
    """将监控告警写入平台运营站内通知（可测试）。"""
    queue = str(alert.get("queue") or "unknown")
    level = str(alert.get("level") or "warning")
    source_key = f"monitor:celery:{queue}:{level}"
    title = str(alert.get("title") or "系统告警")
    message = str(alert.get("message") or "")
    payload = json.dumps(alert, ensure_ascii=False)

    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.level = level
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="celery_queue",
        level=level,
        title=title,
        message=message,
        payload_json=payload,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_stale_monitor_alert_notifications(db: Session, active_alerts: list[dict[str, Any]]) -> int:
    """告警恢复后移除不再触发的 celery_queue 站内通知。"""
    active_keys = {
        f"monitor:celery:{str(alert.get('queue') or 'unknown')}:{str(alert.get('level') or 'warning')}"
        for alert in active_alerts
    }
    rows = list(
        db.scalars(
            select(SystemNotification).where(
                SystemNotification.category == "celery_queue",
                SystemNotification.audience_type == "PLATFORM",
                SystemNotification.tenant_id.is_(None),
            )
        )
    )
    removed = 0
    for row in rows:
        if row.source_key in active_keys:
            continue
        _delete_notification(db, row, auto_commit=False)
        removed += 1
    if removed:
        db.commit()
    return removed


def upsert_report_published_notification(
    db: Session,
    *,
    tenant_id: int,
    report_id: int,
    report_title: str,
    report_type: str,
    type_label: str,
    auto_commit: bool = True,
) -> SystemNotification:
    """报告发布后通知客户企业端用户。"""
    title = f"新{type_label}已发布"
    message = f"「{report_title.strip() or type_label}」已发布，请在报告中心查看"
    source_key = f"report:published:{report_id}"
    payload = {
        "report_id": report_id,
        "report_title": report_title,
        "report_type": report_type,
        "menu_code": "customer.reports",
    }
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "CUSTOMER",
            SystemNotification.tenant_id == tenant_id,
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = "info"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        row = existing
    else:
        row = SystemNotification(
            audience_type="CUSTOMER",
            tenant_id=tenant_id,
            category="report_published",
            level="info",
            title=title,
            message=message[:500],
            payload_json=payload_text,
            source_key=source_key,
        )
        db.add(row)
    if auto_commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def upsert_subtask_backfill_notification(
    db: Session,
    *,
    subtask_id: str,
    title: str,
    message: str,
    payload: dict[str, Any],
) -> SystemNotification:
    """单条失败子任务对应一条待补录通知（source_key 去重）。"""
    source_key = f"subtask:backfill:{subtask_id}"
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = "warning"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="snapshot_backfill",
        level="warning",
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_batch_backfill_notification(
    db: Session,
    *,
    period: str,
    detect_day: str,
    scope: str,
    owner_user_id: int | None,
    tenant_id: int | None,
    subtask_entries: list[dict[str, Any]] | None = None,
    sample_payload: dict[str, Any] | None = None,
    slot_key: str | None = None,
    # 兼容旧按平台调用；写入公司×场次一条
    platform: str | None = None,
    platform_label: str | None = None,
    subtask_ids: list[str] | None = None,
) -> SystemNotification | None:
    """公司×具体场次时刻 汇总一条（A+B）：同 key 合并/递减，N=0 删除。"""
    # 2026-07-28 - 通知按场次时刻 - 不用早午晚；source_key 用 YYYYMMDD-HHMM
    resolved_slot = str(slot_key or "").strip()
    if not resolved_slot:
        # 兼容旧调用把 period 当早/午/晚或已是展示时刻
        compact = str(period or "").strip().replace(" ", "-").replace(":", "")
        if len(compact) >= 13 and compact[8] == "-" and compact[:8].isdigit():
            resolved_slot = f"{compact[:8]}-{compact[9:13]}"
        elif detect_day and len(str(detect_day)) == 10:
            resolved_slot = f"{str(detect_day).replace('-', '')}-0000"
        else:
            resolved_slot = "unknown"
    scope_key = str(tenant_id) if tenant_id is not None else f"lead:{scope}"
    source_key = f"backfill:batch:{scope_key}:{resolved_slot}"

    incoming: list[dict[str, Any]] = []
    for item in subtask_entries or []:
        sid = str(item.get("subtask_id") or "").strip()
        if not sid:
            continue
        code = str(item.get("platform") or platform or "unknown").strip() or "unknown"
        label = str(item.get("platform_label") or platform_label or code).strip() or code
        incoming.append({"subtask_id": sid, "platform": code, "platform_label": label})
    if not incoming and subtask_ids:
        code = str(platform or "unknown").strip() or "unknown"
        label = str(platform_label or code).strip() or code
        for sid_raw in subtask_ids:
            sid = str(sid_raw or "").strip()
            if sid:
                incoming.append({"subtask_id": sid, "platform": code, "platform_label": label})

    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )

    by_id: dict[str, dict[str, Any]] = {}
    if existing is not None:
        try:
            prev = json.loads(existing.payload_json or "{}")
        except Exception:
            prev = {}
        for item in list(prev.get("entries") or []):
            sid = str((item or {}).get("subtask_id") or "").strip()
            if sid:
                by_id[sid] = {
                    "subtask_id": sid,
                    "platform": str((item or {}).get("platform") or "unknown"),
                    "platform_label": str((item or {}).get("platform_label") or (item or {}).get("platform") or "unknown"),
                }
        # 兼容旧 payload 仅有 subtask_ids
        if not by_id:
            old_platform = str(prev.get("platform") or "unknown")
            old_label = str(prev.get("platform_label") or old_platform)
            for sid in list(prev.get("subtask_ids") or []):
                text = str(sid or "").strip()
                if text:
                    by_id[text] = {
                        "subtask_id": text,
                        "platform": old_platform,
                        "platform_label": old_label,
                    }

    added_new = False
    for item in incoming:
        sid = item["subtask_id"]
        if sid not in by_id:
            added_new = True
        by_id[sid] = item

    merged = list(by_id.values())
    count = len(merged)
    title, message, platform_counts = _compose_batch_backfill_copy(
        scope=scope,
        period=period,
        entries=merged,
        owner_user_id=owner_user_id,
    )
    merged_ids = [str(item["subtask_id"]) for item in merged]
    payload = dict(sample_payload or {})
    payload.update(
        {
            "period": period,
            "slot_key": resolved_slot,
            "detect_day": detect_day,
            "scope": scope,
            "pending_count": count,
            "entries": merged,
            "platform_counts": platform_counts,
            "subtask_ids": merged_ids,
            "subtask_id": merged_ids[0] if merged_ids else None,
            "owner_user_id": owner_user_id,
            "tenant_id": tenant_id,
            "menu_code": "platform.snapshot_backfill",
            "batch": True,
            "date_from": detect_day,
            "date_to": detect_day,
        }
    )
    payload_text = json.dumps(payload, ensure_ascii=False)

    if existing is not None:
        if count <= 0:
            _delete_notification(db, existing)
            return existing
        existing.title = title
        existing.message = message
        existing.level = "warning"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        # 新失败并入时清已读，重新响铃
        if added_new:
            db.execute(
                delete(SystemNotificationRead).where(
                    SystemNotificationRead.notification_id == existing.id
                )
            )
        db.commit()
        db.refresh(existing)
        return existing

    if count <= 0:
        return None

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="snapshot_backfill",
        level="warning",
        title=title,
        message=message,
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_approval_pending_notification(
    db: Session,
    *,
    approval_id: int,
    summary: str,
    requester_user_id: int,
    requester_name: str | None,
    module_label: str,
) -> SystemNotification:
    """销售提交审批后，通知运营/管理员处理。"""
    name = (requester_name or "").strip() or "销售"
    title = "待审批操作"
    message = f"{name} 提交了「{summary}」，请及时处理"
    source_key = f"approval:pending:{approval_id}"
    payload = {
        "approval_id": approval_id,
        "summary": summary,
        "module_label": module_label,
        "requester_user_id": requester_user_id,
        "requester_name": name,
        "menu_code": "platform.approvals",
    }
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = "warning"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="operation_approval",
        level="warning",
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_approval_pending_notification(db: Session, approval_id: int) -> None:
    """审批处理完成后移除待办通知。"""
    source_key = f"approval:pending:{approval_id}"
    row = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    if row is None:
        return
    _delete_notification(db, row)


def upsert_approval_result_notification(
    db: Session,
    *,
    approval_id: int,
    status: str,
    summary: str,
    requester_user_id: int,
    reviewer_name: str | None = None,
    review_comment: str | None = None,
) -> SystemNotification:
    """审批通过/驳回后通知提交人。"""
    approved = status == "approved"
    status_label = "已通过" if approved else "已驳回"
    title = f"审批{status_label}"
    message = f"您提交的「{summary}」{status_label}"
    if not approved and review_comment:
        message += f"：{review_comment.strip()}"
    elif approved and reviewer_name:
        message += f"（审核人：{reviewer_name.strip()}）"
    source_key = f"approval:result:{approval_id}"
    payload = {
        "approval_id": approval_id,
        "status": status,
        "summary": summary,
        "requester_user_id": requester_user_id,
        "menu_code": "platform.approvals",
    }
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    level = "info" if approved else "warning"
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = level
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="operation_approval_result",
        level=level,
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_subtask_backfill_notification(db: Session, subtask_id: str) -> None:
    """补录成功后移除单条通知，并从汇总批中剔除该子任务（N 递减，0 删除）。"""
    sid = str(subtask_id or "").strip()
    if not sid:
        return
    source_key = f"subtask:backfill:{sid}"
    row = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    if row is not None:
        _delete_notification(db, row)

    batch_rows = list(
        db.scalars(
            select(SystemNotification).where(
                SystemNotification.audience_type == "PLATFORM",
                SystemNotification.category == "snapshot_backfill",
                SystemNotification.source_key.like("backfill:batch:%"),
            )
        )
    )
    for batch in batch_rows:
        try:
            payload = json.loads(batch.payload_json or "{}")
        except Exception:
            continue
        entries = [
            {
                "subtask_id": str((item or {}).get("subtask_id") or "").strip(),
                "platform": str((item or {}).get("platform") or "unknown"),
                "platform_label": str(
                    (item or {}).get("platform_label") or (item or {}).get("platform") or "unknown"
                ),
            }
            for item in list(payload.get("entries") or [])
            if str((item or {}).get("subtask_id") or "").strip()
        ]
        if not entries:
            ids = [str(x) for x in (payload.get("subtask_ids") or []) if str(x or "").strip()]
            if sid not in ids:
                continue
            old_platform = str(payload.get("platform") or "unknown")
            old_label = str(payload.get("platform_label") or old_platform)
            entries = [
                {"subtask_id": x, "platform": old_platform, "platform_label": old_label}
                for x in ids
            ]
        if sid not in {e["subtask_id"] for e in entries}:
            continue
        remain = [e for e in entries if e["subtask_id"] != sid]
        if not remain:
            _delete_notification(db, batch)
            continue
        period = str(payload.get("period") or "时段")
        scope = str(payload.get("scope") or "监测任务")
        owner_user_id = _payload_owner_user_id(payload)
        title, message, platform_counts = _compose_batch_backfill_copy(
            scope=scope,
            period=period,
            entries=remain,
            owner_user_id=owner_user_id,
        )
        remain_ids = [e["subtask_id"] for e in remain]
        payload["entries"] = remain
        payload["subtask_ids"] = remain_ids
        payload["pending_count"] = len(remain)
        payload["subtask_id"] = remain_ids[0]
        payload["platform_counts"] = platform_counts
        batch.title = title
        batch.message = message
        batch.payload_json = json.dumps(payload, ensure_ascii=False)
        batch.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()


def push_monitor_alert_notification(alert: dict[str, Any]) -> SystemNotification | None:
    """将监控告警写入平台运营站内通知。"""
    db = SessionLocal()
    try:
        return upsert_monitor_alert_notification(db, alert)
    except Exception:
        db.rollback()
        logger.exception("Failed to persist monitor alert notification")
        return None
    finally:
        db.close()


def _visible_notification_ids_stmt(
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> Select[tuple[int]]:
    audience = "PLATFORM" if identity_type == "PLATFORM" else "CUSTOMER"
    visible_ids = select(SystemNotification.id).where(
        SystemNotification.audience_type == audience,
        SystemNotification.created_at >= _notification_retention_cutoff(),
    )
    if audience == "CUSTOMER":
        visible_ids = visible_ids.where(SystemNotification.tenant_id == tenant_id)
        visible_ids = _apply_customer_notification_visibility_filter(
            visible_ids,
            can_view_customer_reports=can_view_customer_reports,
        )
    else:
        visible_ids = visible_ids.where(SystemNotification.tenant_id.is_(None))
        visible_ids = _apply_notification_visibility_filter(
            visible_ids,
            user_id=user_id,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
            snapshot_backfill_owner_only=snapshot_backfill_owner_only,
            can_view_platform_service=can_view_platform_service,
            can_view_tenant_expiry=can_view_tenant_expiry,
            tenant_expiry_owner_only=tenant_expiry_owner_only,
        )
    return visible_ids


def list_notifications_for_user(
    db: Session,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    unread_only: bool = False,
    limit: int = 20,
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> list[dict[str, Any]]:
    stmt = _notification_query_for_user(
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
    )
    if identity_type == "PLATFORM":
        stmt = _apply_notification_visibility_filter(
            stmt,
            user_id=user_id,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
            snapshot_backfill_owner_only=snapshot_backfill_owner_only,
            can_view_platform_service=can_view_platform_service,
            can_view_tenant_expiry=can_view_tenant_expiry,
            tenant_expiry_owner_only=tenant_expiry_owner_only,
        )
    else:
        stmt = _apply_customer_notification_visibility_filter(
            stmt,
            can_view_customer_reports=can_view_customer_reports,
        )
    stmt = stmt.where(SystemNotification.created_at >= _notification_retention_cutoff())
    if unread_only:
        # 必须先筛未读再 limit；否则「最近 N 条里碰巧都已读」会漏掉更早的未读
        read_exists = (
            select(SystemNotificationRead.id)
            .where(
                SystemNotificationRead.notification_id == SystemNotification.id,
                SystemNotificationRead.user_id == user_id,
            )
            .exists()
        )
        stmt = stmt.where(~read_exists)
    stmt = stmt.order_by(SystemNotification.created_at.desc()).limit(max(1, min(limit, 100)))

    rows = list(db.scalars(stmt))
    if not rows:
        return []

    if unread_only:
        return [_serialize_notification(row, is_read=False) for row in rows]

    read_ids = set(
        db.scalars(
            select(SystemNotificationRead.notification_id).where(
                SystemNotificationRead.user_id == user_id,
                SystemNotificationRead.notification_id.in_([row.id for row in rows]),
            )
        )
    )
    return [
        _serialize_notification(row, is_read=row.id in read_ids)
        for row in rows
    ]


def count_unread_notifications(
    db: Session,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> int:
    visible_ids = _visible_notification_ids_stmt(
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
        can_view_customer_reports=can_view_customer_reports,
        snapshot_backfill_owner_only=snapshot_backfill_owner_only,
        can_view_platform_service=can_view_platform_service,
        can_view_tenant_expiry=can_view_tenant_expiry,
        tenant_expiry_owner_only=tenant_expiry_owner_only,
    )
    read_subq = (
        select(SystemNotificationRead.notification_id)
        .where(SystemNotificationRead.user_id == user_id)
    )
    stmt = select(func.count()).select_from(SystemNotification).where(
        SystemNotification.id.in_(visible_ids),
        SystemNotification.id.not_in(read_subq),
    )
    return int(db.scalar(stmt) or 0)


def mark_notification_read(
    db: Session,
    *,
    user_id: int,
    notification_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> bool:
    exists = db.scalar(
        select(SystemNotificationRead.id).where(
            SystemNotificationRead.user_id == user_id,
            SystemNotificationRead.notification_id == notification_id,
        )
    )
    if exists is not None:
        return True
    notification = db.get(SystemNotification, notification_id)
    if notification is None:
        return False
    if not _user_can_read_notification(
        notification,
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
        can_view_customer_reports=can_view_customer_reports,
        snapshot_backfill_owner_only=snapshot_backfill_owner_only,
        can_view_platform_service=can_view_platform_service,
        can_view_tenant_expiry=can_view_tenant_expiry,
        tenant_expiry_owner_only=tenant_expiry_owner_only,
    ):
        return False
    db.add(SystemNotificationRead(user_id=user_id, notification_id=notification_id))
    db.commit()
    return True


def mark_all_notifications_read(
    db: Session,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
    snapshot_backfill_owner_only: bool = False,
    can_view_platform_service: bool = False,
    can_view_tenant_expiry: bool = False,
    tenant_expiry_owner_only: bool = False,
) -> int:
    """标记当前用户可见范围内的全部未读；禁止再走 list(limit=100) 后筛未读。"""
    visible_ids = _visible_notification_ids_stmt(
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
        can_view_customer_reports=can_view_customer_reports,
        snapshot_backfill_owner_only=snapshot_backfill_owner_only,
        can_view_platform_service=can_view_platform_service,
        can_view_tenant_expiry=can_view_tenant_expiry,
        tenant_expiry_owner_only=tenant_expiry_owner_only,
    )
    read_ids = select(SystemNotificationRead.notification_id).where(
        SystemNotificationRead.user_id == user_id,
    )
    unread_ids = list(
        db.scalars(
            select(SystemNotification.id).where(
                SystemNotification.id.in_(visible_ids),
                SystemNotification.id.not_in(read_ids),
            )
        )
    )
    if not unread_ids:
        return 0
    for notification_id in unread_ids:
        db.add(SystemNotificationRead(user_id=user_id, notification_id=int(notification_id)))
    db.commit()
    return len(unread_ids)


def _serialize_notification(row: SystemNotification, *, is_read: bool) -> dict[str, Any]:
    payload: dict[str, Any] | None = None
    if row.payload_json:
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            payload = None
    return {
        "id": row.id,
        "audience_type": row.audience_type,
        "tenant_id": row.tenant_id,
        "category": row.category,
        "level": row.level,
        "title": row.title,
        "message": row.message,
        "payload": payload,
        "source_key": row.source_key,
        "is_read": is_read,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
