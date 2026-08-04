from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator

from kombu.exceptions import OperationalError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorTask
from app.models.tenant import Tenant
from app.schemas.monitor import FAST_MONITOR_MODE, MonitorTaskCreateRequest, PlatformConfig
from app.services.brand_service import (
    active_brand_word_groups,
    active_keyword_groups,
    keyword_group_monitor_keywords,
    keyword_group_platforms,
    molizhishu_monitor_terms,
)
from app.services.molizhishu_client import MolizhishuApiError
from app.services.molizhishu_platforms import filter_submittable_platforms
from app.services.monitor_service import serialize_task, submit_monitor_task
from app.services.platform_matrix_service import prepare_daily_platform_matrix_before_submit
from app.core.region_catalog import normalize_region_codes, region_submission_targets


DEFAULT_DAILY_WINDOW_START = time(hour=9, minute=30)
DEFAULT_DAILY_WINDOW_END = time(hour=20, minute=30)
SCHEDULE_RUN_SUCCESS_STATUSES = frozenset({"submitted"})
SCHEDULE_RUN_STALE_RUNNING_MINUTES = 10
_SCHEDULE_TRANSIENT_ERRORS = (MolizhishuApiError, TimeoutError, OperationalError)


@dataclass(frozen=True)
class DueScheduleGroup:
    tenant_id: int
    schedule_key: str
    group_key: str
    max_prompts: int
    keyword: str | None = None
    region_code: str | None = None


def _keyword_group_suffix(group: dict[str, Any]) -> str:
    return str(group.get("id") or group.get("sort_order", 0))


def is_brand_word_schedule_key(group_key: str) -> bool:
    """品牌词调度 key：bw* / bwonce*。"""
    return str(group_key or "").startswith("bw")


def brand_word_weekly_schedule_key(now: datetime | None = None) -> str:
    """每周一固定窗口 key（约 09:00）。"""
    now = now or datetime.now()
    return f"bw{now:%Y%m%d}-0900"


def brand_word_once_schedule_key(now: datetime | None = None) -> str:
    """仅本次：按保存时刻生成唯一窗口，避免与周调度撞车。"""
    now = now or datetime.now()
    return f"bwonce-{now:%Y%m%d%H%M%S}"


def brand_word_service_start_schedule_key(anchor: date | None = None) -> str:
    """服务开始首跑窗口：按开始日（或当天）去重，避免 Beat 重复打。"""
    day = anchor or date.today()
    return f"bwstart-{day.isoformat().replace('-', '')}"


