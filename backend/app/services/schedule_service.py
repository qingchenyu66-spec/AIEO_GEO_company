from datetime import date, datetime, time
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.monitor import GeoMonitorScheduleRun
from app.models.tenant import Tenant
from app.schemas.monitor import MonitorTaskCreateRequest, PlatformConfig
from app.services.brand_service import active_keyword_groups, keyword_group_monitor_keywords, molizhishu_monitor_terms
from app.services.molizhishu_platforms import filter_submittable_platforms
from app.services.monitor_service import serialize_task, submit_monitor_task
from app.services.platform_matrix_service import prepare_daily_platform_matrix_before_submit


DEFAULT_DAILY_WINDOW_START = time(hour=9, minute=30)
DEFAULT_DAILY_WINDOW_END = time(hour=20, minute=30)


def _active_asset_stmt():
    """只调度服务期内、启用中的企业品牌资产。"""
    today = date.today()
    return (
        select(BrandAsset)
        .join(Tenant, Tenant.id == BrandAsset.tenant_id)
        .where(
            BrandAsset.deleted.is_(False),
            BrandAsset.status.is_(True),
            Tenant.deleted.is_(False),
            Tenant.status.is_(True),
            or_(Tenant.service_start_date.is_(None), Tenant.service_start_date <= today),
            or_(Tenant.service_end_date.is_(None), Tenant.service_end_date >= today),
        )
        .order_by(BrandAsset.tenant_id.asc())
    )


