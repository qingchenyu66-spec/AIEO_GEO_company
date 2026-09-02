"""销售等受限身份的操作审批。"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
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


def _payload_body(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    body = raw.get("body")
    return dict(body) if isinstance(body, dict) else dict(raw)


def normalize_lead_create_approval_payload(
    payload: dict[str, Any] | None,
    *,
    refresh_original: bool = True,
) -> dict[str, Any]:
    """售前诊断新建审批：body=审批采用，original_body=销售原文。"""
    # 2026-08-04 - 审批可改内容但需保留销售原文对照
    body = _payload_body(payload)
    raw = payload if isinstance(payload, dict) else {}
    if refresh_original:
        original = dict(body)
    else:
        prev = raw.get("original_body")
        original = dict(prev) if isinstance(prev, dict) else dict(body)
    return {"body": body, "original_body": original}


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

# 2026-09-02 - 驳回后销售可原单复活重新提交（方案 A）
RESUBMIT_OPERATION_KEYS = frozenset({
    "lead_diagnosis.create",
    "management.tenant.create",
    "brand.asset.upsert",
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


def _match_mergeable_approval(
    candidates: list[OperationApproval],
    *,
    operation_key: str,
    tenant_id: int | None,
    target_id: int | None,
    body: dict[str, Any],
) -> OperationApproval | None:
    for record in candidates:
        if target_id is not None and record.target_id == target_id:
            return record
        if tenant_id is not None and record.tenant_id == tenant_id and operation_key in {
            "brand.asset.upsert",
            "brand.brand_word_groups.upsert",
            "reports.generate",
            "diagnosis.record.create",
            "management.tenant.restore",
        }:
            return record
        if operation_key == "brand.asset.upsert" and tenant_id is None:
            name = str(body.get("company_full_name") or body.get("brand_name") or "").strip()
            rec_body = _payload_body(record.payload_json if isinstance(record.payload_json, dict) else {})
            if (
                name
                and record.tenant_id is None
                and str(rec_body.get("company_full_name") or rec_body.get("brand_name") or "").strip() == name
            ):
                return record
        if operation_key == "management.tenant.create":
            name = str(body.get("name") or "").strip()
            rec_body = _payload_body(record.payload_json if isinstance(record.payload_json, dict) else {})
            if name and str(rec_body.get("name") or "").strip() == name:
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
    return _match_mergeable_approval(
        candidates,
        operation_key=operation_key,
        tenant_id=tenant_id,
        target_id=target_id,
        body=_payload_body(payload),
    )


def find_rejected_resubmit_candidate(
    db: Session,
    current: CurrentSession,
    *,
    operation_key: str,
    tenant_id: int | None,
    target_id: int | None,
    payload: dict[str, Any],
) -> OperationApproval | None:
    """查找同一申请人、同一业务目标下可复活的已驳回单。"""
    if operation_key not in RESUBMIT_OPERATION_KEYS:
        return None
    stmt = (
        select(OperationApproval)
        .where(
            OperationApproval.deleted.is_(False),
            OperationApproval.status == "rejected",
            OperationApproval.operation_key == operation_key,
            OperationApproval.requester_user_id == current.user.id,
        )
        .order_by(desc(OperationApproval.id))
    )
    candidates = list(db.scalars(stmt))
    if not candidates:
        return None
    return _match_mergeable_approval(
        candidates,
        operation_key=operation_key,
        tenant_id=tenant_id,
        target_id=target_id,
        body=_payload_body(payload),
    )


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
    stored = payload
    if operation_key == "lead_diagnosis.create":
        stored = normalize_lead_create_approval_payload(payload, refresh_original=True)
    record = OperationApproval(
        operation_key=operation_key,
        module=module,
        action=action,
        summary=summary.strip() or operation_key,
        tenant_id=tenant_id,
        target_id=target_id,
        payload_json=stored,
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
        "lead_original_body": (
            (record.payload_json or {}).get("original_body")
            if record.operation_key == "lead_diagnosis.create" and isinstance(record.payload_json, dict)
            else None
        ),
        "lead_adopted_body": (
            _payload_body(record.payload_json)
            if record.operation_key == "lead_diagnosis.create"
            else None
        ),
        "preview": build_approval_preview(db, record),
        "status": record.status,
        "status_label": STATUS_LABELS.get(record.status, record.status),
        "requester_user_id": record.requester_user_id,
        "requester_name": requester.display_name if requester else None,
        "reviewer_user_id": record.reviewer_user_id,
        "reviewer_name": reviewer.display_name if reviewer else None,
        "review_comment": record.review_comment,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "resubmit_count": _resubmit_count(record.payload_json),
        "rejection_history": _rejection_history(record.payload_json),
        "executed_result": record.executed_result_json,
        "created_at": record.created_at.isoformat(),
    }


def _rejection_history(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = payload if isinstance(payload, dict) else {}
    history = raw.get("rejection_history")
    if not isinstance(history, list):
        return []
    return [dict(item) for item in history if isinstance(item, dict)]


def _resubmit_count(payload: dict[str, Any] | None) -> int:
    raw = payload if isinstance(payload, dict) else {}
    try:
        return max(0, int(raw.get("resubmit_count") or 0))
    except (TypeError, ValueError):
        return 0


def _append_rejection_to_payload(
    record: OperationApproval,
    payload_json: dict[str, Any],
) -> dict[str, Any]:
    if not record.review_comment and not record.reviewed_at:
        return payload_json
    out = dict(payload_json)
    history = out.get("rejection_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "review_comment": record.review_comment,
            "reviewer_user_id": record.reviewer_user_id,
            "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        }
    )
    out["rejection_history"] = history[-10:]
    return out


def _preserve_resubmit_meta(old_payload: dict[str, Any] | None, new_payload: dict[str, Any]) -> dict[str, Any]:
    old = old_payload if isinstance(old_payload, dict) else {}
    out = dict(new_payload)
    history = old.get("rejection_history")
    if isinstance(history, list) and history:
        out["rejection_history"] = history
    out["resubmit_count"] = _resubmit_count(old) + 1
    return out


def _validate_resubmit_payload(
    db: Session,
    record: OperationApproval,
    payload: dict[str, Any],
) -> dict[str, Any]:
    operation_key = record.operation_key
    body = _payload_body(payload)
    if operation_key == "lead_diagnosis.create":
        from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest

        validated = LeadDiagnosisCreateRequest.model_validate(body)
        stored = normalize_lead_create_approval_payload(
            {"body": validated.model_dump(mode="json")},
            refresh_original=True,
        )
    elif operation_key == "management.tenant.create":
        from app.schemas.permission import TenantCreateRequest

        validated = TenantCreateRequest.model_validate(body)
        stored = {"body": validated.model_dump(mode="json")}
    elif operation_key == "brand.asset.upsert":
        from app.schemas.brand import BrandAssetSaveRequest

        validated = BrandAssetSaveRequest.model_validate(body)
        stored = {"body": validated.model_dump(mode="json")}
    else:
        raise ValueError(f"当前审批类型不支持重新提交：{operation_key}")
    return _preserve_resubmit_meta(record.payload_json if isinstance(record.payload_json, dict) else {}, stored)


def _resubmit_summary(record: OperationApproval, payload: dict[str, Any]) -> str:
    body = _payload_body(payload)
    if record.operation_key == "lead_diagnosis.create":
        brand = str(body.get("brand_name") or "").strip() or "未命名"
        return f"新建售前诊断：{brand}"
    if record.operation_key == "management.tenant.create":
        name = str(body.get("name") or "").strip() or "未命名企业"
        return f"新增企业：{name}"
    if record.operation_key == "brand.asset.upsert":
        name = str(body.get("company_full_name") or body.get("brand_name") or "").strip() or "未命名企业"
        if record.tenant_id is not None:
            return f"保存企业配置：{name}"
        return f"新增企业：{name}"
    return record.summary


def _notify_approval_resubmitted(db: Session, record: OperationApproval) -> None:
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
        logger.exception("Failed to push approval resubmit notification id=%s", record.id)


def _reopen_rejected_approval(
    db: Session,
    record: OperationApproval,
    *,
    summary: str,
    payload_json: dict[str, Any],
    tenant_id: int | None = None,
    target_id: int | None = None,
) -> dict[str, Any]:
    # 2026-09-02 - 驳回原单复活：保留驳回历史，清空审批人字段，重新进待审
    payload_json = _append_rejection_to_payload(record, payload_json)
    record.status = "pending"
    record.reviewer_user_id = None
    record.reviewer_identity_id = None
    record.review_comment = None
    record.reviewed_at = None
    record.summary = summary.strip() or record.summary
    record.payload_json = payload_json
    if tenant_id is not None:
        record.tenant_id = tenant_id
    if target_id is not None:
        record.target_id = target_id
    db.commit()
    db.refresh(record)
    _notify_approval_resubmitted(db, record)
    data = approval_to_dict(db, record)
    data["pending_approval"] = True
    data["resubmitted"] = True
    data["message"] = "已修改并重新提交，等待运营或管理员审核"
    return data


def resubmit_approval(
    db: Session,
    current: CurrentSession,
    approval_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not requires_sales_approval(db, current):
        raise PermissionError("仅销售身份可重新提交审批")
    record = db.scalar(
        select(OperationApproval).where(
            OperationApproval.id == approval_id,
            OperationApproval.deleted.is_(False),
        )
    )
    if record is None:
        raise ValueError("审批单不存在")
    if record.requester_user_id != current.user.id:
        raise PermissionError("仅原提交人可重新提交")
    if record.status != "rejected":
        raise ValueError("仅已驳回单据可重新提交")
    if record.operation_key not in RESUBMIT_OPERATION_KEYS:
        raise ValueError(f"当前审批类型不支持重新提交：{record.operation_key}")

    stored = _validate_resubmit_payload(db, record, payload)
    summary = _resubmit_summary(record, stored)
    resolved_tenant_id = record.tenant_id
    if record.operation_key == "brand.asset.upsert":
        body = _payload_body(stored)
        tid = body.get("tenant_id")
        resolved_tenant_id = int(tid) if tid is not None else None
    return _reopen_rejected_approval(
        db,
        record,
        summary=summary,
        payload_json=stored,
        tenant_id=resolved_tenant_id,
        target_id=record.target_id,
    )


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
        if operation_key == "lead_diagnosis.create":
            # 销售再次提交：原文与采用都刷新为最新销售稿
            existing.payload_json = normalize_lead_create_approval_payload(payload, refresh_original=True)
        else:
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

    rejected = find_rejected_resubmit_candidate(
        db,
        current,
        operation_key=operation_key,
        tenant_id=tenant_id,
        target_id=target_id,
        payload=payload,
    )
    if rejected is not None:
        stored = _validate_resubmit_payload(db, rejected, payload)
        data = _reopen_rejected_approval(
            db,
            rejected,
            summary=summary.strip() or _resubmit_summary(rejected, stored),
            payload_json=stored,
            tenant_id=tenant_id,
            target_id=target_id,
        )
        logger.info(
            "approval resubmitted from rejected id=%s key=%s user=%s tenant=%s",
            rejected.id,
            operation_key,
            current.user.id,
            tenant_id,
        )
        return True, data

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


def revise_lead_diagnosis_create_approval(
    db: Session,
    current: CurrentSession,
    approval_id: int,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """审批人保存售前诊断新建单的「审批采用」内容；品牌名不可改，销售原文不动。"""
    from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest

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
        raise ValueError("仅待审批单据可保存修改")
    if record.operation_key != "lead_diagnosis.create":
        raise ValueError("当前仅支持修改「售前诊断新建」审批单")

    payload = record.payload_json if isinstance(record.payload_json, dict) else {}
    original = payload.get("original_body") if isinstance(payload.get("original_body"), dict) else _payload_body(payload)
    adopted = _payload_body(payload)
    brand = str(original.get("brand_name") or adopted.get("brand_name") or "").strip()
    if not brand:
        raise ValueError("原单缺少品牌名称，无法保存")

    from app.services.lead_diagnosis_service import can_edit_lead_diagnosis_regions

    # 2026-08-11 - 无企业地区编辑权仍可选诊断地区 - 审批采用同口径
    if can_edit_lead_diagnosis_regions(db, current):
        next_regions = patch.get("region_codes", adopted.get("region_codes"))
    else:
        next_regions = adopted.get("region_codes")

    from app.schemas.lead_diagnosis import normalize_lead_context, normalize_lead_schedule_datetimes
    from app.services.lead_diagnosis_service import (
        _merge_schedule_datetimes_into_context,
        _parse_lead_schedule_datetime,
        _schedule_days_from_datetimes,
    )

    schedule_datetimes: list[str] | None = None
    if "schedule_datetimes" in patch:
        schedule_datetimes = normalize_lead_schedule_datetimes(patch.get("schedule_datetimes"))
        if not schedule_datetimes:
            raise ValueError("请至少配置一个抓取时间点")
        # 2026-09-02 - 审批修改改时间段 - 待审单无已跑档，全部须 ≥ 当前
        now = datetime.now().replace(second=0, microsecond=0)
        for item in schedule_datetimes:
            dt = _parse_lead_schedule_datetime(item)
            if dt is None:
                raise ValueError(f"抓取时间格式无效：{item}")
            if dt < now:
                raise ValueError("抓取时间点不能早于当前时间")
        diagnosis_date = adopted.get("diagnosis_date") or date.today()
        if isinstance(diagnosis_date, str):
            diagnosis_date = date.fromisoformat(str(diagnosis_date)[:10])
        parsed = [dt for dt in (_parse_lead_schedule_datetime(x) for x in schedule_datetimes) if dt is not None]
        next_schedule_days = _schedule_days_from_datetimes(parsed, diagnosis_date)
    elif patch.get("schedule_days") is not None:
        next_schedule_days = patch.get("schedule_days")
    else:
        next_schedule_days = adopted.get("schedule_days")

    merged = {
        **adopted,
        "brand_name": brand,
        "competitors": patch.get("competitors", adopted.get("competitors")),
        "platforms": patch.get("platforms", adopted.get("platforms")),
        "region_codes": next_regions,
        "schedule_days": next_schedule_days,
        "prompts": patch.get("prompts", adopted.get("prompts")),
        "contact_note": patch.get("contact_note", adopted.get("contact_note")),
        "contact_name": adopted.get("contact_name"),
        "contact_phone": adopted.get("contact_phone"),
        "start_immediately": adopted.get("start_immediately", True),
    }
    # 校验可提交平台/问题等；品牌强制原文
    validated = LeadDiagnosisCreateRequest.model_validate(merged)
    body = validated.model_dump(mode="json")
    body["brand_name"] = brand
    lead_ctx = normalize_lead_context(adopted.get("lead_context") or body.get("lead_context"))
    if schedule_datetimes is not None:
        body["lead_context"] = _merge_schedule_datetimes_into_context(lead_ctx, schedule_datetimes)
    elif isinstance(adopted.get("lead_context"), dict):
        prev_dts = adopted["lead_context"].get("schedule_datetimes")
        if prev_dts:
            body["lead_context"] = _merge_schedule_datetimes_into_context(
                lead_ctx,
                normalize_lead_schedule_datetimes(prev_dts),
            )
    record.payload_json = {
        "body": body,
        "original_body": dict(original),
    }
    record.summary = f"新建售前诊断：{brand}"
    db.commit()
    db.refresh(record)
    return approval_to_dict(db, record)


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
    # 2026-08-25 - Logo 进审批驳回 - 清理申请人暂存文件
    from app.services.tenant_logo_service import cleanup_logo_staging_from_payload

    cleanup_logo_staging_from_payload(record.payload_json, owner_user_id=record.requester_user_id)
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
