"""审批通过后回放执行各业务操作。"""

from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.approval import OperationApproval
from app.models.diagnosis import BrandDiagnosis
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.brand import BrandAssetSaveRequest, BrandWordGroupsSaveRequest
from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest, LeadDiagnosisUpdateRequest
from app.schemas.permission import (
    TenantCreateRequest,
    TenantUpdateRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.services.brand_service import (
    asset_to_dict,
    brand_word_group_to_dict,
    competitor_to_dict,
    editable_keyword_groups,
    list_brand_word_groups,
    list_competitors,
    save_brand_asset,
    save_brand_word_groups,
)
from app.services.lead_diagnosis_service import create_lead_diagnosis, submit_due_lead_run, update_lead_diagnosis
from app.services.management_service import (
    _platform_identity_requests_admin,
    _tenant_code_from_name,
    allocate_tenant_code,
    assert_actor_can_assign_identities,
    create_managed_user,
    raise_if_live_tenant_name_or_code_conflict,
    tenant_name_was_purged,
    update_managed_user,
)
from app.services.report_service import generate_report, publish_report, update_report
from app.services.tenant_account_service import (
    mark_tenant_inactive,
    restore_tenant_customer_accounts,
    sync_tenant_accounts_for_service_state,
)
from app.services.tenant_scope import is_platform_admin_identity, resolve_and_guard_tenant_id


def _payload(record: OperationApproval) -> dict[str, Any]:
    raw = record.payload_json or {}
    return raw if isinstance(raw, dict) else {}


def _service_status_from_period(start: date | None, end: date | None) -> bool:
    if end and end < date.today():
        return False
    return True


def _requester_actor(db: Session, record: OperationApproval) -> tuple[User, UserIdentity]:
    user = db.get(User, record.requester_user_id)
    identity = db.get(UserIdentity, record.requester_identity_id)
    if user is None or identity is None or identity.deleted or not identity.status:
        raise ValueError("申请人账号或身份不可用，无法回放执行")
    if identity.user_id != user.id:
        raise ValueError("审批单申请人身份不匹配")
    return user, identity


def execute_approval(db: Session, current: CurrentSession, record: OperationApproval) -> dict[str, Any]:
    key = record.operation_key
    data = _payload(record)
    # 2026-07-30 - 涉及管理员职/角的用户单，仅管理员可批
    if key in {"management.user.create", "management.user.update"}:
        body = data.get("body") if isinstance(data.get("body"), dict) else data
        try:
            if key == "management.user.create":
                payload = UserCreateRequest.model_validate(body)
            else:
                payload = UserUpdateRequest.model_validate(body)
            needs_admin = any(_platform_identity_requests_admin(db, item) for item in payload.identities)
        except Exception:
            needs_admin = False
        if needs_admin and not is_platform_admin_identity(db, current.identity):
            raise PermissionError("仅平台管理员可审批涉及管理员职位的申请")
    handlers = {
        "management.user.create": _exec_user_create,
        "management.user.update": _exec_user_update,
        "management.tenant.create": _exec_tenant_create,
        "management.tenant.update": _exec_tenant_update,
        "management.tenant.delete": _exec_tenant_delete,
        "management.tenant.restore": _exec_tenant_restore,
        "brand.asset.upsert": _exec_brand_asset,
        "brand.brand_word_groups.upsert": _exec_brand_word_groups,
        "reports.generate": _exec_report_generate,
        "reports.update": _exec_report_update,
        "reports.publish": _exec_report_publish,
        "diagnosis.record.create": _exec_diagnosis_create,
        "lead_diagnosis.create": _exec_lead_create,
        "lead_diagnosis.update": _exec_lead_update,
        "lead_diagnosis.submit_run": _exec_lead_submit_run,
    }
    handler = handlers.get(key)
    if handler is None:
        raise ValueError(f"未支持的操作类型：{key}")
    return handler(db, current, record, data)


def _exec_user_create(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    requester, requester_identity = _requester_actor(db, record)
    payload = UserCreateRequest.model_validate(data.get("body") or data)
    user = create_managed_user(
        db,
        payload,
        requester,
        requester_identity,
        commit=False,
    )
    db.flush()
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


def _exec_user_update(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    requester, requester_identity = _requester_actor(db, record)
    user_id = int(data.get("user_id") or record.target_id or 0)
    payload = UserUpdateRequest.model_validate(data.get("body") or data)
    user = update_managed_user(
        db,
        user_id,
        payload,
        requester,
        requester_identity,
        commit=False,
    )
    db.flush()
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


def _exec_tenant_create(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    payload = TenantCreateRequest.model_validate(data.get("body") or data)
    name = payload.name.strip()
    preferred_code = (payload.code or _tenant_code_from_name(name)).strip()
    raise_if_live_tenant_name_or_code_conflict(db, name=name, code=preferred_code)
    was_purged = tenant_name_was_purged(db, name)
    code = allocate_tenant_code(db, name, preferred_code)
    tenant = Tenant(
        name=name,
        code=code,
        owner_user_id=record.requester_user_id,
        service_start_date=payload.service_start_date,
        service_end_date=payload.service_end_date,
        status=_service_status_from_period(payload.service_start_date, payload.service_end_date),
        stop_reason="expired" if payload.service_end_date and payload.service_end_date < date.today() else None,
    )
    db.add(tenant)
    db.flush()
    if not tenant.status:
        if tenant.stop_reason == "expired" and tenant.stopped_at is None:
            tenant.stopped_at = datetime.now(UTC)
        sync_tenant_accounts_for_service_state(db, tenant)
    result = {"id": tenant.id, "name": tenant.name, "code": tenant.code}
    if was_purged:
        result["name_was_purged"] = True
    return result


def _exec_tenant_update(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    from app.services.schedule_service import maybe_kick_brand_words_after_service_became_active
    from app.services.tenant_account_service import tenant_service_is_operational

    tenant_id = int(data.get("tenant_id") or record.target_id or 0)
    payload = TenantUpdateRequest.model_validate(data.get("body") or data)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    was_operational = tenant_service_is_operational(tenant)
    name = payload.name.strip()
    code = (payload.code or tenant.code or _tenant_code_from_name(name)).strip()
    raise_if_live_tenant_name_or_code_conflict(db, name=name, code=code, exclude_id=tenant_id)
    tenant.name = name
    tenant.code = code
    tenant.service_start_date = payload.service_start_date
    tenant.service_end_date = payload.service_end_date
    period_status = _service_status_from_period(payload.service_start_date, payload.service_end_date)
    if tenant.stop_reason in {"manual", "canceled"}:
        tenant.status = False
    else:
        tenant.status = period_status
        tenant.stop_reason = "expired" if payload.service_end_date and payload.service_end_date < date.today() else None
        if tenant.status:
            tenant.stopped_at = None
            tenant.stopped_by = None
        elif tenant.stop_reason == "expired" and tenant.stopped_at is None:
            tenant.stopped_at = datetime.now(UTC)
    sync_tenant_accounts_for_service_state(db, tenant)
    db.flush()
    maybe_kick_brand_words_after_service_became_active(
        tenant_id=tenant.id,
        became_active=tenant_service_is_operational(tenant) and not was_operational,
    )
    return {"id": tenant.id, "name": tenant.name}


def _exec_tenant_delete(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    from app.models.user_identity import UserIdentity

    tenant_id = int(data.get("tenant_id") or record.target_id or 0)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    mark_tenant_inactive(
        db,
        tenant,
        stop_reason="canceled" if tenant.service_start_date and tenant.service_start_date > date.today() else "manual",
        stopped_by=current.user.id,
        stopped_at=datetime.now(UTC),
    )
    db.flush()
    return {"id": tenant.id, "status": tenant.status}


def _exec_tenant_restore(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    from app.services.schedule_service import maybe_kick_brand_words_after_service_became_active
    from app.services.tenant_account_service import tenant_service_is_operational

    tenant_id = int(data.get("tenant_id") or record.target_id or 0)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    if tenant.service_end_date and tenant.service_end_date < date.today():
        raise ValueError("服务已到期，请先延长服务期限后再恢复")
    was_operational = tenant_service_is_operational(tenant)
    tenant.status = _service_status_from_period(tenant.service_start_date, tenant.service_end_date)
    tenant.stop_reason = None
    tenant.stopped_at = None
    tenant.stopped_by = None
    restore_tenant_customer_accounts(db, tenant_id)
    db.flush()
    maybe_kick_brand_words_after_service_became_active(
        tenant_id=tenant.id,
        became_active=tenant_service_is_operational(tenant) and not was_operational,
    )
    return {"id": tenant.id, "status": tenant.status}


def _exec_brand_asset(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    payload = BrandAssetSaveRequest.model_validate(data.get("body") or data)
    asset = save_brand_asset(db, payload, current)
    return {"tenant_id": asset.tenant_id, "brand_name": asset.brand_name}


def _exec_brand_word_groups(
    db: Session,
    current: CurrentSession,
    record: OperationApproval,
    data: dict[str, Any],
) -> dict[str, Any]:
    """回放销售提交的品牌词保存；与 PUT /brand-word-groups 直执口径一致。"""
    from app.core.config import settings
    from app.services.schedule_service import enumerate_brand_word_once_groups, submit_schedule_group

    payload = BrandWordGroupsSaveRequest.model_validate(data.get("body") or data)
    asset, submit_rows = save_brand_word_groups(db, payload, current)
    submit_dicts = [brand_word_group_to_dict(item) for item in submit_rows]
    submitted: list[dict[str, Any]] = []
    for item in enumerate_brand_word_once_groups(
        db,
        tenant_id=asset.tenant_id,
        groups=submit_dicts,
        max_prompts=settings.celery_scan_submit_max_prompts,
    ):
        submitted.append(submit_schedule_group(db, current, item))
    keyword_groups = editable_keyword_groups(db, asset.tenant_id)
    brand_word_groups = list_brand_word_groups(db, asset.tenant_id)
    competitors = list_competitors(db, asset.tenant_id)
    return {
        "tenant_id": asset.tenant_id,
        "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
        "competitors": [competitor_to_dict(item) for item in competitors],
        "once_submitted": submitted,
    }


def _exec_report_generate(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("body") or data
    return generate_report(db, body, current, auto_commit=False)


def _exec_report_update(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    report_id = int(data.get("report_id") or record.target_id or 0)
    body = data.get("body") or data
    return update_report(db, report_id, body, current, auto_commit=False)


def _exec_report_publish(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    report_id = int(data.get("report_id") or record.target_id or 0)
    return publish_report(db, report_id, current, auto_commit=False)


def _exec_diagnosis_create(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("body") or data
    raw_tenant_id = body.get("tenant_id", record.tenant_id)
    if raw_tenant_id is None:
        raise ValueError("请指定企业")
    tenant_id = resolve_and_guard_tenant_id(db, current, int(raw_tenant_id))
    record_obj = BrandDiagnosis(
        tenant_id=tenant_id,
        created_by_user_id=record.requester_user_id,
        diagnosis_title=body.get("diagnosis_title", "品牌诊断"),
        health_score=body.get("health_score", 80),
        sentiment_summary=body.get("sentiment_summary"),
        strength_points=body.get("strength_points"),
        weakness_points=body.get("weakness_points"),
        recommendation=body.get("recommendation"),
        diagnosis_platforms_json=body.get("diagnosis_platforms", ["doubao_mobile", "deepseek"]),
        diagnosis_keywords_json=body.get("diagnosis_keywords", []),
        reference_count=body.get("reference_count", 0),
        monitor_data_summary=body.get("monitor_data_summary"),
        status="published",
    )
    db.add(record_obj)
    db.flush()
    return {"id": record_obj.id, "diagnosis_title": record_obj.diagnosis_title}


def _exec_lead_create(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    payload = LeadDiagnosisCreateRequest.model_validate(data.get("body") or data)
    return create_lead_diagnosis(db, current, payload)


def _exec_lead_update(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    lead_id = int(data.get("lead_id") or record.target_id or 0)
    payload = LeadDiagnosisUpdateRequest.model_validate(data.get("body") or data)
    return update_lead_diagnosis(db, current, lead_id, payload)


def _exec_lead_submit_run(db: Session, current: CurrentSession, record: OperationApproval, data: dict[str, Any]) -> dict[str, Any]:
    lead_id = int(data.get("lead_id") or record.target_id or 0)
    return submit_due_lead_run(
        db,
        current,
        lead_id,
        schedule_key=data.get("schedule_key"),
        force=bool(data.get("force")),
    )