def enumerate_brand_word_service_start_groups(
    db: Session,
    *,
    tenant_id: int,
    max_prompts: int = 50,
    now: datetime | None = None,
) -> Iterator[DueScheduleGroup]:
    """服务开始首跑：启用中的 once + weekly 品牌词各提交一轮。"""
    # 2026-08-03 - 到点开跑；once 仅此轮，weekly 之后仍走周一 Beat
    now = now or datetime.now()
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        return
    from app.services.tenant_account_service import tenant_service_is_operational

    if not tenant_service_is_operational(tenant, today=now.date()):
        return
    asset = db.scalar(
        select(BrandAsset).where(
            BrandAsset.tenant_id == tenant_id,
            BrandAsset.deleted.is_(False),
            BrandAsset.status.is_(True),
        )
    )
    if asset is None:
        return
    keyword_groups = active_brand_word_groups(db, tenant_id)
    if not keyword_groups:
        return
    schedule_key = brand_word_service_start_schedule_key(tenant.service_start_date or now.date())
    per_group_max_prompts = max(1, max_prompts // max(1, len(keyword_groups)))
    for group in keyword_groups:
        for region_code in region_submission_targets(asset.region_codes_json):
            region_suffix = f"-rg{region_code}" if region_code else ""
            group_key = f"{schedule_key}-kw{_keyword_group_suffix(group)}{region_suffix}"
            if schedule_run_blocks_due(get_schedule_run(db, tenant_id, group_key), now=now):
                continue
            yield DueScheduleGroup(
                tenant_id=tenant_id,
                schedule_key=schedule_key,
                group_key=group_key,
                max_prompts=per_group_max_prompts,
                keyword=group.get("monitor_keyword"),
                region_code=region_code,
            )


def get_schedule_run(db: Session, tenant_id: int, group_key: str) -> GeoMonitorScheduleRun | None:
    return db.scalar(
        select(GeoMonitorScheduleRun).where(
            GeoMonitorScheduleRun.tenant_id == tenant_id,
            GeoMonitorScheduleRun.schedule_key == group_key,
        )
    )


def schedule_run_blocks_due(existing: GeoMonitorScheduleRun | None, *, now: datetime | None = None) -> bool:
    """已成功提交或仍在执行中的调度窗口不再重复入队；failed 允许重试。"""
    if existing is None:
        return False
    if existing.status in SCHEDULE_RUN_SUCCESS_STATUSES:
        return True
    if existing.status == "running":
        now = now or datetime.now()
        stale_after = timedelta(minutes=SCHEDULE_RUN_STALE_RUNNING_MINUTES)
        updated_at = existing.updated_at or existing.created_at
        if updated_at and now - updated_at < stale_after:
            return True
    return False


def persist_schedule_group_failure(
    db: Session,
    *,
    tenant_id: int,
    group_key: str,
    error_message: str,
    prompt_count: int = 0,
    platform_count: int = 0,
    created_by: int | None = None,
) -> GeoMonitorScheduleRun:
    existing = get_schedule_run(db, tenant_id, group_key)
    if existing is None:
        run = GeoMonitorScheduleRun(
            tenant_id=tenant_id,
            schedule_key=group_key,
            status="failed",
            prompt_count=prompt_count,
            platform_count=platform_count,
            error_message=error_message,
            created_by=created_by,
        )
        db.add(run)
    else:
        run = existing
        run.status = "failed"
        run.error_message = error_message
        run.prompt_count = prompt_count
        run.platform_count = platform_count
        if created_by is not None:
            run.created_by = created_by
    db.commit()
    return run


def enumerate_due_schedule_groups(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    max_prompts: int = 50,
    force: bool = False,
    now: datetime | None = None,
) -> Iterator[DueScheduleGroup]:
    """Yield due tenant keyword-group jobs without submitting them."""
    now = now or datetime.now()
    stmt = _active_asset_stmt()
    if tenant_ids is not None:
        if not tenant_ids:
            return
        stmt = stmt.where(BrandAsset.tenant_id.in_(tenant_ids))
    elif tenant_id:
        stmt = stmt.where(BrandAsset.tenant_id == tenant_id)
    assets = list(db.scalars(stmt))
    tenant_ids = {asset.tenant_id for asset in assets}
    keyword_groups_cache = {
        tenant: active_keyword_groups(db, tenant) for tenant in tenant_ids
    }
    for asset in assets:
        schedule_key = matched_schedule_key(asset, now, force=force, tolerance_minutes=settings.schedule_tolerance_minutes)
        if not schedule_key:
            continue
        keyword_groups = keyword_groups_cache.get(asset.tenant_id) or []
        per_group_max_prompts = max(1, max_prompts // max(1, len(keyword_groups)))
        for group in keyword_groups:
            for region_code in region_submission_targets(asset.region_codes_json):
                region_suffix = f"-rg{region_code}" if region_code else ""
                group_key = f"{schedule_key}-kw{_keyword_group_suffix(group)}{region_suffix}"
                if schedule_run_blocks_due(get_schedule_run(db, asset.tenant_id, group_key), now=now):
                    continue
                yield DueScheduleGroup(
                    tenant_id=asset.tenant_id,
                    schedule_key=schedule_key,
                    group_key=group_key,
                    max_prompts=per_group_max_prompts,
                    keyword=group.get("monitor_keyword"),
                    region_code=region_code,
                )


def enumerate_due_brand_word_weekly_groups(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    max_prompts: int = 50,
    now: datetime | None = None,
    force: bool = False,
) -> Iterator[DueScheduleGroup]:
    """每周一提交启用中的品牌词（run_mode=weekly）。"""
    now = now or datetime.now()
    if not force and now.isoweekday() != 1:
        return
    # 08:55–09:00+tolerance；beat 定在周一 09:00
    if not force:
        current_minutes = now.hour * 60 + now.minute
        target = 9 * 60
        if current_minutes < target - 5 or current_minutes > target + settings.schedule_tolerance_minutes:
            return
    schedule_key = brand_word_weekly_schedule_key(now)
    stmt = _active_asset_stmt()
    if tenant_ids is not None:
        if not tenant_ids:
            return
        stmt = stmt.where(BrandAsset.tenant_id.in_(tenant_ids))
    elif tenant_id:
        stmt = stmt.where(BrandAsset.tenant_id == tenant_id)
    assets = list(db.scalars(stmt))
    for asset in assets:
        keyword_groups = active_brand_word_groups(db, asset.tenant_id, run_mode="weekly")
        if not keyword_groups:
            continue
        per_group_max_prompts = max(1, max_prompts // max(1, len(keyword_groups)))
        for group in keyword_groups:
            for region_code in region_submission_targets(asset.region_codes_json):
                region_suffix = f"-rg{region_code}" if region_code else ""
                group_key = f"{schedule_key}-kw{_keyword_group_suffix(group)}{region_suffix}"
                if schedule_run_blocks_due(get_schedule_run(db, asset.tenant_id, group_key), now=now):
                    continue
                yield DueScheduleGroup(
                    tenant_id=asset.tenant_id,
                    schedule_key=schedule_key,
                    group_key=group_key,
                    max_prompts=per_group_max_prompts,
                    keyword=group.get("monitor_keyword"),
                    region_code=region_code,
                )


def enumerate_brand_word_once_groups(
    db: Session,
    *,
    tenant_id: int,
    groups: list[dict[str, Any]],
    max_prompts: int = 50,
    now: datetime | None = None,
) -> Iterator[DueScheduleGroup]:
    """保存后立刻提交一轮（once/weekly 均可用；key 为 bwonce-*，不占用周一 weekly key）。"""
    now = now or datetime.now()
    asset = db.scalar(
        select(BrandAsset).where(
            BrandAsset.tenant_id == tenant_id,
            BrandAsset.deleted.is_(False),
            BrandAsset.status.is_(True),
        )
    )
    if asset is None or not groups:
        return
    schedule_key = brand_word_once_schedule_key(now)
    per_group_max_prompts = max(1, max_prompts // max(1, len(groups)))
    for group in groups:
        for region_code in region_submission_targets(asset.region_codes_json):
            region_suffix = f"-rg{region_code}" if region_code else ""
            group_key = f"{schedule_key}-kw{_keyword_group_suffix(group)}{region_suffix}"
            if schedule_run_blocks_due(get_schedule_run(db, tenant_id, group_key), now=now):
                continue
            yield DueScheduleGroup(
                tenant_id=tenant_id,
                schedule_key=schedule_key,
                group_key=group_key,
                max_prompts=per_group_max_prompts,
                keyword=group.get("monitor_keyword"),
                region_code=region_code,
            )


def submit_schedule_group(
    db: Session,
    current: CurrentSession,
    item: DueScheduleGroup,
) -> dict[str, Any]:
    """Submit one scheduled keyword group to Molizhishu."""
    from app.core.redis_client import redis_lock
    from app.services.tenant_account_service import molizhishu_submit_skip_message

    asset = db.scalar(
        select(BrandAsset).where(
            BrandAsset.tenant_id == item.tenant_id,
            BrandAsset.deleted.is_(False),
            BrandAsset.status.is_(True),
        )
    )
    if asset is None:
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "failed",
            "keyword": item.keyword,
            "message": "企业品牌资产不存在或未启用",
        }
    tenant = db.scalar(select(Tenant).where(Tenant.id == item.tenant_id, Tenant.deleted.is_(False)))
    skip_message = molizhishu_submit_skip_message(tenant)
    if skip_message:
        # 2026-08-03 - 服务未开通：跑之前跳过，不落 failed，避免看板「调度失败」吓人
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "skipped",
            "keyword": item.keyword,
            "message": skip_message,
        }
    if schedule_run_blocks_due(get_schedule_run(db, item.tenant_id, item.group_key)):
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "skipped",
            "message": "该调度窗口已执行",
        }

    lock_key = f"schedule-submit:{item.tenant_id}:{item.group_key}"
    with redis_lock(lock_key, ttl_seconds=600) as acquired:
        if not acquired:
            return {
                "tenant_id": item.tenant_id,
                "schedule_key": item.group_key,
                "status": "skipped",
                "message": "该调度窗口正在提交",
            }
        # 持锁后再读一次，堵住 enumerate→submit 之间的双过门
        if schedule_run_blocks_due(get_schedule_run(db, item.tenant_id, item.group_key)):
            return {
                "tenant_id": item.tenant_id,
                "schedule_key": item.group_key,
                "status": "skipped",
                "message": "该调度窗口已执行",
            }
        return _submit_schedule_group_locked(db, current, item, asset)


def _submit_schedule_group_locked(
    db: Session,
    current: CurrentSession,
    item: DueScheduleGroup,
    asset: BrandAsset,
) -> dict[str, Any]:
    """持锁后的提交主体：先落 running 再打模力，降低 TOCTOU 双投。"""
    competitors = list(
        db.scalars(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == item.tenant_id,
                BrandCompetitor.deleted.is_(False),
            )
        )
    )
    if is_brand_word_schedule_key(item.group_key):
        keyword_groups = active_brand_word_groups(db, item.tenant_id)
        missing_message = "品牌词组不存在或已变更"
    else:
        keyword_groups = active_keyword_groups(db, item.tenant_id)
        missing_message = "监测词组不存在或已变更"
    group_part = item.group_key.split("-kw", 1)[-1]
    group_suffix = group_part.split("-rg", 1)[0]
    keyword_group = next(
        (group for group in keyword_groups if _keyword_group_suffix(group) == group_suffix),
        None,
    )
    if keyword_group is None:
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "failed",
            "keyword": item.keyword,
            "message": missing_message,
        }

    payload = build_scheduled_payload(
        db,
        asset,
        competitors,
        max_prompts=item.max_prompts,
        keyword_group=keyword_group,
        region_code=item.region_code,
        purpose="brand_word" if is_brand_word_schedule_key(item.group_key) else "geo",
    )
    existing_run = get_schedule_run(db, item.tenant_id, item.group_key)
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
                    "tenant_id": item.tenant_id,
                    "schedule_key": item.group_key,
                    "status": "submitted",
                    "keyword": item.keyword,
                    "task": serialize_task(linked_task),
                }
            existing_run.task_id = None
            existing_run.status = "running"
            existing_run.error_message = None
            run = existing_run
        else:
            existing_run.task_id = None
            existing_run.status = "running"
            existing_run.error_message = None
            run = existing_run
    elif existing_run is not None and existing_run.status == "failed":
        run = existing_run
        run.status = "running"
        run.error_message = None
        run.task_id = None
        run.prompt_count = len(payload.prompts)
        run.platform_count = len(payload.platforms)
    else:
        run = GeoMonitorScheduleRun(
            tenant_id=item.tenant_id,
            schedule_key=item.group_key,
            status="running",
            prompt_count=len(payload.prompts),
            platform_count=len(payload.platforms),
            created_by=current.user.id,
        )
        db.add(run)
    try:
        # ponytail: 先 commit running，其它 Worker 的 blocks_due 才能看见；再打模力
        db.commit()
    except IntegrityError:
        db.rollback()
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "skipped",
            "message": "该调度窗口已执行",
        }
    try:
        db.refresh(run)
        if not payload.prompts:
            raise ValueError("企业未配置可生成检测问题的监测词或竞品")
        if not payload.platforms:
            raise ValueError("企业未配置已购买或允许监测的模型平台")
        prepare_daily_platform_matrix_before_submit(
            db,
            tenant_id=item.tenant_id,
            schedule_key=item.group_key,
        )
        task = submit_monitor_task(db, payload, current, auto_commit=False)
        run.task_id = task.task_id
        run.status = "submitted"
        db.commit()
        db.refresh(task)
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "submitted",
            "keyword": item.keyword,
            "task": serialize_task(task),
        }
    except _SCHEDULE_TRANSIENT_ERRORS:
        db.rollback()
        raise
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        from app.services.tenant_account_service import (
            is_service_gate_schedule_message,
            molizhishu_submit_skip_message,
        )

        message = str(exc)
        # 兜底：即便漏过前置检查，服务闸门也不落 failed
        if is_service_gate_schedule_message(message):
            tenant = db.scalar(select(Tenant).where(Tenant.id == item.tenant_id))
            return {
                "tenant_id": item.tenant_id,
                "schedule_key": item.group_key,
                "status": "skipped",
                "keyword": item.keyword,
                "message": molizhishu_submit_skip_message(tenant) or "企业服务未开通，监测暂不提交",
            }
        persist_schedule_group_failure(
            db,
            tenant_id=item.tenant_id,
            group_key=item.group_key,
            error_message=message,
            prompt_count=len(payload.prompts),
            platform_count=len(payload.platforms),
            created_by=current.user.id,
        )
        return {
            "tenant_id": item.tenant_id,
            "schedule_key": item.group_key,
            "status": "failed",
            "keyword": item.keyword,
            "message": message,
        }


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


