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
from app.services.brand_service import active_keyword_groups
from app.services.monitor_service import serialize_task, submit_monitor_task


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
    group_keyword = (keyword_group or {}).get("monitor_keyword")
    group_terms = (keyword_group or {}).get("exposure_terms") or []
    subject = (asset.company_full_name or "").strip() or (asset.brand_name or "").strip()
    brand_terms = _dedupe_text([asset.brand_name, asset.brand_short_name, asset.company_full_name, *group_terms, *(asset.aliases_json or [])])
    product_terms = _dedupe_text([group_keyword, *(asset.product_keywords_json or []), *(asset.monitor_keywords_json or [])])
    competitor_names = _dedupe_text([item.name for item in competitors if item.status and not item.deleted])
    prompts: list[str] = []
    if subject:
        prompts.extend([
            f"{subject}是做什么的？",
            f"{subject}这家公司怎么样？",
            f"{subject}值得推荐吗？",
            f"{subject}有哪些优势和不足？",
        ])
    for term in product_terms[:12]:
        prompts.append(f"{term}相关公司推荐有哪些？")
        if subject:
            prompts.append(f"{subject}在{term}领域表现怎么样？")
    for competitor in competitor_names[:12]:
        if subject:
            prompts.append(f"{subject}和{competitor}对比哪个好？")
            prompts.append(f"{subject}、{competitor}分别适合什么企业？")
    for term in brand_terms[:8]:
        prompts.append(f"{term}的口碑评价怎么样？")
    return _dedupe_text(prompts)[:max_prompts]


def build_scheduled_payload(
    asset: BrandAsset,
    competitors: list[BrandCompetitor],
    max_prompts: int = 50,
    keyword_group: dict[str, Any] | None = None,
) -> MonitorTaskCreateRequest:
    prompts = build_scheduled_prompts(asset, competitors, max_prompts=max_prompts, keyword_group=keyword_group)
    platforms = [
        PlatformConfig(platform=code, mode="search", screenshot=1)
        for code in (asset.monitored_platforms_json or [])
        if str(code).strip()
    ]
    return MonitorTaskCreateRequest(
        tenant_id=asset.tenant_id,
        prompts=prompts,
        platforms=platforms,
        monitor_keywords=(keyword_group or {}).get("monitor_keyword") or asset.brand_name,
        monitor_keyword_aliases=(keyword_group or {}).get("exposure_terms") or asset.aliases_json or [],
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
        per_group_max_prompts = max(1, max_prompts // max(1, len(keyword_groups)))
        payloads = [build_scheduled_payload(asset, competitors, max_prompts=per_group_max_prompts, keyword_group=group) for group in keyword_groups]
        result.append({
            "tenant_id": asset.tenant_id,
            "tenant_name": tenant_map.get(asset.tenant_id) or asset.company_full_name,
            "brand_name": asset.brand_name,
            "region_code": asset.region_code,
            "schedule_type": asset.schedule_type,
            "schedule_times": [item.strftime("%H:%M") for item in schedule_times_for_asset(asset)],
            "keyword_group_count": len(keyword_groups),
            "platforms": [item.model_dump() for item in payloads[0].platforms] if payloads else [],
            "prompt_count": sum(len(payload.prompts) for payload in payloads),
            "prompts": [prompt for payload in payloads for prompt in payload.prompts],
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
            payload = build_scheduled_payload(asset, competitors, max_prompts=per_group_max_prompts, keyword_group=group)
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
