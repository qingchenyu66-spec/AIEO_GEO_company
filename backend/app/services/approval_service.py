"""销售等受限身份的操作审批。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.approval import OperationApproval
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.approval_preview_service import build_approval_preview
from app.services.menu_permission_service import has_identity_menu_permission
from app.services.tenant_scope import is_sales_identity

logger = logging.getLogger(__name__)

MODULE_LABELS = {
    "user": "用户管理",
    "tenant": "企业管理",
    "brand": "企业配置",
    "report": "分析报告",
    "diagnosis": "品牌诊断",
    "lead_diagnosis": "售前诊断",
}
ACTION_LABELS = {
    "create": "新建",
    "update": "修改",
    "delete": "删除",
    "publish": "发布",
    "submit": "提交执行",
    "restore": "恢复",
    "reset_password": "重置密码",
    "status": "变更状态",
}
STATUS_LABELS = {
    "pending": "待审批",
    "approved": "已通过",
    "rejected": "已驳回",
}

# 仅 PLATFORM_SALES 入队；交付 / 运营 / 管理员直接生效。
# 下列 operation_key 即使销售也直接执行，禁止接入 queue_or_run 审批。
SALES_APPROVAL_BYPASS_KEYS = frozenset({
    "management.user.delete",
    "management.user.restore",
    "management.user.reset_password",
    "management.user.status",
    "brand.competitor.create",
    "brand.competitor.update",
    "brand.competitor.delete",
})


def requires_sales_approval(db: Session, current: CurrentSession) -> bool:
    """仅销售身份需审批；交付、运营、管理员直接生效。"""
    return is_sales_identity(db, current.identity)


def can_review_approvals(db: Session, current: CurrentSession) -> bool:
    if current.identity.identity_type != "PLATFORM":
        return False
    return has_identity_menu_permission(
        db,
        current.identity.id,
        "platform.approvals",
        "can_update",
    )


def ensure_can_review(db: Session, current: CurrentSession) -> None:
    if not can_review_approvals(db, current):
        raise PermissionError("当前账号无权审批操作")


def _payload_body(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("body")
    return body if isinstance(body, dict) else payload


def find_pending_duplicate(
    db: Session,
    current: CurrentSession,
    *,
    operation_key: str,
    tenant_id: int | None,
    target_id: int | None,
    payload: dict[str, Any],
) -> OperationApproval | None:
    """查找同一申请人、同一业务目标下尚未处理的待审批单。"""
    stmt = (
        select(OperationApproval)
        .where(
            OperationApproval.deleted.is_(False),
            OperationApproval.status == "pending",
            OperationApproval.operation_key == operation_key,
            OperationApproval.requester_user_id == current.user.id,
        )
        .order_by(desc(OperationApproval.id))
    )
    candidates = list(db.scalars(stmt))
    if not candidates:
        return None

    body = _payload_body(payload)

    for record in candidates:
        if target_id is not None and record.target_id == target_id:
            return record
        if tenant_id is not None and record.tenant_id == tenant_id and operation_key in {
            "brand.asset.upsert",
            "brand.brand_word_groups.upsert",
            "reports.generate",
            "diagnosis.record.create",
        }:
            return record
        if operation_key == "management.user.create":
            username = str(body.get("username") or "").strip().lower()
            rec_body = _payload_body(record.payload_json if isinstance(record.payload_json, dict) else {})
            if username and str(rec_body.get("username") or "").strip().lower() == username:
                return record
        if operation_key == "lead_diagnosis.create":
            brand = str(body.get("brand_name") or "").strip()
            rec_body = _payload_body(record.payload_json if isinstance(record.payload_json, dict) else {})
            if brand and str(rec_body.get("brand_name") or "").strip() == brand:
                return record
    return None


def create_approval_request(
    db: Session,
    current: CurrentSession,
    *,
    operation_key: str,
    module: str,
    action: str,
    summary: str,
    payload: dict[str, Any],
    tenant_id: int | None = None,
    target_id: int | None = None,
) -> OperationApproval:
    record = OperationApproval(
        operation_key=operation_key,
        module=module,
        action=action,
        summary=summary.strip() or operation_key,
        tenant_id=tenant_id,
        target_id=target_id,
        payload_json=payload,
        status="pending",
        requester_user_id=current.user.id,
        requester_identity_id=current.identity.id,
    )
    db.add(record)
    db.flush()
    return record


def approval_to_dict(
    db: Session,
    record: OperationApproval,
    *,
    users_by_id: dict[int, User] | None = None,
    tenants_by_id: dict[int, Tenant] | None = None,
) -> dict[str, Any]:
    if users_by_id is not None:
        requester = users_by_id.get(record.requester_user_id)
        reviewer = users_by_id.get(record.reviewer_user_id) if record.reviewer_user_id else None
    else:
        requester = db.scalar(select(User).where(User.id == record.requester_user_id))
        reviewer = db.scalar(select(User).where(User.id == record.reviewer_user_id)) if record.reviewer_user_id else None
    if tenants_by_id is not None:
        tenant = tenants_by_id.get(record.tenant_id) if record.tenant_id else None
    else:
        tenant = db.scalar(select(Tenant).where(Tenant.id == record.tenant_id)) if record.tenant_id else None
    return {
        "id": record.id,
        "operation_key": record.operation_key,
        "module": record.module,
        "module_label": MODULE_LABELS.get(record.module, record.module),
        "action": record.action,
        "action_label": ACTION_LABELS.get(record.action, record.action),
        "summary": record.summary,
        "tenant_id": record.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "target_id": record.target_id,
        "payload": record.payload_json,
        "preview": build_approval_preview(db, record),
        "status": record.status,
        "status_label": STATUS_LABELS.get(record.status, record.status),
        "requester_user_id": record.requester_user_id,
        "requester_name": requester.display_name if requester else None,
        "reviewer_user_id": record.reviewer_user_id,
        "reviewer_name": reviewer.display_name if reviewer else None,
        "review_comment": record.review_comment,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "executed_result": record.executed_result_json,
        "created_at": record.created_at.isoformat(),
    }


def pending_approval_response(
    db: Session,
    record: OperationApproval,
    *,
    duplicate_merged: bool = False,
) -> dict[str, Any]:
    data = approval_to_dict(db, record)
    data["pending_approval"] = True
    if duplicate_merged:
        data["duplicate_merged"] = True
        data["message"] = "该操作已有待审批申请，已用本次内容更新原申请（未新建重复项）"
    else:
        data["message"] = "已提交审批，等待运营或管理员审核通过后生效"
    return data


def queue_or_run(
    db: Session,
    current: CurrentSession,
    *,
    operation_key: str,
    module: str,
    action: str,
    summary: str,
    payload: dict[str, Any],
    executor: Callable[[], Any],
    tenant_id: int | None = None,
    target_id: int | None = None,
) -> tuple[bool, Any]:
    """销售身份入审批队列；交付/运营/管理员及豁免操作直接执行。返回 (is_pending, result)。"""
    if operation_key in SALES_APPROVAL_BYPASS_KEYS:
        return False, executor()
    if not requires_sales_approval(db, current):
        return False, executor()

    existing = find_pending_duplicate(
        db,
        current,
        operation_key=operation_key,
        tenant_id=tenant_id,
        target_id=target_id,
        payload=payload,
    )
    if existing is not None:
        existing.summary = summary.strip() or existing.summary
        existing.payload_json = payload
        if tenant_id is not None:
            existing.tenant_id = tenant_id
        if target_id is not None:
            existing.target_id = target_id
        db.commit()
        db.refresh(existing)
        logger.info(
            "approval merged duplicate id=%s key=%s user=%s tenant=%s",
            existing.id,
            operation_key,
            current.user.id,
            tenant_id,
        )
        return True, pending_approval_response(db, existing, duplicate_merged=True)

    record = create_approval_request(
        db,
        current,
        operation_key=operation_key,
        module=module,
        action=action,
        summary=summary,
        payload=payload,
        tenant_id=tenant_id,
        target_id=target_id,
    )
    db.commit()
    db.refresh(record)
    from app.services.system_notification_service import upsert_approval_pending_notification

    requester = db.scalar(select(User).where(User.id == record.requester_user_id))
    try:
        upsert_approval_pending_notification(
            db,
            approval_id=record.id,
            summary=record.summary,
            requester_user_id=record.requester_user_id,
            requester_name=requester.display_name if requester else None,
            module_label=MODULE_LABELS.get(record.module, record.module),
        )
    except Exception:
        logger.exception("Failed to push approval pending notification id=%s", record.id)
    logger.info(
        "approval queued id=%s key=%s user=%s tenant=%s",
        record.id,
        operation_key,
        current.user.id,
        tenant_id,
    )
    return True, pending_approval_response(db, record)


def list_approvals(
    db: Session,
    current: CurrentSession,
    *,
    status: str | None = None,
    mine_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(OperationApproval).where(OperationApproval.deleted.is_(False)).order_by(desc(OperationApproval.id)).limit(limit)
    if status:
        stmt = stmt.where(OperationApproval.status == status)
    if mine_only or requires_sales_approval(db, current):
        stmt = stmt.where(OperationApproval.requester_user_id == current.user.id)
    elif not can_review_approvals(db, current):
        raise PermissionError("当前账号无权查看审批单")
    rows = list(db.scalars(stmt))
    user_ids = {item.requester_user_id for item in rows}
    user_ids.update(item.reviewer_user_id for item in rows if item.reviewer_user_id)
    tenant_ids = {item.tenant_id for item in rows if item.tenant_id}
    users_by_id: dict[int, User] = {}
    tenants_by_id: dict[int, Tenant] = {}
    if user_ids:
        users_by_id = {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(user_ids)))
        }
    if tenant_ids:
        tenants_by_id = {
            tenant.id: tenant
            for tenant in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids)))
        }
    return [
        approval_to_dict(db, item, users_by_id=users_by_id, tenants_by_id=tenants_by_id)
        for item in rows
    ]


def count_pending_approvals(db: Session, current: CurrentSession) -> int:
    """待审批数量：运营/管理员为全部待审，销售为自己提交的待审。"""
    stmt = select(func.count()).select_from(OperationApproval).where(
        OperationApproval.deleted.is_(False),
        OperationApproval.status == "pending",
    )
    if requires_sales_approval(db, current):
        stmt = stmt.where(OperationApproval.requester_user_id == current.user.id)
    elif can_review_approvals(db, current):
        pass
    else:
        return 0
    return int(db.scalar(stmt) or 0)


def get_approval(db: Session, current: CurrentSession, approval_id: int) -> OperationApproval:
    record = db.scalar(
        select(OperationApproval).where(
            OperationApproval.id == approval_id,
            OperationApproval.deleted.is_(False),
        )
    )
    if record is None:
        raise ValueError("审批单不存在")
    if requires_sales_approval(db, current):
        if record.requester_user_id != current.user.id:
            raise PermissionError("无权查看该审批单")
    else:
        ensure_can_review(db, current)
    return record


def reject_approval(
    db: Session,
    current: CurrentSession,
    approval_id: int,
    *,
    comment: str | None = None,
) -> dict[str, Any]:
    ensure_can_review(db, current)
    record = db.scalar(
        select(OperationApproval).where(
            OperationApproval.id == approval_id,
            OperationApproval.deleted.is_(False),
        )
    )
    if record is None:
        raise ValueError("审批单不存在")
    if record.status != "pending":
        raise ValueError("该审批单已处理")
    record.status = "rejected"
    record.reviewer_user_id = current.user.id
    record.reviewer_identity_id = current.identity.id
    record.review_comment = (comment or "").strip() or None
    record.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(record)
    from app.services.system_notification_service import (
        resolve_approval_pending_notification,
        upsert_approval_result_notification,
    )

    reviewer = db.scalar(select(User).where(User.id == current.user.id))
    try:
        resolve_approval_pending_notification(db, record.id)
        upsert_approval_result_notification(
            db,
            approval_id=record.id,
            status="rejected",
            summary=record.summary,
            requester_user_id=record.requester_user_id,
            reviewer_name=reviewer.display_name if reviewer else None,
            review_comment=record.review_comment,
        )
    except Exception:
        logger.exception("Failed to push approval reject notification id=%s", record.id)
    return approval_to_dict(db, record)


def approve_and_execute(
    db: Session,
    current: CurrentSession,
    approval_id: int,
    *,
    comment: str | None = None,
) -> dict[str, Any]:
    from app.services.approval_executor import execute_approval
    from app.services.operation_log_service import write_operation_log

    ensure_can_review(db, current)
    record = db.scalar(
        select(OperationApproval)
        .where(
            OperationApproval.id == approval_id,
            OperationApproval.deleted.is_(False),
        )
        .with_for_update()
    )
    if record is None:
        raise ValueError("审批单不存在")
    if record.status != "pending":
        raise ValueError("该审批单已处理")
    try:
        result = execute_approval(db, current, record)
    except Exception:
        db.rollback()
        raise
    record.status = "approved"
    record.reviewer_user_id = current.user.id
    record.reviewer_identity_id = current.identity.id
    record.review_comment = (comment or "").strip() or None
    record.reviewed_at = datetime.now(UTC)
    record.executed_result_json = result if isinstance(result, dict) else {"result": result}
    write_operation_log(
        db,
        current,
        "审批通过",
        f"已通过并执行：{record.summary}",
        target_module="操作审批",
        target_id=record.id,
        tenant_id=record.tenant_id,
        risk_level="关注",
    )
    db.commit()
    db.refresh(record)
    from app.services.system_notification_service import (
        resolve_approval_pending_notification,
        upsert_approval_result_notification,
    )

    reviewer = db.scalar(select(User).where(User.id == current.user.id))
    try:
        resolve_approval_pending_notification(db, record.id)
        upsert_approval_result_notification(
            db,
            approval_id=record.id,
            status="approved",
            summary=record.summary,
            requester_user_id=record.requester_user_id,
            reviewer_name=reviewer.display_name if reviewer else None,
        )
    except Exception:
        logger.exception("Failed to push approval approve notification id=%s", record.id)
    payload = approval_to_dict(db, record)
    payload["executed"] = True
    payload["executed_result"] = record.executed_result_json
    return payload