def matched_schedule_key(
    asset: BrandAsset,
    now: datetime,
    tolerance_minutes: int | None = None,
    *,
    force: bool = False,
) -> str | None:
    tolerance_minutes = settings.schedule_tolerance_minutes if tolerance_minutes is None else tolerance_minutes
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
    region_code: str | None = None,
    *,
    purpose: str = "geo",
) -> MonitorTaskCreateRequest:
    from app.core.monitor_purpose import PURPOSE_BRAND_WORD, normalize_task_purpose
    from app.services.brand_service import keyword_group_platform_configs, tenant_purchased_platforms
    from app.services.platform_catalog_lifecycle_service import submittable_platform_codes

    prompts = build_scheduled_prompts(asset, competitors, max_prompts=max_prompts, keyword_group=keyword_group)
    configs = keyword_group_platform_configs(keyword_group, asset)
    allowed = set(submittable_platform_codes(db, [item["code"] for item in configs]))
    purpose_norm = normalize_task_purpose(purpose)
    if purpose_norm == PURPOSE_BRAND_WORD:
        purchased = set(tenant_purchased_platforms(db, asset.tenant_id, asset))
        if purchased:
            allowed &= purchased
    platforms = [
        PlatformConfig(platform=item["code"], mode=item["mode"], screenshot=item["screenshot"])
        for item in configs
        if item["code"] in allowed
    ]
    monitor_keyword, aliases = molizhishu_monitor_terms(db, asset.tenant_id, keyword_group=keyword_group)
    return MonitorTaskCreateRequest(
        tenant_id=asset.tenant_id,
        prompts=prompts,
        platforms=platforms,
        monitor_keywords=monitor_keyword,
        monitor_keyword_aliases=aliases,
        region_code=[region_code] if region_code else None,
        purpose=purpose_norm,  # type: ignore[arg-type]
    )