def _dedupe_text(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = (value or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        result.append(text)
    return result


def _parse_hhmm(value: str) -> time | None:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except (ValueError, TypeError):
        return None


def _even_daily_times(frequency: int) -> list[time]:
    count = max(1, min(int(frequency or 1), 24))
    start_minutes = DEFAULT_DAILY_WINDOW_START.hour * 60 + DEFAULT_DAILY_WINDOW_START.minute
    end_minutes = DEFAULT_DAILY_WINDOW_END.hour * 60 + DEFAULT_DAILY_WINDOW_END.minute
    if count == 1:
        return [DEFAULT_DAILY_WINDOW_START]
    step = (end_minutes - start_minutes) / (count - 1)
    return [
        time(hour=int((start_minutes + step * index) // 60), minute=int((start_minutes + step * index) % 60))
        for index in range(count)
    ]


def schedule_times_for_asset(asset: BrandAsset) -> list[time]:
    configured = [_parse_hhmm(item) for item in (asset.schedule_times_json or [])]
    configured_times = [item for item in configured if item is not None]
    if asset.schedule_type == "daily_times":
        return configured_times or _even_daily_times(asset.schedule_frequency)
    return configured_times or [DEFAULT_DAILY_WINDOW_START]


def matched_schedule_key(asset: BrandAsset, now: datetime, tolerance_minutes: int = 20, *, force: bool = False) -> str | None:
    if not force and asset.schedule_type == "weekly" and now.isoweekday() not in (asset.schedule_weekdays_json or []):
        return None
    if not force and asset.schedule_type == "monthly" and now.day not in (asset.schedule_month_days_json or []):
        return None
    if force:
        return now.strftime("%Y%m%d-%H%M")
    current_minutes = now.hour * 60 + now.minute
    for slot in schedule_times_for_asset(asset):
        slot_minutes = slot.hour * 60 + slot.minute
        if 0 <= current_minutes - slot_minutes <= tolerance_minutes:
            return f"{now:%Y%m%d}-{slot.hour:02d}{slot.minute:02d}"
    return None


def build_scheduled_prompts(
    asset: BrandAsset,
    competitors: list[BrandCompetitor],
    max_prompts: int = 50,
    keyword_group: dict[str, Any] | None = None,
) -> list[str]:
    """检测问题直接使用词组内的监测关键词，不再套用模板生成。"""
    del asset, competitors
    return _dedupe_text(keyword_group_monitor_keywords(keyword_group))[:max_prompts]


def build_scheduled_payload(
    db: Session,
    asset: BrandAsset,
    competitors: list[BrandCompetitor],
    max_prompts: int = 50,
    keyword_group: dict[str, Any] | None = None,
) -> MonitorTaskCreateRequest:
    prompts = build_scheduled_prompts(asset, competitors, max_prompts=max_prompts, keyword_group=keyword_group)
    platforms = [
        PlatformConfig(platform=code, mode="standard", screenshot=1)
        for code in filter_submittable_platforms(asset.monitored_platforms_json)
    ]
    monitor_keyword, aliases = molizhishu_monitor_terms(db, asset.tenant_id, keyword_group=keyword_group)
    return MonitorTaskCreateRequest(
        tenant_id=asset.tenant_id,
        prompts=prompts,
        platforms=platforms,
        monitor_keywords=monitor_keyword,
        monitor_keyword_aliases=aliases,
        region_code=[asset.region_code] if asset.region_code else None,
    )


def preview_scheduled_tasks(db: Session, *, tenant_id: int | None = None, max_prompts: int = 50) -> list[dict[str, Any]]:
    stmt = _active_asset_stmt()
    if tenant_id:
        stmt = stmt.where(BrandAsset.tenant_id == tenant_id)
    tenant_map = {item.id: item.name for item in db.scalars(select(Tenant).where(Tenant.deleted.is_(False)))}
    result: list[dict[str, Any]] = []
    for asset in db.scalars(stmt):
        competitors = list(db.scalars(select(BrandCompetitor).where(BrandCompetitor.tenant_id == asset.tenant_id, BrandCompetitor.deleted.is_(False))))
        keyword_groups = active_keyword_groups(db, asset.tenant_id)
        group_count = max(1, len(keyword_groups))
        per_group_max_prompts = max(1, max_prompts // group_count)
        platforms = [
            PlatformConfig(platform=code, mode="standard", screenshot=1)
            for code in filter_submittable_platforms(asset.monitored_platforms_json)
        ]
        platform_count = len(platforms)
        group_previews: list[dict[str, Any]] = []
        for group in keyword_groups:
            prompts = build_scheduled_prompts(asset, competitors, max_prompts=per_group_max_prompts, keyword_group=group)
            group_previews.append({
                "monitor_keyword": group.get("monitor_keyword"),
                "exposure_terms": group.get("exposure_terms") or [],
                "prompt_limit": per_group_max_prompts,
                "prompt_count": len(prompts),
                "prompts": prompts,
                "subtask_count": len(prompts) * platform_count,
            })
        total_prompts = sum(item["prompt_count"] for item in group_previews)
        total_subtasks = sum(item["subtask_count"] for item in group_previews)
        all_prompts = [prompt for group in group_previews for prompt in group["prompts"]]
        result.append({
            "tenant_id": asset.tenant_id,
            "tenant_name": tenant_map.get(asset.tenant_id) or asset.company_full_name,
            "brand_name": asset.brand_name,
            "region_code": asset.region_code,
            "schedule_type": asset.schedule_type,
            "schedule_times": [item.strftime("%H:%M") for item in schedule_times_for_asset(asset)],
            "max_prompts_total": max_prompts,
            "max_prompts_per_group": per_group_max_prompts,
            "keyword_group_count": len(keyword_groups),
            "tasks_per_schedule_window": len(keyword_groups),
            "platform_count": platform_count,
            "platforms": [item.model_dump() for item in platforms],
            "prompt_count": total_prompts,
            "unique_prompt_count": len(set(all_prompts)),
            "subtask_count_per_window": total_subtasks,
            "prompts": all_prompts,
            "keyword_groups": group_previews,
            "competitor_count": len(competitors),
        })
    return result


def run_due_scheduled_tasks(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    limit: int = 10,
    max_prompts: int = 50,
    force: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now()
    stmt = _active_asset_stmt()
    if tenant_id:
        stmt = stmt.where(BrandAsset.tenant_id == tenant_id)
    results: list[dict[str, Any]] = []
    for asset in db.scalars(stmt):
        if len(results) >= limit:
            break
        schedule_key = matched_schedule_key(asset, now, force=force)
        if not schedule_key:
            continue
        competitors = list(db.scalars(select(BrandCompetitor).where(BrandCompetitor.tenant_id == asset.tenant_id, BrandCompetitor.deleted.is_(False))))
        keyword_groups = active_keyword_groups(db, asset.tenant_id)
        per_group_max_prompts = max(1, max_prompts // max(1, len(keyword_groups)))
        for group in keyword_groups:
            group_key = f"{schedule_key}-kw{group.get('id') or group.get('sort_order', 0)}"
            if db.scalar(select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.tenant_id == asset.tenant_id, GeoMonitorScheduleRun.schedule_key == group_key)):
                results.append({"tenant_id": asset.tenant_id, "schedule_key": group_key, "status": "skipped", "message": "该调度窗口已执行"})
                continue
            payload = build_scheduled_payload(db, asset, competitors, max_prompts=per_group_max_prompts, keyword_group=group)
            run = GeoMonitorScheduleRun(
                tenant_id=asset.tenant_id,
                schedule_key=group_key,
                status="running",
                prompt_count=len(payload.prompts),
                platform_count=len(payload.platforms),
                created_by=current.user.id,
            )
            db.add(run)
            try:
                db.flush()
                if not payload.prompts:
                    raise ValueError("企业未配置可生成检测问题的监测词或竞品")
                if not payload.platforms:
                    raise ValueError("企业未配置已购买或允许监测的模型平台")
                prepare_daily_platform_matrix_before_submit(
                    db,
                    tenant_id=asset.tenant_id,
                    schedule_key=group_key,
                )
                task = submit_monitor_task(db, payload, current)
                run.task_id = task.task_id
                run.status = "submitted"
                db.commit()
                results.append({"tenant_id": asset.tenant_id, "schedule_key": group_key, "status": "submitted", "keyword": group.get("monitor_keyword"), "task": serialize_task(task)})
            except (IntegrityError, ValueError, RuntimeError) as exc:
                db.rollback()
                failed = GeoMonitorScheduleRun(
                    tenant_id=asset.tenant_id,
                    schedule_key=group_key,
                    status="failed",
                    prompt_count=len(payload.prompts),
                    platform_count=len(payload.platforms),
                    error_message=str(exc),
                    created_by=current.user.id,
                )
                db.add(failed)
                db.commit()
                results.append({"tenant_id": asset.tenant_id, "schedule_key": group_key, "status": "failed", "keyword": group.get("monitor_keyword"), "message": str(exc)})
    return results
