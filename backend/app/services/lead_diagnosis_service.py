"""售前线索诊断：按计划天数×每日时段抓取、汇总统计、HTML 导出。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator

from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from kombu.exceptions import OperationalError

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.user import User
from app.models.tenant import Tenant
from app.core.lead_diagnosis_config import (
    DEFAULT_LEAD_SCHEDULE_TIMES,
    LEAD_DIAGNOSIS_CREATE_COOLDOWN_DAYS,
    clamp_lead_schedule_days,
)
from app.core.masking import mask_phone
from app.core.region_catalog import normalize_region_codes, region_display_name, region_submission_targets
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.lead_diagnosis import (
    LeadDiagnosisCreateRequest,
    LeadDiagnosisUpdateRequest,
    normalize_lead_context,
)
from app.schemas.monitor import FAST_MONITOR_MODE, CompetitorBrand, MonitorTaskCreateRequest, PlatformConfig
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.lead_diagnosis_analytics import build_lead_diagnosis_analytics, build_rule_report_sections
from app.services.menu_permission_service import has_identity_menu_permission
from app.services.tenant_scope import is_sales_identity
from app.services.report_text_sanitize import consolidate_top_sources, sanitize_source_title
from app.services.molizhishu_catalog_service import filter_submittable_platforms, get_supported_platform_catalog
from app.services.molizhishu_client import MolizhishuApiError
from app.services.monitor_service import TERMINAL_STATUSES, submit_standalone_monitor_task

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"pending", "collecting"}
RUN_TERMINAL = {"completed", "failed", "skipped"}
LEAD_RUN_STALE_MINUTES = 10
LEAD_MAX_PARALLEL_SUBMITS = 2
LEAD_DIAGNOSIS_TASK_SUBTITLE = "售前诊断"


def _slot_is_future(day: date, slot: str, now: datetime) -> bool:
    scheduled = _slot_scheduled_at(day, slot)
    return scheduled is not None and now < scheduled


def _active_inflight_run_count(lead: LeadDiagnosis, tasks: dict[str, GeoMonitorTask]) -> int:
    """仍在模力侧抓取中的批次（pending/submitted 且 task 未终态）。"""
    count = 0
    for run in lead.runs or []:
        if run.status not in {"pending", "submitted"}:
            continue
        task = tasks.get(run.task_id or "")
        if task is None:
            count += 1
            continue
        if task.status in TERMINAL_STATUSES:
            continue
        count += 1
    return count


def abort_lead_diagnosis(
    db: Session,
    lead_id: int,
    *,
    reason: str = "管理员重置",
) -> LeadDiagnosis:
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None:
        raise ValueError("售前诊断不存在")
    tasks = _task_map(db, lead)
    for run in lead.runs or []:
        if run.status not in {"pending", "submitted"}:
            continue
        run.status = "failed"
        run.error_message = reason
        task = tasks.get(run.task_id or "")
        if task is not None and task.status not in TERMINAL_STATUSES:
            task.status = "stopped"
            task.last_error = reason
    if lead.status in ACTIVE_STATUSES:
        lead.status = "failed"
    db.commit()
    db.refresh(lead)
    return lead


def lead_diagnosis_cost_rank_label(brand_name: str | None) -> str:
    brand = str(brand_name or "").strip()
    if not brand:
        return LEAD_DIAGNOSIS_TASK_SUBTITLE
    return f"{brand}_{LEAD_DIAGNOSIS_TASK_SUBTITLE}"


def build_platform_cost_ranking(
    db: Session,
    *,
    tenant_name_map: dict[int, str],
    tenant_ids: list[int] | None = None,
    limit: int | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """运营总览费用排行：正式企业按 tenant 汇总，售前诊断按线索品牌拆分展示。

    limit=None 表示返回全部有消耗行；勿再默认 Top8（企业少时会误以为数据不全）。
    """
    from sqlalchemy import func

    tenant_stmt = (
        select(GeoMonitorTask.tenant_id, func.coalesce(func.sum(GeoMonitorSubtask.amount), 0))
        .join(GeoMonitorSubtask, GeoMonitorSubtask.task_id == GeoMonitorTask.task_id)
        .where(GeoMonitorTask.deleted.is_(False), GeoMonitorTask.tenant_id.isnot(None))
    )
    if since is not None:
        tenant_stmt = tenant_stmt.where(GeoMonitorTask.created_at >= since)
    if tenant_ids is not None:
        tenant_stmt = tenant_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    tenant_rows = db.execute(tenant_stmt.group_by(GeoMonitorTask.tenant_id)).all()

    ranking: list[dict[str, Any]] = [
        {
            "tenant_id": int(row[0]),
            "lead_diagnosis_id": None,
            "tenant_name": tenant_name_map.get(int(row[0])) or f"企业 #{row[0]}",
            "cost": round(float(row[1] or 0), 4),
        }
        for row in tenant_rows
        if float(row[1] or 0) > 0
    ]

    if tenant_ids is None:
        lead_where = [
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id.is_(None),
            LeadDiagnosis.deleted.is_(False),
            LeadDiagnosisRun.task_id.isnot(None),
        ]
        if since is not None:
            lead_where.append(GeoMonitorTask.created_at >= since)
        lead_rows = db.execute(
            select(
                LeadDiagnosis.id,
                LeadDiagnosis.brand_name,
                func.coalesce(func.sum(GeoMonitorSubtask.amount), 0),
            )
            .join(LeadDiagnosisRun, LeadDiagnosisRun.lead_diagnosis_id == LeadDiagnosis.id)
            .join(GeoMonitorSubtask, GeoMonitorSubtask.task_id == LeadDiagnosisRun.task_id)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == LeadDiagnosisRun.task_id)
            .where(*lead_where)
            .group_by(LeadDiagnosis.id, LeadDiagnosis.brand_name)
        ).all()
        for lead_id, brand_name, amount in lead_rows:
            cost = round(float(amount or 0), 4)
            if cost <= 0:
                continue
            ranking.append({
                "tenant_id": None,
                "lead_diagnosis_id": int(lead_id),
                "tenant_name": lead_diagnosis_cost_rank_label(brand_name),
                "cost": cost,
            })

        lead_task_ids = select(LeadDiagnosisRun.task_id).where(LeadDiagnosisRun.task_id.isnot(None))
        orphan_where = [
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id.is_(None),
            GeoMonitorTask.task_id.notin_(lead_task_ids),
        ]
        if since is not None:
            orphan_where.append(GeoMonitorTask.created_at >= since)
        orphan_cost = float(db.scalar(
            select(func.coalesce(func.sum(GeoMonitorSubtask.amount), 0))
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .where(*orphan_where)
        ) or 0)
        if orphan_cost > 0:
            ranking.append({
                "tenant_id": None,
                "lead_diagnosis_id": None,
                "tenant_name": "其他未绑定任务",
                "cost": round(orphan_cost, 4),
            })

    ranking.sort(key=lambda item: item["cost"], reverse=True)
    # 2026-08-03 - 去掉默认 Top8；企业全量有消耗都应展示
    if limit is None or limit <= 0:
        return ranking
    return ranking[:limit]


def lead_run_blocks_due(run: LeadDiagnosisRun | None, *, now: datetime | None = None) -> bool:
    """非 failed 的运行记录在 stale 窗口内视为占用该时段。"""
    if run is None:
        return False
    if run.status == "failed":
        return False
    if run.status in {"completed", "skipped"}:
        return True
    if run.status in {"pending", "submitted", "running"}:
        now = now or datetime.now()
        updated = run.updated_at or run.created_at
        if updated and now - updated < timedelta(minutes=LEAD_RUN_STALE_MINUTES):
            return True
        return False
    return True


def lead_diagnosis_task_displays(db: Session, task_ids: list[str]) -> dict[str, dict[str, str]]:
    """监测 task_id -> 售前诊断在运营看板上的展示文案。"""
    cleaned_ids = [item for item in task_ids if item]
    if not cleaned_ids:
        return {}
    rows = db.execute(
        select(LeadDiagnosisRun.task_id, LeadDiagnosis.brand_name)
        .join(LeadDiagnosis, LeadDiagnosis.id == LeadDiagnosisRun.lead_diagnosis_id)
        .where(LeadDiagnosisRun.task_id.in_(cleaned_ids), LeadDiagnosis.deleted.is_(False))
    )
    displays: dict[str, dict[str, str]] = {}
    for task_id, brand_name in rows:
        if not task_id or not brand_name:
            continue
        brand = str(brand_name).strip()
        if not brand:
            continue
        displays[str(task_id)] = {
            "tenant_name": f"{brand} 诊断报告",
            "monitor_keywords": LEAD_DIAGNOSIS_TASK_SUBTITLE,
        }
    return displays


@dataclass(frozen=True)
class DueLeadRun:
    lead_id: int
    schedule_key: str
    schedule_label: str
    region_code: str | None = None


def can_view_lead_creator_info(db: Session, current: CurrentSession) -> bool:
    """运营/管理员可查看创建人；销售仅访问本人任务，列表不重复展示创建人。"""
    return not is_sales_identity(db, current.identity)


def _creator_users_map(db: Session, user_ids: set[int]) -> dict[int, User]:
    if not user_ids:
        return {}
    return {
        row.id: row
        for row in db.scalars(select(User).where(User.id.in_(user_ids)))
    }


def _serialize_creator(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "user_id": user.id,
        "display_name": (user.display_name or "").strip() or user.username,
        "username": user.username,
    }


def require_lead_diagnosis_access(db: Session, current: CurrentSession, action: str = "can_export") -> None:
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可访问售前诊断")
    if not has_identity_menu_permission(db, current.identity.id, "platform.lead_diagnosis", action):
        raise PermissionError("当前身份无售前诊断权限")


def can_edit_lead_diagnosis_regions(db: Session, current: CurrentSession) -> bool:
    """与企业管理「服务地区」同权：无编辑权则诊断不可选地区。"""
    return has_identity_menu_permission(
        db, current.identity.id, "platform.audit.regions", "can_update",
    )


def sanitize_lead_region_codes_for_grants(
    db: Session,
    current: CurrentSession,
    region_codes: list[str] | None,
) -> list[str]:
    # 2026-08-11 - 无企业地区编辑权仍可选诊断地区 - 与 audit.regions 对齐，无权强制全部区域
    if can_edit_lead_diagnosis_regions(db, current):
        return normalize_region_codes(region_codes)
    return []


def assert_lead_platforms_allowed(db: Session, current: CurrentSession, platforms: list[str]) -> None:
    """2026-08-04 - 诊断平台与职位「平台范围」同口径；白名单为空则不可选任何端。"""
    from app.services.menu_permission_service import identity_allowed_monitor_platforms

    allowed = set(identity_allowed_monitor_platforms(db, current.identity))
    if not allowed:
        raise ValueError("当前职位未配置可诊断平台，请联系管理员在职位管理中勾选平台范围")
    selected = [str(code or "").strip() for code in platforms if str(code or "").strip()]
    forbidden = [code for code in selected if code not in allowed]
    if forbidden:
        raise ValueError(f"包含未授权诊断平台：{'、'.join(forbidden)}")


def ensure_lead_diagnosis_owner_access(db: Session, current: CurrentSession, lead: LeadDiagnosis) -> None:
    """销售只能访问本人创建的售前诊断；运营/管理员不限制。"""
    if not is_sales_identity(db, current.identity):
        return
    if lead.created_by_user_id != current.user.id:
        raise PermissionError("无权访问该售前诊断")


def _load_lead_diagnosis(db: Session, lead_id: int) -> LeadDiagnosis | None:
    return db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )


def ensure_lead_diagnosis_owner_access_by_id(db: Session, current: CurrentSession, lead_id: int) -> LeadDiagnosis:
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    ensure_lead_diagnosis_owner_access(db, current, lead)
    return lead


def _schedule_slots(lead: LeadDiagnosis) -> list[str]:
    raw = lead.schedule_times_json or DEFAULT_LEAD_SCHEDULE_TIMES
    cleaned = [str(item).strip() for item in raw if str(item).strip()]
    return cleaned or list(DEFAULT_LEAD_SCHEDULE_TIMES)


def _schedule_days(lead: LeadDiagnosis) -> int:
    # 2026-08-04 - 诊断天数可配 - 读库字段，旧单/缺省回落默认 3
    return clamp_lead_schedule_days(getattr(lead, "schedule_days", None))


def _schedule_total_count(lead: LeadDiagnosis) -> int:
    region_count = len(region_submission_targets(lead.region_codes_json))
    return _schedule_days(lead) * len(_schedule_slots(lead)) * region_count


def _schedule_rounds_per_region(lead: LeadDiagnosis) -> int:
    return _schedule_days(lead) * len(_schedule_slots(lead))


def _schedule_anchor(lead: LeadDiagnosis) -> datetime:
    """抓取计划起点：创建时刻（跳过创建前已过的时段）。"""
    if lead.created_at:
        return lead.created_at.replace(tzinfo=None) if lead.created_at.tzinfo else lead.created_at
    return datetime.combine(lead.diagnosis_date, time.min)


def _slot_scheduled_at(day: date, slot: str) -> datetime | None:
    slot_time = _slot_time(slot)
    if slot_time is None:
        return None
    return datetime.combine(day, slot_time)


def _iter_schedule_slot_rounds(lead: LeadDiagnosis) -> Iterator[tuple[date, str]]:
    """按时间顺序产出计入计划次数的 (日期, 时段)，创建前已过的时段跳过并顺延。"""
    slots = _schedule_slots(lead)
    rounds_needed = _schedule_rounds_per_region(lead)
    anchor = _schedule_anchor(lead)
    emitted = 0
    day_offset = 0
    while emitted < rounds_needed and day_offset < 366:
        day = lead.diagnosis_date + timedelta(days=day_offset)
        for slot in slots:
            scheduled = _slot_scheduled_at(day, slot)
            if scheduled is None or scheduled < anchor:
                continue
            yield day, slot
            emitted += 1
            if emitted >= rounds_needed:
                return
        day_offset += 1


def _plan_end_date(lead: LeadDiagnosis) -> date:
    last_day = lead.diagnosis_date
    for day, _slot in _iter_schedule_slot_rounds(lead):
        last_day = day
    return last_day


def _schedule_calendar_days(lead: LeadDiagnosis) -> int:
    days = {day for day, _slot in _iter_schedule_slot_rounds(lead)}
    return len(days) or _schedule_days(lead)


def _serialize_schedule_plan(lead: LeadDiagnosis) -> list[dict[str, Any]]:
    return [
        {
            "day": day.isoformat(),
            "slot": slot,
            "schedule_key": schedule_key,
            "schedule_label": schedule_label,
            "region_code": region_code,
        }
        for day, slot, schedule_key, schedule_label, region_code in _iter_schedule_plan(lead)
    ]


def _append_region_to_schedule(key: str, label: str, region_code: str | None) -> tuple[str, str]:
    if not region_code:
        return key, label
    name = region_display_name(region_code)
    return f"{key}-rg{region_code}", f"{label} · {name}"


def _iter_schedule_plan(lead: LeadDiagnosis) -> Iterator[tuple[date, str, str, str, str | None]]:
    """按时间顺序产出 (day, slot, schedule_key, schedule_label, region_code)。"""
    for day, slot in _iter_schedule_slot_rounds(lead):
        key, label = _build_schedule_key(day, slot)
        for region_code in region_submission_targets(lead.region_codes_json):
            schedule_key, schedule_label = _append_region_to_schedule(key, label, region_code)
            yield day, slot, schedule_key, schedule_label, region_code


def _expected_schedule_keys(lead: LeadDiagnosis) -> set[str]:
    return {key for _, _, key, _, _ in _iter_schedule_plan(lead)}


def _slot_time(value: str) -> time | None:
    text = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _build_schedule_key(diagnosis_date: date, slot: str) -> tuple[str, str]:
    slot_time = _slot_time(slot)
    if slot_time is None:
        raise ValueError(f"无效时段：{slot}")
    key = f"{diagnosis_date.strftime('%Y%m%d')}-{slot_time.strftime('%H%M')}"
    label = f"{diagnosis_date.isoformat()} {slot_time.strftime('%H:%M')}"
    return key, label


def _all_platform_configs() -> list[PlatformConfig]:
    codes = filter_submittable_platforms(
        [str(item.get("code") or "") for item in get_supported_platform_catalog()]
    )
    if not codes:
        raise ValueError("未配置可提交的 AI 监测平台")
    return [PlatformConfig(platform=code, mode=FAST_MONITOR_MODE, screenshot=1) for code in codes]


def _platform_configs_for_lead(lead: LeadDiagnosis) -> list[PlatformConfig]:
    # 2026-07-29 - 新建可指定诊断平台 - 有落库列表则按指定提交；旧单空列表回退全量
    selected = filter_submittable_platforms(
        [str(item or "").strip() for item in (lead.platforms_json or [])]
    )
    if selected:
        return [PlatformConfig(platform=code, mode=FAST_MONITOR_MODE, screenshot=1) for code in selected]
    return _all_platform_configs()


def _competitor_payload(names: list[str]) -> list[CompetitorBrand]:
    return [CompetitorBrand(name=name) for name in names if name.strip()]


def _normalize_brand_key(name: str | None) -> str:
    return re.sub(r"\s+", "", str(name or "").strip().lower())


def _resolve_lead_tenant_id(db: Session, lead: LeadDiagnosis) -> int | None:
    if lead.converted_tenant_id:
        return lead.converted_tenant_id
    lead_key = _normalize_brand_key(lead.brand_name)
    if not lead_key:
        return None
    for asset in db.scalars(select(BrandAsset).where(BrandAsset.deleted.is_(False))):
        for candidate in (asset.brand_name, asset.company_full_name, asset.brand_short_name):
            key = _normalize_brand_key(candidate)
            if key and (key == lead_key or key in lead_key or lead_key in key):
                return asset.tenant_id
    return None


def resolve_lead_competitors(db: Session, lead: LeadDiagnosis, *, sync_lead: bool = True) -> list[str]:
    """读取企业当前生效竞品；售前诊断快照与后台不一致时同步回写。"""
    tenant_id = _resolve_lead_tenant_id(db, lead)
    if tenant_id:
        names = [
            str(row.name).strip()
            for row in db.scalars(
                select(BrandCompetitor).where(
                    BrandCompetitor.tenant_id == tenant_id,
                    BrandCompetitor.deleted.is_(False),
                    BrandCompetitor.status.is_(True),
                )
            )
            if row.name and str(row.name).strip()
        ]
        if names:
            synced = names[:10]
            if sync_lead and synced != (lead.competitors_json or []):
                lead.competitors_json = synced
            return synced
    return [str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()]


def _serialize_run(run: LeadDiagnosisRun) -> dict[str, Any]:
    # 2026-08-04 - 临时 lead 的 run 未落库无 created_at - 导出序列化允许空时间戳
    return {
        "id": run.id,
        "schedule_key": run.schedule_key,
        "schedule_label": run.schedule_label,
        "task_id": run.task_id,
        "status": run.status,
        "prompt_count": run.prompt_count,
        "platform_count": run.platform_count,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _lead_region_codes(lead: LeadDiagnosis, region_code: str | None = None) -> list[str] | None:
    code = (region_code or "").strip()
    return [code] if code else None


def _serialize_lead(
    lead: LeadDiagnosis,
    *,
    include_result: bool = False,
    mask_contact: bool = False,
    include_creator: bool = False,
    creator: User | None = None,
) -> dict[str, Any]:
    result = lead.diagnosis_result_json or {}
    kpis = result.get("kpis") or {}
    contact_phone = mask_phone(lead.contact_phone) if mask_contact else lead.contact_phone
    payload: dict[str, Any] = {
        "id": lead.id,
        "brand_name": lead.brand_name,
        "contact_name": lead.contact_name,
        "contact_phone": contact_phone,
        "contact_note": lead.contact_note,
        # 2026-08-13 - 详情可审计入口字段 - 序列化 lead_context，旧单 normalize 为空字段
        "lead_context": normalize_lead_context(lead.lead_context_json),
        # 2026-08-13 - 露出词/别名（可选）
        "brand_aliases": list(getattr(lead, "brand_aliases_json", None) or []),
        "prompts": lead.prompts_json or [],
        "competitors": lead.competitors_json or [],
        "platforms": list(lead.platforms_json or []),
        "region_codes": normalize_region_codes(lead.region_codes_json or []),
        "schedule_times": _schedule_slots(lead),
        "schedule_days": _schedule_days(lead),
        "schedule_calendar_days": _schedule_calendar_days(lead),
        "plan_end_date": _plan_end_date(lead).isoformat(),
        "schedule_total_count": _schedule_total_count(lead),
        "diagnosis_date": lead.diagnosis_date.isoformat(),
        "status": lead.status,
        "health_score": lead.health_score,
        "converted_tenant_id": lead.converted_tenant_id,
        "created_by_user_id": lead.created_by_user_id,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
        "run_count": len(lead.runs or []),
        # 2026-08-21 - 迁入/补交产生计划外 run 时进度 12/9=133% - 只计计划内完成档
        "completed_run_count": _completed_planned_run_count(lead),
        "mention_rate": kpis.get("mention_rate"),
        "avg_rank": kpis.get("avg_rank"),
    }
    if include_creator:
        if creator is not None:
            payload["creator"] = _serialize_creator(creator)
        elif lead.created_by_user_id:
            payload["creator"] = {
                "user_id": lead.created_by_user_id,
                "display_name": f"用户 #{lead.created_by_user_id}",
                "username": None,
            }
    if include_result:
        payload["diagnosis_result"] = result
        payload["runs"] = [_serialize_run(item) for item in sorted(lead.runs or [], key=lambda row: row.schedule_key)]
        payload["schedule_plan"] = _serialize_schedule_plan(lead)
    return payload


def list_lead_diagnoses(db: Session, current: CurrentSession, *, keyword: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    require_lead_diagnosis_access(db, current, "can_export")
    stmt = (
        select(LeadDiagnosis)
        .where(LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
        .order_by(desc(LeadDiagnosis.id))
    )
    if status:
        stmt = stmt.where(LeadDiagnosis.status == status)
    if is_sales_identity(db, current.identity):
        stmt = stmt.where(LeadDiagnosis.created_by_user_id == current.user.id)
    rows = list(db.scalars(stmt))
    if keyword:
        needle = keyword.strip().lower()
        rows = [
            row for row in rows
            if needle in (row.brand_name or "").lower()
            or needle in (row.contact_name or "").lower()
            or needle in (row.contact_phone or "").lower()
        ]
    show_creator = can_view_lead_creator_info(db, current)
    creator_map = _creator_users_map(
        db,
        {row.created_by_user_id for row in rows if row.created_by_user_id},
    ) if show_creator else {}
    # 2026-08-07 - 列表「完成轮次」与监测任务对齐，避免不点刷新一直停在一轮
    for row in rows:
        if row.status in ACTIVE_STATUSES:
            _sync_lead_run_statuses_from_tasks(db, row)
    return [
        _serialize_lead(
            row,
            mask_contact=True,
            include_creator=show_creator,
            creator=creator_map.get(row.created_by_user_id) if row.created_by_user_id else None,
        )
        for row in rows
    ]


def get_lead_diagnosis(
    db: Session,
    lead_id: int,
    *,
    current: CurrentSession | None = None,
) -> dict[str, Any]:
    if current is not None:
        ensure_lead_diagnosis_owner_access_by_id(db, current, lead_id)
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    # 2026-08-07 - 打开详情即回写已完成轮次，勿等手动刷新
    if lead.status in ACTIVE_STATUSES:
        _sync_lead_run_statuses_from_tasks(db, lead)
        maybe_finalize_lead_diagnosis(db, lead_id)
        lead = _load_lead_diagnosis(db, lead_id) or lead
    show_creator = current is not None and can_view_lead_creator_info(db, current)
    creator = None
    if show_creator and lead.created_by_user_id:
        creator = db.get(User, lead.created_by_user_id)
    mask_contact = bool(current is not None and is_sales_identity(db, current.identity))
    return _serialize_lead(
        lead,
        include_result=True,
        mask_contact=mask_contact,
        include_creator=show_creator,
        creator=creator,
    )


def normalize_lead_brand_name(brand_name: str | None) -> str:
    return str(brand_name or "").strip().lower()


def find_recent_lead_diagnosis_by_brand(
    db: Session,
    *,
    user_id: int,
    brand_name: str,
    within_days: int = LEAD_DIAGNOSIS_CREATE_COOLDOWN_DAYS,
) -> LeadDiagnosis | None:
    """同一创建人、同一品牌名在冷却期内是否已有未取消的诊断记录。"""
    # 2026-08-04 - 已取消单仍占 7 天冷却，导致无法再提审/审批通过；canceled 不计入
    normalized = normalize_lead_brand_name(brand_name)
    if not normalized or not user_id:
        return None
    cutoff = datetime.now() - timedelta(days=max(1, within_days))
    return db.scalar(
        select(LeadDiagnosis)
        .where(
            LeadDiagnosis.deleted.is_(False),
            LeadDiagnosis.status != "canceled",
            LeadDiagnosis.created_by_user_id == user_id,
            func.lower(func.trim(LeadDiagnosis.brand_name)) == normalized,
            LeadDiagnosis.created_at >= cutoff,
        )
        .order_by(desc(LeadDiagnosis.id))
        .limit(1)
    )


def assert_lead_diagnosis_create_allowed(
    db: Session,
    current: CurrentSession,
    brand_name: str,
) -> None:
    existing = find_recent_lead_diagnosis_by_brand(
        db,
        user_id=current.user.id,
        brand_name=brand_name,
    )
    if existing is None:
        return
    created_at = existing.created_at.strftime("%Y-%m-%d %H:%M")
    raise ValueError(
        f"同一品牌 {LEAD_DIAGNOSIS_CREATE_COOLDOWN_DAYS} 天内只能创建一条售前诊断，"
        f"您已于 {created_at} 创建「{existing.brand_name}」（#{existing.id}）"
    )


def create_lead_diagnosis(
    db: Session,
    current: CurrentSession,
    payload: LeadDiagnosisCreateRequest,
    *,
    enforce_position_platforms: bool = True,
    enforce_region_grants: bool = True,
) -> dict[str, Any]:
    require_lead_diagnosis_access(db, current, "can_create")
    assert_lead_diagnosis_create_allowed(db, current, payload.brand_name)
    # 2026-08-04 - 审批人可勾全量可提交平台；审批回放不再按销售职位白名单拦截
    if enforce_position_platforms:
        assert_lead_platforms_allowed(db, current, list(payload.platforms))
    diagnosis_date = payload.diagnosis_date or date.today()
    # 2026-08-11 - 审批回放勿按申请人再剥地区 - 入队/修订时已按编辑人权限落正文
    region_codes = (
        sanitize_lead_region_codes_for_grants(db, current, payload.region_codes)
        if enforce_region_grants
        else normalize_region_codes(payload.region_codes)
    )
    lead = LeadDiagnosis(
        brand_name=payload.brand_name.strip(),
        contact_name=(payload.contact_name or "").strip() or None,
        contact_phone=(payload.contact_phone or "").strip() or None,
        contact_note=(payload.contact_note or "").strip() or None,
        # 2026-08-13 - 入口官网/行业/产品落库 lead_context_json，不再拼进 contact_note
        lead_context_json=payload.lead_context_dict(),
        # 2026-08-13 - 可选露出词落库，提交监测别名与聚合匹配共用
        brand_aliases_json=list(payload.brand_aliases or []),
        prompts_json=payload.prompts,
        competitors_json=payload.competitors,
        platforms_json=list(payload.platforms),
        region_codes_json=region_codes,
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        schedule_days=clamp_lead_schedule_days(payload.schedule_days),
        diagnosis_date=diagnosis_date,
        status="pending",
        created_by_user_id=current.user.id,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    if payload.start_immediately:
        lead.status = "collecting"
        db.commit()
        submit_due_lead_run(db, current, lead.id, force=False)

    return get_lead_diagnosis(db, lead.id, current=current)


def update_lead_diagnosis(
    db: Session,
    current: CurrentSession,
    lead_id: int,
    payload: LeadDiagnosisUpdateRequest,
) -> dict[str, Any]:
    require_lead_diagnosis_access(db, current, "can_create")
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    ensure_lead_diagnosis_owner_access(db, current, lead)
    if payload.contact_name is not None:
        lead.contact_name = payload.contact_name.strip() or None
    if payload.contact_phone is not None:
        lead.contact_phone = payload.contact_phone.strip() or None
    if payload.contact_note is not None:
        lead.contact_note = payload.contact_note.strip() or None
    db.commit()
    return get_lead_diagnosis(db, lead_id, current=current)


def cancel_lead_diagnosis(
    db: Session,
    current: CurrentSession,
    lead_id: int,
) -> dict[str, Any]:
    """取消进行中的售前诊断：不再进入后续自动/手动抓取。"""
    # 2026-08-04 - 售前诊断缺取消入口 - 状态改 canceled，踢出 ACTIVE 即停跑
    require_lead_diagnosis_access(db, current, "can_create")
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    ensure_lead_diagnosis_owner_access(db, current, lead)
    if lead.status not in ACTIVE_STATUSES:
        raise ValueError("当前诊断已结束或已取消，无法再取消")
    lead.status = "canceled"
    for run in lead.runs or []:
        if run.status in {"pending", "submitted"}:
            run.status = "skipped"
            run.error_message = (run.error_message or "").strip() or "诊断已取消，本场次不再执行"
    db.commit()
    return get_lead_diagnosis(db, lead_id, current=current)


def finalize_lead_diagnosis_early(
    db: Session,
    current: CurrentSession,
    lead_id: int,
) -> dict[str, Any]:
    """提前收官：跳过未执行场次，用已完成场次汇总并置 ready，可导出报告。"""
    # 2026-08-11 - 要等满计划才能出报告 - 支持中途收官，剩余场次标 skipped
    require_lead_diagnosis_access(db, current, "can_create")
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    ensure_lead_diagnosis_owner_access(db, current, lead)
    if lead.status not in ACTIVE_STATUSES:
        raise ValueError("当前诊断已结束或已取消，无法提前收官")

    _sync_lead_run_statuses_from_tasks(db, lead)
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")

    tasks = _task_map(db, lead)
    for run in lead.runs or []:
        if run.status != "submitted":
            continue
        task = tasks.get(run.task_id or "")
        if task is not None and task.status not in TERMINAL_STATUSES:
            raise ValueError("尚有场次正在抓取，请等当前场次结束后再提前收官")

    completed_runs = [run for run in (lead.runs or []) if run.status == "completed" and run.task_id]
    if not completed_runs:
        raise ValueError("至少需要完成一场抓取才能提前生成报告")

    for run in lead.runs or []:
        if run.status in {"pending", "submitted"}:
            run.status = "skipped"
            run.error_message = (run.error_message or "").strip() or "提前收官，本场次不再执行"

    existing_keys = {run.schedule_key for run in (lead.runs or [])}
    for _day, _slot, schedule_key, schedule_label, _region in _iter_schedule_plan(lead):
        if schedule_key in existing_keys:
            continue
        db.add(
            LeadDiagnosisRun(
                lead_diagnosis_id=lead.id,
                schedule_key=schedule_key,
                schedule_label=schedule_label,
                status="skipped",
                prompt_count=len(lead.prompts_json or []),
                platform_count=len(_platform_configs_for_lead(lead)),
                error_message="提前收官，本场次不再执行",
            )
        )
        existing_keys.add(schedule_key)

    db.flush()
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")

    task_ids = [run.task_id for run in (lead.runs or []) if run.status == "completed" and run.task_id]
    subtasks = _load_subtasks_by_task_ids(db, task_ids)
    usable = [item for item in subtasks if item.status in TERMINAL_STATUSES and item.answer_content]
    if not usable:
        raise ValueError("已完成场次尚无可用监测结果，无法生成报告")

    tasks = _task_map(db, lead)
    result = aggregate_lead_diagnosis(
        lead,
        subtasks,
        task_region_map=_task_region_map(tasks),
        db=db,
    )
    lead.diagnosis_result_json = result
    lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
    lead.status = "ready"
    db.commit()
    _kick_lead_export_pregenerate(lead_id)
    return get_lead_diagnosis(db, lead_id, current=current)


def _is_slot_due(
    day: date,
    slot: str,
    now: datetime,
    *,
    tolerance_minutes: int,
) -> bool:
    slot_time = _slot_time(slot)
    if slot_time is None:
        return False
    scheduled = datetime.combine(day, slot_time)
    if now < scheduled:
        return False
    return now <= scheduled + timedelta(minutes=tolerance_minutes)


def enumerate_due_lead_runs(
    db: Session,
    *,
    lead_id: int | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> Iterator[DueLeadRun]:
    now = now or datetime.now()
    tolerance = settings.schedule_tolerance_minutes
    stmt = (
        select(LeadDiagnosis)
        .where(LeadDiagnosis.deleted.is_(False), LeadDiagnosis.status.in_(ACTIVE_STATUSES))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead_id:
        stmt = stmt.where(LeadDiagnosis.id == lead_id)
    for lead in db.scalars(stmt):
        if lead.diagnosis_date > now.date():
            continue
        existing_keys = {
            run.schedule_key
            for run in (lead.runs or [])
            if lead_run_blocks_due(run, now=now)
        }
        for day, slot, schedule_key, schedule_label, region_code in _iter_schedule_plan(lead):
            if schedule_key in existing_keys:
                continue
            if force or _is_slot_due(day, slot, now, tolerance_minutes=tolerance):
                yield DueLeadRun(
                    lead_id=lead.id,
                    schedule_key=schedule_key,
                    schedule_label=schedule_label,
                    region_code=region_code,
                )


def submit_due_lead_run(
    db: Session,
    current: CurrentSession,
    lead_id: int,
    *,
    schedule_key: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    require_lead_diagnosis_access(db, current, "can_create")
    now = datetime.now()
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    ensure_lead_diagnosis_owner_access(db, current, lead)
    if lead.status not in ACTIVE_STATUSES:
        raise ValueError("当前诊断已结束，无法继续抓取")

    tasks = _task_map(db, lead)
    inflight = _active_inflight_run_count(lead, tasks)
    if inflight >= LEAD_MAX_PARALLEL_SUBMITS:
        raise ValueError(
            f"当前已有 {inflight} 个批次在抓取中，请等待至少一个完成后再提交（上限 {LEAD_MAX_PARALLEL_SUBMITS}）"
        )

    due_items = list(enumerate_due_lead_runs(db, lead_id=lead_id, force=force))
    if schedule_key:
        due_items = [item for item in due_items if item.schedule_key == schedule_key]
    if not due_items and force:
        existing_keys = {
            run.schedule_key
            for run in (lead.runs or [])
            if lead_run_blocks_due(run, now=now)
        }
        for _day, _slot, key, label, region_code in _iter_schedule_plan(lead):
            if schedule_key and key != schedule_key and not schedule_key.startswith(f"{key}-rg"):
                continue
            full_key, full_label = _append_region_to_schedule(key, label, region_code)
            if schedule_key and full_key != schedule_key:
                continue
            if full_key in existing_keys:
                continue
            if _slot_is_future(_day, _slot, now):
                if schedule_key:
                    raise ValueError("该时段尚未到点，请等待自动执行或补抓已错过的时段")
                continue
            due_items = [DueLeadRun(lead_id=lead.id, schedule_key=full_key, schedule_label=full_label, region_code=region_code)]
            break
    if not due_items:
        return {"status": "skipped", "message": "当前没有可提交的抓取窗口"}

    item = due_items[0]
    existing_run = db.scalar(
        select(LeadDiagnosisRun).where(
            LeadDiagnosisRun.lead_diagnosis_id == lead.id,
            LeadDiagnosisRun.schedule_key == item.schedule_key,
        )
    )
    if existing_run is not None and existing_run.task_id:
        linked_task = db.scalar(
            select(GeoMonitorTask).where(
                GeoMonitorTask.task_id == existing_run.task_id,
                GeoMonitorTask.deleted.is_(False),
            )
        )
        if linked_task is not None:
            terminal_failed = linked_task.status in {"failed", "stopped"} and not (linked_task.completed_items or 0)
            if not terminal_failed:
                if existing_run.status != "submitted":
                    existing_run.status = "submitted"
                    existing_run.error_message = None
                    db.commit()
                return {
                    "status": "submitted",
                    "schedule_key": existing_run.schedule_key,
                    "task_id": existing_run.task_id,
                    "message": None,
                }
            existing_run.task_id = None
    if existing_run is not None and lead_run_blocks_due(existing_run):
        return {"status": "skipped", "message": "该时段已提交"}

    platforms = _platform_configs_for_lead(lead)
    # 2026-08-13 - lead 无 tenant 资产别名时重算会把「艾迪亚传媒」判未提及；提交时带短名/别名
    request = MonitorTaskCreateRequest(
        monitor_keywords=lead.brand_name,
        monitor_keyword_aliases=[t for t in _lead_brand_terms(lead) if t != str(lead.brand_name or "").strip()],
        competitors=_competitor_payload(lead.competitors_json or []),
        prompts=lead.prompts_json or [],
        platforms=platforms,
        region_code=_lead_region_codes(lead, item.region_code),
    )
    if existing_run is not None and existing_run.status == "failed":
        run = existing_run
        run.status = "pending"
        run.error_message = None
        run.task_id = None
        run.prompt_count = len(request.prompts)
        run.platform_count = len(platforms)
    else:
        run = LeadDiagnosisRun(
            lead_diagnosis_id=lead.id,
            schedule_key=item.schedule_key,
            schedule_label=item.schedule_label,
            status="pending",
            prompt_count=len(request.prompts),
            platform_count=len(platforms),
        )
        db.add(run)
    db.flush()

    try:
        task = submit_standalone_monitor_task(
            db,
            payload=request,
            created_by=current.user.id,
            auto_commit=False,
        )
        run.task_id = task.task_id
        run.status = "submitted"
        lead.status = "collecting"
        db.commit()
        db.refresh(task)
    except (MolizhishuApiError, TimeoutError, OperationalError, SQLAlchemyError):
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = str(exc)
        db.commit()
    return {
        "status": run.status,
        "schedule_key": run.schedule_key,
        "task_id": run.task_id,
        "message": run.error_message,
    }


def persist_lead_run_failure(
    db: Session,
    *,
    lead_id: int,
    schedule_key: str,
    error_message: str,
) -> None:
    run = db.scalar(
        select(LeadDiagnosisRun).where(
            LeadDiagnosisRun.lead_diagnosis_id == lead_id,
            LeadDiagnosisRun.schedule_key == schedule_key,
        )
    )
    if run is None:
        run = LeadDiagnosisRun(
            lead_diagnosis_id=lead_id,
            schedule_key=schedule_key,
            status="failed",
            error_message=error_message,
        )
        db.add(run)
    else:
        run.status = "failed"
        run.error_message = error_message
    db.commit()


def _task_map(db: Session, lead: LeadDiagnosis) -> dict[str, GeoMonitorTask]:
    task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
    if not task_ids:
        return {}
    rows = list(db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.task_id.in_(task_ids))))
    return {row.task_id: row for row in rows}


def _run_status_from_terminal_task(task: GeoMonitorTask) -> tuple[str, str | None]:
    """监测任务已终态时，推导对应 LeadDiagnosisRun 状态与错误信息。"""
    if int(task.completed_items or 0) > 0:
        return "completed", None
    return "failed", (task.last_error or "监测任务未产生有效结果")


def _sync_lead_run_statuses_from_tasks(db: Session, lead: LeadDiagnosis, *, commit: bool = True) -> bool:
    """把已终态的监测任务回写到 LeadDiagnosisRun.status。

    2026-08-07 - 多轮已抓完页面仍显示一轮：列表/详情只读 run 表，不同步 task；
    仅手动 /refresh 才对齐。读路径与 Celery finalize 共用此回写。
    """
    tasks = _task_map(db, lead)
    changed = False
    for run in lead.runs or []:
        if run.status in RUN_TERMINAL or not run.task_id:
            continue
        task = tasks.get(run.task_id)
        if task is None:
            continue
        if task.status not in TERMINAL_STATUSES:
            continue
        new_status, err = _run_status_from_terminal_task(task)
        run.status = new_status
        if new_status == "failed" and not run.error_message:
            run.error_message = err
        changed = True
    if changed and commit:
        db.commit()
    return changed


def refresh_lead_diagnosis_runs(
    db: Session,
    lead_id: int,
    *,
    current: CurrentSession | None = None,
) -> dict[str, Any]:
    if current is not None:
        ensure_lead_diagnosis_owner_access_by_id(db, current, lead_id)
    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    _sync_lead_run_statuses_from_tasks(db, lead)
    maybe_finalize_lead_diagnosis(db, lead_id)
    return get_lead_diagnosis(db, lead_id, current=current)


def _all_slots_attempted(lead: LeadDiagnosis) -> bool:
    expected = _expected_schedule_keys(lead)
    attempted = {run.schedule_key for run in (lead.runs or [])}
    return expected.issubset(attempted)


def _completed_planned_run_count(lead: LeadDiagnosis) -> int:
    expected = _expected_schedule_keys(lead)
    return sum(
        1
        for item in (lead.runs or [])
        if item.status == "completed" and item.schedule_key in expected
    )


def _all_slots_completed(lead: LeadDiagnosis) -> bool:
    # 2026-08-21 - 计划外历史场次会让 completed==expected 永远失败、卡 collecting - 改为计划档均已完成即可
    expected = _expected_schedule_keys(lead)
    if not expected:
        return False
    completed = {run.schedule_key for run in (lead.runs or []) if run.status == "completed"}
    return expected.issubset(completed)


def _runs_terminal(lead: LeadDiagnosis, tasks: dict[str, GeoMonitorTask]) -> bool:
    expected = _expected_schedule_keys(lead)
    runs = [run for run in (lead.runs or []) if not expected or run.schedule_key in expected]
    for run in runs:
        if run.status in {"pending", "submitted"}:
            task = tasks.get(run.task_id or "")
            if task and task.status not in TERMINAL_STATUSES:
                return False
        if run.status == "pending":
            return False
    return bool(runs)


def maybe_finalize_lead_diagnosis(db: Session, lead_id: int) -> bool:
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None or lead.status not in ACTIVE_STATUSES:
        return False

    tasks = _task_map(db, lead)
    if not (
        _all_slots_attempted(lead)
        and _runs_terminal(lead, tasks)
        and _all_slots_completed(lead)
    ):
        return False

    subtasks = _load_subtasks(db, lead)
    if not subtasks:
        lead.status = "failed"
        db.commit()
        return True

    result = aggregate_lead_diagnosis(
        lead,
        subtasks,
        task_region_map=_task_region_map(tasks),
        db=db,
    )
    lead.diagnosis_result_json = result
    lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
    lead.status = "ready"
    db.commit()
    _kick_lead_export_pregenerate(lead_id)
    return True


def _kick_lead_export_pregenerate(lead_id: int) -> None:
    """ready 后异步预热导出；失败不影响主流程。"""
    try:
        from app.services.report_export_job_service import pregenerate_lead_diagnosis_exports

        pregenerate_lead_diagnosis_exports(int(lead_id))
    except Exception as exc:
        logger.warning("lead diagnosis export pregenerate failed lead_id=%s err=%s", lead_id, exc)


def refresh_lead_diagnosis_after_backfill(db: Session, task_id: str) -> None:
    """快照补录后刷新关联售前诊断的运行状态并重算聚合结果。"""
    run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task_id))
    if run is None:
        return

    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == run.lead_diagnosis_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None:
        return

    tasks = _task_map(db, lead)
    task = tasks.get(task_id)
    if task is not None and task.completed_items > 0 and run.status == "failed":
        run.status = "completed"
        run.error_message = None

    if lead.status not in ACTIVE_STATUSES and lead.status != "ready":
        db.commit()
        return

    if lead.status in ACTIVE_STATUSES:
        if maybe_finalize_lead_diagnosis(db, lead.id):
            return

    if lead.status == "ready":
        subtasks = _load_subtasks(db, lead)
        if not subtasks:
            db.commit()
            return
        result = aggregate_lead_diagnosis(
            lead,
            subtasks,
            task_region_map=_task_region_map(tasks),
            db=db,
        )
        lead.diagnosis_result_json = result
        lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
        db.commit()
        # 2026-08-07 - 补录重算后结果变了，重新预热导出指纹
        _kick_lead_export_pregenerate(lead.id)


def _load_subtasks_by_task_ids(db: Session, task_ids: list[str]) -> list[GeoMonitorSubtask]:
    if not task_ids:
        return []
    # 2026-07-30 - 1038 类风险 - 诊断聚合不依赖顺序，勿全行 ORDER BY 宽列 filesort
    return list(
        db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(task_ids)))
    )


def _load_subtasks(db: Session, lead: LeadDiagnosis) -> list[GeoMonitorSubtask]:
    task_ids = [run.task_id for run in (lead.runs or []) if run.task_id and run.status != "failed"]
    return _load_subtasks_by_task_ids(db, task_ids)


def _task_region_map(tasks: dict[str, GeoMonitorTask]) -> dict[str, list[str] | None]:
    return {task_id: task.region_code_json for task_id, task in tasks.items()}


def _lead_brand_terms(lead: LeadDiagnosis) -> list[str]:
    """售前品牌匹配词：全称 + 入口露出词 + 结果里别名 + 去后缀短名。

    2026-08-21 - 短别名/短码（如 SAB）虚抬格级 - 弱别名不进自动匹配
    """
    from app.schemas.lead_diagnosis import normalize_brand_aliases
    from app.services.lead_brand_match import is_weak_brand_alias, matchable_brand_terms

    raw: list[str] = []
    seen: set[str] = set()

    def _collect(value: str | None) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        raw.append(text)

    brand = str(lead.brand_name or "").strip()
    _collect(brand)
    for alias in normalize_brand_aliases(getattr(lead, "brand_aliases_json", None) or []):
        _collect(alias)
    stored = lead.diagnosis_result_json if isinstance(lead.diagnosis_result_json, dict) else {}
    for alias in normalize_brand_aliases(stored.get("brand_aliases") or []):
        _collect(alias)
    # 艾迪亚控股集团有限公司 → 艾迪亚控股集团 / 艾迪亚
    for suffix in ("有限公司", "股份有限公司", "集团有限公司", "控股集团有限公司", "集团"):
        if brand.endswith(suffix) and len(brand) > len(suffix) + 1:
            _collect(brand[: -len(suffix)].strip())
    if brand and len(brand) >= 3 and not is_weak_brand_alias(brand[:3]):
        _collect(brand[:3])
    return matchable_brand_terms(brand, raw)


def _effective_lead_mention_position(
    item: GeoMonitorSubtask,
    brand: str,
    brand_terms: list[str],
) -> float | None:
    """2026-08-13 - 售前热力全 —：聚合只读 mention_position，lead 无别名重算被清成空。
    对齐生产展示位次：信任已写 mention_position，否则走 _resolve_brand_rank（勿用 normalize 重编号）。
    2026-08-21 - 与样本表共用 resolve_subtask_brand_rank，避免两套判定。
    """
    from app.services.lead_brand_match import resolve_subtask_brand_rank

    return resolve_subtask_brand_rank(item, brand, brand_terms)


def aggregate_lead_diagnosis(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    *,
    task_region_map: dict[str, list[str] | None] | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    competitors = [str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()]
    if db is not None:
        competitors = resolve_lead_competitors(db, lead)
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES and item.answer_content]
    brand = str(lead.brand_name or "").strip()
    brand_terms = _lead_brand_terms(lead)
    # 2026-08-13 - 热力/KPI 改吃有效位次，勿只信可能被空别名洗掉的 mention_position
    effective_ranks: list[float] = []
    for item in completed:
        pos = _effective_lead_mention_position(item, brand, brand_terms)
        if pos is not None:
            effective_ranks.append(pos)
    mentioned_count = len(effective_ranks)
    top3_count = sum(1 for rank in effective_ranks if rank <= 3)

    sentiment_counts: dict[str, int] = {}
    for item in completed:
        key = (item.sentiment or "unknown").lower()
        sentiment_counts[key] = sentiment_counts.get(key, 0) + 1
    positive = sentiment_counts.get("positive", 0) + sentiment_counts.get("neutral", 0)
    positive_rate = round(positive / len(completed) * 100, 1) if completed else 0.0
    # 2026-08-14 - 负面率与驾驶舱一致：neg / 全样本（含 unknown），勿用已标注子集
    negative_rate = (
        round(sentiment_counts.get("negative", 0) / len(completed) * 100, 1) if completed else 0.0
    )

    mention_rate = round(mentioned_count / len(completed) * 100, 1) if completed else 0.0
    avg_rank = round(sum(effective_ranks) / len(effective_ranks), 1) if effective_ranks else None
    top3_rate = round(top3_count / len(completed) * 100, 1) if completed else 0.0

    platform_buckets: dict[str, dict[str, Any]] = {}
    matrix_cells: dict[str, dict[str, Any]] = {}
    source_map: dict[str, dict[str, Any]] = {}

    for item in completed:
        eff = _effective_lead_mention_position(item, brand, brand_terms)
        bucket = platform_buckets.setdefault(
            item.platform,
            {"platform": item.platform, "total": 0, "completed": 0, "mentioned": 0, "rank_total": 0.0, "rank_count": 0},
        )
        bucket["total"] += 1
        bucket["completed"] += 1
        if eff is not None:
            bucket["mentioned"] += 1
            bucket["rank_total"] += eff
            bucket["rank_count"] += 1

        cell_key = f"{item.prompt}::{item.platform}"
        cell = matrix_cells.setdefault(cell_key, {"prompt": item.prompt, "platform": item.platform, "ranks": [], "mentioned": 0, "total": 0})
        cell["total"] += 1
        if eff is not None:
            cell["mentioned"] += 1
            cell["ranks"].append(eff)

        for source in item.reference_list_json or []:
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            clean_title = sanitize_source_title(source.get("title") or source.get("site"), url=key)
            row = source_map.setdefault(
                key,
                {"title": clean_title, "url": url, "count": 0, "platforms": []},
            )
            row["count"] += 1
            if item.platform not in row["platforms"]:
                row["platforms"].append(item.platform)

    platform_stats = []
    for bucket in platform_buckets.values():
        total = bucket["total"] or 1
        platform_stats.append({
            "platform": bucket["platform"],
            "total": bucket["total"],
            "completed": bucket["completed"],
            "mention_rate": round(bucket["mentioned"] / total * 100, 1),
            "avg_rank": round(bucket["rank_total"] / bucket["rank_count"], 1) if bucket["rank_count"] else None,
        })
    platform_stats.sort(key=lambda row: row["mention_rate"], reverse=True)

    matrix_rows = []
    for cell in matrix_cells.values():
        ranks = cell["ranks"]
        # 2026-08-21 - mention_rate 实为格内回答命中率；对外主展示用 avg_rank/露出
        hit_rate = round(cell["mentioned"] / cell["total"] * 100, 1) if cell["total"] else 0.0
        matrix_rows.append({
            "prompt": cell["prompt"],
            "platform": cell["platform"],
            "sample_count": cell["total"],
            "mention_rate": hit_rate,
            "answer_hit_rate": hit_rate,
            "exposed": bool(ranks),
            "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
        })

    top_sources = consolidate_top_sources(list(source_map.values()), limit=12)
    plan_end = _plan_end_date(lead)
    schedule_round_count = len({run.schedule_key for run in (lead.runs or []) if run.status == "completed"})
    total_rounds = _schedule_total_count(lead)

    extended_analytics = build_lead_diagnosis_analytics(
        lead,
        subtasks,
        lead.runs or [],
        competitors=competitors,
        task_region_map=task_region_map,
    )
    # 2026-08-14 - 汇总后竞品以挖掘结果为准（空则仍是建单/企业库兜底）
    competitors = list(extended_analytics.get("competitors") or competitors)
    competitor_stats = list(extended_analytics.get("competitor_stats") or [])
    competitors_mined = list(extended_analytics.get("competitors_mined") or [])

    kpis = {
        "mention_rate": mention_rate,
        "avg_rank": avg_rank,
        "top3_rate": top3_rate,
        "positive_rate": positive_rate,
        "negative_rate": negative_rate,
        "completed_count": len(completed),
        "subtask_count": len(subtasks),
        "source_count": len(source_map),
        "task_count": len({item.task_id for item in completed}),
        "schedule_round_count": schedule_round_count,
    }
    health_score = _rule_health_score(kpis)
    rule_highlights = _rule_highlights(kpis, platform_stats)
    diagnosis_block = _rule_diagnosis_block(
        lead,
        kpis,
        rule_highlights,
        schedule_round_count=schedule_round_count,
        total_rounds=total_rounds,
    )
    report_sections = build_rule_report_sections(
        brand=lead.brand_name,
        competitors=extended_analytics.get("competitors") or [],
        prompt_analytics=extended_analytics.get("prompt_analytics") or [],
        source_analysis=extended_analytics.get("source_analysis") or {},
        kpis=kpis,
    )

    from app.services.molizhishu_catalog_service import get_supported_platform_catalog
    from app.services.report_enrichment_service import (
        build_report_enrichment,
        merge_priority_actions,
        merge_prompt_commentaries,
    )

    platform_names = {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }
    report_enrichment = build_report_enrichment(
        brand=lead.brand_name,
        competitors=competitors,
        prompt_analytics=extended_analytics.get("prompt_analytics") or [],
        matrix_rows=matrix_rows,
        platform_stats=platform_stats,
        platform_names=platform_names,
        source_analysis=extended_analytics.get("source_analysis") or {},
        top_sources=top_sources,
        subtasks=subtasks,
        sentiment_counts=sentiment_counts,
        positive_rate=positive_rate,
    )

    ai_insights: dict[str, Any] = {}
    analysis_html: str | None = None
    client = DeepseekClient()
    if client.report_enabled:
        try:
            ai = client.generate_report_insights(
                brand_name=lead.brand_name,
                company_name=lead.brand_name,
                report_type="diagnosis",
                period_label=f"{lead.diagnosis_date.isoformat()} 起 {_schedule_days(lead)} 天（{schedule_round_count}/{total_rounds} 次抓取均值）",
                kpis={**kpis, "health_score": health_score},
                platform_stats=platform_stats,
                top_sources=top_sources,
                sentiment_counts=sentiment_counts,
                competitor_names=competitors,
                rule_highlights=rule_highlights,
                lead_analytics=extended_analytics,
            )
            ai_insights = {
                "executive_summary": ai.get("executive_summary"),
                "highlights": ai.get("highlights") or rule_highlights,
            }
            if ai.get("report_sections"):
                report_sections = ai["report_sections"]
            analysis_html = ai.get("analysis_html")
            report_enrichment["prompt_commentaries"] = merge_prompt_commentaries(
                report_enrichment.get("prompt_commentaries") or [],
                ai.get("prompt_commentaries"),
            )
            if ai.get("platform_insight"):
                report_enrichment["platform_insight"] = ai["platform_insight"]
            ai_tips = ai.get("source_action_tips")
            if isinstance(ai_tips, list) and ai_tips:
                report_enrichment["source_action_tips"] = [
                    str(item).strip() for item in ai_tips if str(item).strip()
                ][:12]
            report_enrichment.pop("analysis_action_tips", None)
            if ai.get("analysis_html"):
                analysis_html = ai.get("analysis_html")
            report_enrichment["priority_actions"] = merge_priority_actions(
                report_enrichment.get("priority_actions") or [],
                ai.get("priority_actions"),
            )
            if ai.get("health_score") is not None:
                health_score = ai["health_score"]
            diagnosis_block.update({
                "sentiment_summary": ai.get("sentiment_summary") or diagnosis_block.get("sentiment_summary"),
                "strength_points": ai.get("strength_points") or diagnosis_block.get("strength_points"),
                "weakness_points": ai.get("weakness_points") or diagnosis_block.get("weakness_points"),
                "recommendation": ai.get("recommendation") or diagnosis_block.get("recommendation"),
                "health_score": health_score,
            })
        except (DeepseekApiError, RuntimeError):
            ai_insights = {"highlights": rule_highlights}
            analysis_html = None

    diagnosis_block["health_score"] = health_score
    kpis["health_score"] = health_score

    result_payload = {
        "brand_name": lead.brand_name,
        "company_name": lead.brand_name,
        # 2026-08-13 - 汇总结果带上入口露出词，报告/重算可复用
        "brand_aliases": list(getattr(lead, "brand_aliases_json", None) or []),
        "competitors": competitors,
        "competitors_mined": competitors_mined,
        "competitor_stats": competitor_stats,
        "period_label": (
            f"{lead.diagnosis_date.isoformat()} 至 {plan_end.isoformat()} · "
            f"{_schedule_days(lead)} 天 × 每日 {len(_schedule_slots(lead))} 档均值"
            f"（{schedule_round_count}/{total_rounds} 次有效抓取）"
        ),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kpis": kpis,
        "diagnosis": diagnosis_block,
        "ai_insights": ai_insights,
        "monitor_snapshot": {
            "highlights": ai_insights.get("highlights") or rule_highlights,
            "platform_stats": platform_stats,
            "top_sources": top_sources,
            "sentiment_counts": sentiment_counts,
            "matrix_rows": matrix_rows,
            "prompt_analytics": extended_analytics.get("prompt_analytics") or [],
            "source_analysis": extended_analytics.get("source_analysis") or {},
            "rank_trend": extended_analytics.get("rank_trend") or [],
            "tracked_entities": extended_analytics.get("tracked_entities") or [],
            "competitors": competitors,
            "competitors_mined": competitors_mined,
            "competitor_stats": competitor_stats,
            "brand_city_rankings": extended_analytics.get("brand_city_rankings") or [],
            "brand_date_matrix": extended_analytics.get("brand_date_matrix") or {},
            "brand_city_matrix": extended_analytics.get("brand_city_matrix") or {},
            "matrix_rows": matrix_rows,
            "report_enrichment": report_enrichment,
        },
        "report_enrichment": report_enrichment,
        "matrix_rows": matrix_rows,
        "report_sections": report_sections,
        "analysis_html": analysis_html,
        "runs": [_serialize_run(run) for run in sorted(lead.runs or [], key=lambda row: row.schedule_key)],
    }
    # 2026-08-13 - 方案 B - 收尾时一次生成驾驶舱叙事包
    try:
        from app.services.report_diagnosis_cockpit_service import ensure_cockpit_narrative

        result_payload = ensure_cockpit_narrative(result_payload)
    except Exception:
        pass
    return result_payload


def _rule_health_score(kpis: dict[str, Any]) -> int:
    mention = float(kpis.get("mention_rate") or 0)
    top3 = float(kpis.get("top3_rate") or 0)
    positive = float(kpis.get("positive_rate") or 0)
    avg_rank = kpis.get("avg_rank")
    rank_bonus = 0.0
    if avg_rank is not None:
        rank_bonus = max(0.0, 100.0 - float(avg_rank) * 12.0)
    score = mention * 0.35 + top3 * 0.25 + positive * 0.20 + rank_bonus * 0.20
    return max(0, min(100, int(round(score))))


def _rule_highlights(kpis: dict[str, Any], platform_stats: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"品牌提及率 {kpis.get('mention_rate')}%，Top3 露出率 {kpis.get('top3_rate')}%。",
        f"平均推荐排名 {kpis.get('avg_rank') or '—'}，共完成 {kpis.get('completed_count')} 条有效样本。",
    ]
    if platform_stats:
        best = platform_stats[0]
        lines.append(f"表现最好平台提及率 {best.get('mention_rate')}%。")
    return lines[:5]


def _rule_diagnosis_block(
    lead: LeadDiagnosis,
    kpis: dict[str, Any],
    highlights: list[str],
    *,
    schedule_round_count: int,
    total_rounds: int,
) -> dict[str, Any]:
    return {
        "diagnosis_title": f"{lead.brand_name} 售前品牌诊断",
        "health_score": _rule_health_score(kpis),
        "sentiment_summary": (
            f"基于 {schedule_round_count}/{total_rounds} 次抓取结果，"
            f"品牌整体提及率 {kpis.get('mention_rate')}%。"
        ),
        "strength_points": highlights[0] if highlights else "品牌已在部分 AI 平台获得露出。",
        "weakness_points": "部分平台/问题场景下排名与提及率仍有提升空间，建议补充权威信源与对比内容。",
        "recommendation": "建议签约后开启持续监测，针对低提及平台补充结构化内容与第三方引用。",
    }


def _schedule_from_monitor_task(task: GeoMonitorTask) -> tuple[str, str]:
    moment = task.created_at or datetime.now()
    return (
        moment.strftime("%Y%m%d-%H%M"),
        moment.strftime("%Y-%m-%d %H:%M"),
    )


def _completed_tenant_monitor_tasks(db: Session, tenant_id: int, *, max_rounds: int = 9) -> list[GeoMonitorTask]:
    tasks = list(
        db.scalars(
            select(GeoMonitorTask)
            .where(
                GeoMonitorTask.tenant_id == tenant_id,
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.status == "completed",
            )
            .order_by(GeoMonitorTask.created_at.asc())
        )
    )
    ready: list[GeoMonitorTask] = []
    for task in tasks:
        total = db.scalar(
            select(func.count())
            .select_from(GeoMonitorSubtask)
            .where(GeoMonitorSubtask.task_id == task.task_id)
        ) or 0
        completed = db.scalar(
            select(func.count())
            .select_from(GeoMonitorSubtask)
            .where(
                GeoMonitorSubtask.task_id == task.task_id,
                GeoMonitorSubtask.status == "completed",
            )
        ) or 0
        if total > 0 and completed == total:
            ready.append(task)
    return ready[-max_rounds:]


def find_tenant_lead_diagnosis(db: Session, tenant_id: int) -> LeadDiagnosis | None:
    """查找与企业监测数据关联、且已汇总的售前诊断记录。"""
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(
            LeadDiagnosis.converted_tenant_id == tenant_id,
            LeadDiagnosis.deleted.is_(False),
            LeadDiagnosis.status == "ready",
        )
        .order_by(desc(LeadDiagnosis.id))
        .limit(1)
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is not None:
        return lead

    return db.scalar(
        select(LeadDiagnosis)
        .join(LeadDiagnosisRun, LeadDiagnosisRun.lead_diagnosis_id == LeadDiagnosis.id)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == LeadDiagnosisRun.task_id)
        .where(
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.deleted.is_(False),
            LeadDiagnosis.deleted.is_(False),
            LeadDiagnosis.status == "ready",
        )
        .order_by(desc(LeadDiagnosis.id))
        .limit(1)
        .options(selectinload(LeadDiagnosis.runs))
    )


def _build_ephemeral_lead_from_tenant_tasks(
    db: Session,
    *,
    tenant_id: int,
    tenant: Tenant,
    asset: BrandAsset,
    tasks: list[GeoMonitorTask],
) -> LeadDiagnosis:
    prompts = list(
        dict.fromkeys(
            item
            for task in reversed(tasks)
            for item in (task.prompts_json or [])
            if str(item).strip()
        )
    )[:5]
    competitors = [
        row.name
        for row in db.scalars(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == tenant_id,
                BrandCompetitor.deleted.is_(False),
                BrandCompetitor.status.is_(True),
            )
        )
        if row.name
    ]
    platform_codes = filter_submittable_platforms(
        [str(item or "").strip() for item in (asset.monitored_platforms_json or [])]
    )
    if not platform_codes:
        platform_codes = filter_submittable_platforms(
            [
                str(code or "").strip()
                for task in tasks
                for item in (task.platforms_json or [])
                for code in (
                    [item.get("platform") if isinstance(item, dict) else item]
                )
            ]
        )
    lead = LeadDiagnosis(
        brand_name=(asset.brand_name or asset.company_full_name or tenant.name).strip(),
        contact_note=f"基于 {tenant.name} 历史监测数据（{len(tasks)} 轮已完成任务）",
        prompts_json=prompts,
        competitors_json=competitors[:10],
        platforms_json=platform_codes,
        region_codes_json=list(asset.region_codes_json or []),
        schedule_times_json=list(asset.schedule_times_json or DEFAULT_LEAD_SCHEDULE_TIMES),
        diagnosis_date=(tasks[0].created_at or datetime.now()).date(),
        status="ready",
        converted_tenant_id=tenant_id,
    )
    lead.runs = [
        LeadDiagnosisRun(
            lead_diagnosis_id=0,
            schedule_key=schedule_key,
            schedule_label=schedule_label,
            task_id=task.task_id,
            status="completed",
            prompt_count=len(task.prompts_json or []),
            platform_count=len(task.platforms_json or []),
        )
        for task in tasks
        for schedule_key, schedule_label in [_schedule_from_monitor_task(task)]
    ]
    return lead


def _task_region_map_for_task_ids(db: Session, task_ids: list[str]) -> dict[str, list[str] | None]:
    if not task_ids:
        return {}
    tasks = {
        row.task_id: row
        for row in db.scalars(
            select(GeoMonitorTask).where(
                GeoMonitorTask.task_id.in_(task_ids),
                GeoMonitorTask.deleted.is_(False),
            )
        )
    }
    return _task_region_map(tasks)


def aggregate_tenant_diagnosis(db: Session, tenant_id: int) -> dict[str, Any]:
    """与企业售前诊断导出共用 aggregate_lead_diagnosis 汇总链路。"""
    lead = find_tenant_lead_diagnosis(db, tenant_id)
    if lead is not None:
        subtasks = _load_subtasks(db, lead)
        if subtasks:
            task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
            return aggregate_lead_diagnosis(
                lead,
                subtasks,
                task_region_map=_task_region_map_for_task_ids(db, task_ids),
                db=db,
            )

    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError(f"企业不存在: tenant_id={tenant_id}")

    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))
    if asset is None:
        raise ValueError(f"企业 {tenant.name} 尚未配置品牌资产")

    tasks = _completed_tenant_monitor_tasks(db, tenant_id)
    if not tasks:
        raise ValueError(f"企业 {tenant.name} 没有全部完成的监测任务，无法生成诊断报告")

    ephemeral = _build_ephemeral_lead_from_tenant_tasks(
        db,
        tenant_id=tenant_id,
        tenant=tenant,
        asset=asset,
        tasks=tasks,
    )
    task_ids = [run.task_id for run in (ephemeral.runs or []) if run.task_id]
    subtasks = _load_subtasks_by_task_ids(db, task_ids)
    if not subtasks:
        raise ValueError("关联监测子任务为空，无法汇总诊断")

    return aggregate_lead_diagnosis(
        ephemeral,
        subtasks,
        task_region_map=_task_region_map_for_task_ids(db, task_ids),
        db=db,
    )


def import_tenant_lead_diagnosis(
    db: Session,
    *,
    tenant_id: int,
    contact_note: str | None = None,
    max_rounds: int = 9,
    created_by_user_id: int | None = None,
) -> LeadDiagnosis:
    """从企业已完成监测任务生成并持久化售前诊断（与 import 脚本同源）。"""
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError(f"企业不存在: tenant_id={tenant_id}")

    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))
    if asset is None:
        raise ValueError(f"企业 {tenant.name} 尚未配置品牌资产")

    tasks = _completed_tenant_monitor_tasks(db, tenant_id, max_rounds=max_rounds)
    if not tasks:
        raise ValueError(f"企业 {tenant.name} 没有全部完成的监测任务，无法生成诊断")

    prompts = list(
        dict.fromkeys(item for task in reversed(tasks) for item in (task.prompts_json or []) if str(item).strip())
    )[:5]
    if not prompts:
        raise ValueError("已完成监测任务中未找到检测问题")

    competitors = [
        row.name
        for row in db.scalars(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == tenant_id,
                BrandCompetitor.deleted.is_(False),
                BrandCompetitor.status.is_(True),
            )
        )
        if row.name
    ]

    platform_codes = filter_submittable_platforms(
        [str(item or "").strip() for item in (asset.monitored_platforms_json or [])]
    )
    if not platform_codes:
        platform_codes = filter_submittable_platforms(
            [
                str(code or "").strip()
                for task in tasks
                for item in (task.platforms_json or [])
                for code in (
                    [item.get("platform") if isinstance(item, dict) else item]
                )
            ]
        )

    lead = LeadDiagnosis(
        brand_name=(asset.brand_name or asset.company_full_name or tenant.name).strip(),
        contact_note=contact_note or f"基于 {tenant.name} 历史监测数据（{len(tasks)} 轮已完成任务）自动生成",
        prompts_json=prompts,
        competitors_json=competitors[:10],
        platforms_json=platform_codes,
        region_codes_json=list(asset.region_codes_json or []),
        schedule_times_json=list(asset.schedule_times_json or DEFAULT_LEAD_SCHEDULE_TIMES),
        diagnosis_date=tasks[0].created_at.date(),
        status="collecting",
        converted_tenant_id=tenant_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(lead)
    db.flush()

    for task in tasks:
        schedule_key, schedule_label = _schedule_from_monitor_task(task)
        db.add(
            LeadDiagnosisRun(
                lead_diagnosis_id=lead.id,
                schedule_key=schedule_key,
                schedule_label=schedule_label,
                task_id=task.task_id,
                status="completed",
                prompt_count=len(task.prompts_json or []),
                platform_count=len(task.platforms_json or []),
            )
        )

    db.commit()
    db.refresh(lead)

    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead.id)
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None:
        raise ValueError("售前诊断创建失败")

    subtasks = _load_subtasks(db, lead)
    if not subtasks:
        lead.status = "failed"
        db.commit()
        raise ValueError("关联监测子任务为空，无法汇总")

    task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
    result = aggregate_lead_diagnosis(
        lead,
        subtasks,
        task_region_map=_task_region_map_for_task_ids(db, task_ids),
        db=db,
    )
    lead.diagnosis_result_json = result
    lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
    lead.status = "ready"
    db.commit()
    db.refresh(lead)
    _kick_lead_export_pregenerate(lead.id)
    return lead


def build_lead_diagnosis_export(
    db: Session,
    lead_id: int,
    export_format: str = "html",
    *,
    current: CurrentSession | None = None,
) -> tuple[bytes, str, str]:
    report = _build_lead_diagnosis_report_payload(db, lead_id, current=current)
    from app.services.report_export_service import build_report_export

    fmt = _resolve_lead_export_format(export_format)
    return build_report_export(report, fmt, db=db)


def build_lead_diagnosis_preview_html(
    db: Session,
    lead_id: int,
    *,
    current: CurrentSession | None = None,
) -> str:
    """售前诊断在线预览：与 HTML 下载同源驾驶舱模板。

    2026-08-12 - 售前详情改 iframe 驾驶舱 - 预览走 cockpit，不再依赖 Vue 结论页
    """
    report = _build_lead_diagnosis_report_payload(db, lead_id, current=current)
    from app.services.report_export_service import build_report_html_preview

    return build_report_html_preview(db, report)


def _build_lead_diagnosis_report_payload(
    db: Session,
    lead_id: int,
    *,
    current: CurrentSession | None = None,
) -> dict[str, Any]:
    detail = get_lead_diagnosis(db, lead_id, current=current)
    if detail.get("status") != "ready":
        raise ValueError("诊断尚未完成，暂无法导出")
    result = dict(detail.get("diagnosis_result") or {})
    # 导出前用现算日均覆盖快照时段行，并写回，避免反复吃旧 cache
    result = _refresh_diagnosis_daily_ranks_for_export(db, lead_id, result)
    # 2026-08-13 - 方案 B - 旧 ready 单缺叙事包时懒生成并落库，避免每次预览重打 DeepSeek
    if not (isinstance(result.get("cockpit_narrative"), dict) and result["cockpit_narrative"].get("stage_copy")):
        try:
            from app.services.report_diagnosis_cockpit_service import ensure_cockpit_narrative

            enriched = ensure_cockpit_narrative(
                {
                    **result,
                    "brand_name": detail.get("brand_name") or result.get("brand_name"),
                    "competitors": detail.get("competitors") or result.get("competitors") or [],
                }
            )
            narrative = enriched.get("cockpit_narrative")
            if isinstance(narrative, dict) and narrative.get("stage_copy"):
                result["cockpit_narrative"] = narrative
                lead = _load_lead_diagnosis(db, lead_id)
                if lead is not None:
                    from sqlalchemy.orm.attributes import flag_modified

                    stored = dict(lead.diagnosis_result_json or {})
                    stored["cockpit_narrative"] = narrative
                    lead.diagnosis_result_json = stored
                    flag_modified(lead, "diagnosis_result_json")
                    db.add(lead)
                    db.commit()
        except Exception:
            pass
    # 2026-08-13 - 报告链路透传入口上下文，供 cockpit HTML 的 lead_context/input_context
    lead_ctx = normalize_lead_context(detail.get("lead_context"))
    # 2026-08-13 - 问法×平台快照证据（审计层，不参与 KPI）
    snapshot_evidence = _build_lead_snapshot_evidence(db, lead_id)
    return {
        "report_title": _lead_diagnosis_report_title(detail, result),
        "report_type": "diagnosis",
        "report_type_label": "售前诊断",
        "status_label": "已完成",
        "tenant_name": detail["brand_name"],
        "data_summary": result.get("diagnosis", {}).get("sentiment_summary"),
        "created_at": detail.get("created_at"),
        "updated_at": detail.get("updated_at") or detail.get("created_at"),
        "id": lead_id,
        "report_content": {
            **result,
            "contact_phone": detail.get("contact_phone"),
            "contact_name": detail.get("contact_name"),
            # 2026-08-14 - 导出优先用汇总挖掘竞品，勿被建单 competitors 盖掉
            "competitors": result.get("competitors") or detail.get("competitors") or [],
            "competitor_stats": result.get("competitor_stats") or [],
            "competitors_mined": result.get("competitors_mined") or [],
            "lead_context": lead_ctx,
            "input_context": lead_ctx,
            "snapshot_evidence": snapshot_evidence,
        },
    }


def _build_lead_snapshot_evidence(db: Session, lead_id: int) -> dict[str, dict[str, Any]]:
    """从已完成场次子任务提取问法×平台快照/摘要。key = prompt||canonical_slot。"""
    from app.services.report_diagnosis_cockpit_service import _canonical_platform

    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        return {}
    task_ids = [r.task_id for r in (lead.runs or []) if r.task_id and r.status == "completed"]
    if not task_ids:
        # 提前收官：也吃有答案的 submitted/completed 任务
        task_ids = [r.task_id for r in (lead.runs or []) if r.task_id]
    if not task_ids:
        return {}
    rows = list(
        db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(task_ids)))
    )
    out: dict[str, dict[str, Any]] = {}
    for st in rows:
        prompt = str(st.prompt or "").strip()
        slot = _canonical_platform(str(st.platform or ""))
        if not prompt or not slot:
            continue
        key = f"{prompt}||{slot}"
        answer = str(st.answer_content or "").strip()
        shot = str(st.page_screenshot or "").strip()
        raw = st.raw_result_json if isinstance(st.raw_result_json, dict) else {}
        share = ""
        for cand in (
            raw.get("share_url"),
            raw.get("snapshot_url"),
            raw.get("page_url"),
            (raw.get("result") or {}).get("share_url") if isinstance(raw.get("result"), dict) else None,
        ):
            if cand and str(cand).strip().startswith("http"):
                share = str(cand).strip()
                break
        refs: list[str] = []
        for lst_name in ("citation_list_json", "reference_list_json"):
            lst = getattr(st, lst_name, None)
            if isinstance(lst, list):
                for item in lst[:8]:
                    if isinstance(item, dict):
                        u = str(item.get("url") or item.get("link") or "").strip()
                    else:
                        u = str(item or "").strip()
                    if u.startswith("http") and u not in refs:
                        refs.append(u)
        # 优先保留已有更完整的条目
        prev = out.get(key) or {}
        if prev.get("share_url") and not share and not answer:
            continue
        summary = answer[:400] if answer else str(prev.get("answer_summary") or "")
        out[key] = {
            "share_url": share or str(prev.get("share_url") or ""),
            "snapshot_url": share or str(prev.get("snapshot_url") or ""),
            "page_screenshot": shot or str(prev.get("page_screenshot") or ""),
            "screenshot_url": shot or str(prev.get("screenshot_url") or ""),
            "answer_summary": summary,
            "references": refs or list(prev.get("references") or []),
        }
    return out


def _lead_diagnosis_report_title(detail: dict[str, Any], result: dict[str, Any]) -> str:
    """文件名带平台版本：SAB伟星拉链_豆包+ChatGPT综合_售前品牌诊断报告。"""
    from app.services.molizhishu_catalog_service import get_supported_platform_catalog
    from app.services.report_diagnosis_cockpit_service import diagnosis_export_title

    catalog = {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }
    labels: list[str] = []
    for row in result.get("platform_stats") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("platform") or "").strip()
        if code:
            labels.append(catalog.get(code) or code)
    if not labels:
        for code in detail.get("platforms") or []:
            c = str(code or "").strip()
            if c:
                labels.append(catalog.get(c) or c)
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for name in labels:
        if name in seen:
            continue
        seen.add(name)
        uniq.append(name)
    brand = str(detail.get("brand_name") or result.get("brand_name") or "品牌").strip()
    return diagnosis_export_title(brand, uniq)


def _refresh_diagnosis_daily_ranks_for_export(
    db: Session,
    lead_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    from app.services.lead_diagnosis_analytics import refresh_daily_rank_fields_in_diagnosis_result

    lead = _load_lead_diagnosis(db, lead_id)
    if lead is None:
        raise ValueError("售前诊断不存在")
    subtasks = _load_subtasks(db, lead)
    task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
    refreshed = refresh_daily_rank_fields_in_diagnosis_result(
        lead,
        subtasks,
        result,
        competitors=[str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()],
        task_region_map=_task_region_map_for_task_ids(db, task_ids),
    )
    lead.diagnosis_result_json = refreshed
    flag_modified(lead, "diagnosis_result_json")
    db.commit()
    return refreshed


def _resolve_lead_export_format(export_format: str) -> str:
    """2026-08-24 - 产品仅保留 HTML 下载。"""
    normalized = (export_format or "html").lower()
    if normalized != "html":
        raise ValueError("售前诊断仅支持 HTML 导出")
    return "html"


def _resolve_export_format(export_format: str) -> str:
    normalized = (export_format or "pdf").lower()
    if normalized in {"pdf", "docx", "html"}:
        return normalized
    raise ValueError(f"不支持的导出格式: {export_format}")


def finalize_due_lead_diagnoses(db: Session) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(LeadDiagnosis)
            .where(LeadDiagnosis.deleted.is_(False), LeadDiagnosis.status.in_(ACTIVE_STATUSES))
            .options(selectinload(LeadDiagnosis.runs))
        )
    )
    finalized = 0
    for lead in rows:
        # 2026-08-07 - finalize 前先回写 run，否则 task 已完成仍卡在 submitted
        _sync_lead_run_statuses_from_tasks(db, lead)
        if maybe_finalize_lead_diagnosis(db, lead.id):
            finalized += 1
    return {"finalized": finalized, "checked": len(rows)}