def preview_scheduled_tasks(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    max_prompts: int = 50,
) -> list[dict[str, Any]]:
    stmt = _active_asset_stmt()
    if tenant_ids is not None:
        if not tenant_ids:
            return []
        stmt = stmt.where(BrandAsset.tenant_id.in_(tenant_ids))
    elif tenant_id:
        stmt = stmt.where(BrandAsset.tenant_id == tenant_id)
    tenant_map = {item.id: item.name for item in db.scalars(select(Tenant).where(Tenant.deleted.is_(False)))}
    result: list[dict[str, Any]] = []
    for asset in db.scalars(stmt):
        competitors = list(db.scalars(select(BrandCompetitor).where(BrandCompetitor.tenant_id == asset.tenant_id, BrandCompetitor.deleted.is_(False))))
        keyword_groups = active_keyword_groups(db, asset.tenant_id)
        group_count = max(1, len(keyword_groups))
        per_group_max_prompts = max(1, max_prompts // group_count)
        group_previews: list[dict[str, Any]] = []
        for group in keyword_groups:
            prompts = build_scheduled_prompts(asset, competitors, max_prompts=per_group_max_prompts, keyword_group=group)
            from app.services.brand_service import keyword_group_platform_configs
            from app.services.platform_catalog_lifecycle_service import submittable_platform_codes

            configs = keyword_group_platform_configs(group, asset)
            allowed = set(submittable_platform_codes(db, [item["code"] for item in configs]))
            group_platforms = [
                PlatformConfig(platform=item["code"], mode=item["mode"], screenshot=item["screenshot"])
                for item in configs
                if item["code"] in allowed
            ]
            group_platform_count = len(group_platforms)
            group_previews.append({
                "monitor_keyword": group.get("monitor_keyword"),
                "exposure_terms": group.get("exposure_terms") or [],
                "platforms": [item.platform for item in group_platforms],
                "prompt_limit": per_group_max_prompts,
                "prompt_count": len(prompts),
                "prompts": prompts,
                "subtask_count": len(prompts) * group_platform_count,
            })
        total_prompts = sum(item["prompt_count"] for item in group_previews)
        total_subtasks = sum(item["subtask_count"] for item in group_previews)
        all_prompts = [prompt for group in group_previews for prompt in group["prompts"]]
        all_platform_codes = sorted({code for group in group_previews for code in (group.get("platforms") or [])})
        platform_count = len(all_platform_codes)
        platforms = [
            PlatformConfig(platform=code, mode=FAST_MONITOR_MODE, screenshot=1)
            for code in all_platform_codes
        ]
        result.append({
            "tenant_id": asset.tenant_id,
            "tenant_name": tenant_map.get(asset.tenant_id) or asset.company_full_name,
            "brand_name": asset.brand_name,
            "region_codes": normalize_region_codes(asset.region_codes_json or []),
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
    tenant_ids: list[int] | None = None,
    limit: int = 10,
    max_prompts: int = 50,
    force: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in enumerate_due_schedule_groups(
        db,
        tenant_id=tenant_id,
        tenant_ids=tenant_ids,
        max_prompts=max_prompts,
        force=force,
        now=now,
    ):
        if len(results) >= limit:
            break
        results.append(submit_schedule_group(db, current, item))
    return results


def kick_brand_word_service_start_for_tenant(
    db: Session,
    tenant_id: int,
    *,
    max_prompts: int | None = None,
) -> dict[str, Any]:
    """服务刚开始：把启用品牌词（once/weekly）各入队/提交一轮。幂等靠 bwstart-* schedule_run。"""
    max_prompts = max_prompts or settings.celery_scan_submit_max_prompts
    items = list(enumerate_brand_word_service_start_groups(db, tenant_id=tenant_id, max_prompts=max_prompts))
    if not items:
        return {"tenant_id": tenant_id, "status": "ok", "enqueued": 0, "submitted": 0, "skipped": 0}

    if settings.celery_enabled:
        from app.tasks.monitor import _enqueue_task, _schedule_submit_task_id, submit_schedule_group_task

        enqueued = 0
        skipped = 0
        for item in items:
            existing = get_schedule_run(db, item.tenant_id, item.group_key)
            is_retry = existing is not None and existing.status == "failed"
            ok = _enqueue_task(
                submit_schedule_group_task,
                task_id=_schedule_submit_task_id(item.group_key, is_retry=is_retry),
                kwargs={
                    "tenant_id": item.tenant_id,
                    "group_key": item.group_key,
                    "max_prompts": item.max_prompts,
                    "keyword": item.keyword,
                },
            )
            if ok:
                enqueued += 1
            else:
                skipped += 1
        return {"tenant_id": tenant_id, "status": "ok", "enqueued": enqueued, "submitted": 0, "skipped": skipped}

    from app.services.platform_session import load_platform_session

    current = load_platform_session(db)
    submitted = 0
    skipped = 0
    for item in items:
        result = submit_schedule_group(db, current, item)
        if result.get("status") == "submitted":
            submitted += 1
        else:
            skipped += 1
    return {"tenant_id": tenant_id, "status": "ok", "enqueued": 0, "submitted": submitted, "skipped": skipped}


def maybe_kick_brand_words_after_service_became_active(
    *,
    tenant_id: int,
    became_active: bool,
) -> None:
    """企业刚进入服务期时触发品牌词首跑（Celery 优先，失败只打日志）。"""
    if not became_active:
        return
    try:
        from app.tasks.monitor import kick_brand_word_service_start_task

        kick_brand_word_service_start_task.delay(tenant_id)
    except Exception:
        # 无 Celery / broker 抖动时不挡企业保存
        import logging

        logging.getLogger(__name__).exception(
            "kick brand word service-start failed tenant_id=%s", tenant_id
        )
