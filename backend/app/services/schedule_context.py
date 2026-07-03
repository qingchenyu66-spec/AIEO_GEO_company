"""Resolve schedule window labels from GeoMonitorScheduleRun or brand config."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorTask

SCHEDULE_TYPE_LABELS = {
    "daily_times": "每天定时",
    "fixed_times": "固定时刻",
    "weekly": "每周指定日",
    "monthly": "每月指定日",
}

NON_RANKING_PROMPT_MARKERS = (
    "是做什么的",
    "这家公司怎么样",
    "有哪些优势和不足",
    "值得推荐吗",
    "表现怎么样",
    "分别适合什么企业",
    "口碑评价怎么样",
    "对比哪个好",
)


def prompt_monitor_intent(prompt: str | None) -> str:
    """Classify monitor prompt: monitor keywords are ranking questions; legacy templates stay exposure."""
    text = (prompt or "").strip()
    if not text:
        return "exposure"
    if any(marker in text for marker in NON_RANKING_PROMPT_MARKERS):
        return "exposure"
    return "ranking"


def extract_schedule_window_key(schedule_key: str | None) -> str | None:
    text = str(schedule_key or "").strip()
    if not text:
        return None
    return text.split("-kw", 1)[0]


def format_schedule_window_label(window_key: str | None) -> str | None:
    text = str(window_key or "").strip()
    if len(text) < 13 or text[8] != "-":
        return None
    date_part, time_part = text[:8], text[9:13]
    try:
        dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def infer_schedule_window_from_datetime(
    dt: datetime,
    asset: BrandAsset | None,
    *,
    tolerance_minutes: int = 180,
) -> tuple[str | None, str | None]:
    """Match task creation time to the nearest configured schedule slot on the same day."""
    if asset is None or dt is None:
        return None, None
    from app.services.schedule_service import schedule_times_for_asset

    slots = schedule_times_for_asset(asset)
    if not slots:
        return None, None

    date_part = dt.strftime("%Y%m%d")
    dt_minutes = dt.hour * 60 + dt.minute
    matched_slot = None
    matched_diff: int | None = None

    for slot in slots:
        slot_minutes = slot.hour * 60 + slot.minute
        diff = dt_minutes - slot_minutes
        if 0 <= diff <= tolerance_minutes:
            if matched_diff is None or diff < matched_diff:
                matched_slot = slot
                matched_diff = diff
        elif -30 <= diff < 0:
            late_diff = abs(diff)
            if matched_diff is None or late_diff < matched_diff:
                matched_slot = slot
                matched_diff = late_diff

    if matched_slot is None:
        closest = min(
            slots,
            key=lambda slot: abs(dt_minutes - (slot.hour * 60 + slot.minute)),
        )
        matched_slot = closest

    window_key = f"{date_part}-{matched_slot.hour:02d}{matched_slot.minute:02d}"
    return window_key, format_schedule_window_label(window_key)


def schedule_runs_for_tasks(db: Session, task_ids: list[str]) -> dict[str, GeoMonitorScheduleRun]:
    ids = [item for item in task_ids if item]
    if not ids:
        return {}
    rows = list(
        db.scalars(
            select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.task_id.in_(ids))
        )
    )
    return {row.task_id: row for row in rows if row.task_id}


def resolve_monitor_task_source(task: GeoMonitorTask, *, has_lead_run: bool = False) -> str:
    """签约企业任务一律视为 GEO 监测；仅无 tenant_id 的独立售前抓取标为 lead_diagnosis。"""
    if getattr(task, "tenant_id", None):
        return "tenant_monitor"
    if has_lead_run:
        return "lead_diagnosis"
    return "tenant_monitor"


def lead_diagnosis_runs_for_tasks(db: Session, task_ids: list[str]) -> dict[str, LeadDiagnosisRun]:
    """售前诊断抓取记录：task_id -> run，用于正确展示 16:30 等诊断批次。"""
    ids = [item for item in task_ids if item]
    if not ids:
        return {}
    rows = list(
        db.scalars(
            select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id.in_(ids))
        )
    )
    return {row.task_id: row for row in rows if row.task_id}


def resolve_task_schedule_context(
    task: GeoMonitorTask,
    schedule_run: GeoMonitorScheduleRun | None,
    asset: BrandAsset | None,
    lead_run: LeadDiagnosisRun | None = None,
) -> dict[str, Any]:
    keyword_group = str(task.monitor_keywords or "").strip() or None
    if schedule_run and schedule_run.schedule_key:
        window_key = extract_schedule_window_key(schedule_run.schedule_key)
        label = format_schedule_window_label(window_key)
        return {
            "schedule_key": schedule_run.schedule_key,
            "schedule_window_key": window_key,
            "schedule_label": label or window_key,
            "schedule_run_status": schedule_run.status,
            "schedule_source": "run",
            "keyword_group": keyword_group,
        }

    if lead_run and lead_run.schedule_key:
        window_key = extract_schedule_window_key(lead_run.schedule_key) or lead_run.schedule_key
        label = lead_run.schedule_label or format_schedule_window_label(window_key) or window_key
        return {
            "schedule_key": lead_run.schedule_key,
            "schedule_window_key": window_key,
            "schedule_label": label,
            "schedule_run_status": lead_run.status,
            "schedule_source": "lead_diagnosis" if not getattr(task, "tenant_id", None) else "run",
            "keyword_group": keyword_group,
        }

    inferred_key, inferred_label = infer_schedule_window_from_datetime(
        task.created_at,
        asset,
    )
    if inferred_key and inferred_label:
        return {
            "schedule_key": None,
            "schedule_window_key": inferred_key,
            "schedule_label": inferred_label,
            "schedule_run_status": None,
            "schedule_source": "inferred",
            "keyword_group": keyword_group,
        }

    fallback_label = task.created_at.strftime("%Y-%m-%d %H:%M") if task.created_at else None
    fallback_key = task.created_at.strftime("%Y%m%d-%H%M") if task.created_at else task.task_id
    return {
        "schedule_key": None,
        "schedule_window_key": fallback_key,
        "schedule_label": fallback_label,
        "schedule_run_status": None,
        "schedule_source": "created_at",
        "keyword_group": keyword_group,
    }


def schedule_plan_summary(asset: BrandAsset | None) -> dict[str, Any]:
    if asset is None:
        return {
            "schedule_type": None,
            "schedule_type_label": None,
            "schedule_times": [],
            "schedule_frequency": 0,
            "schedule_weekdays": [],
            "schedule_month_days": [],
        }
    from app.services.schedule_service import schedule_times_for_asset

    times = [slot.strftime("%H:%M") for slot in schedule_times_for_asset(asset)]
    return {
        "schedule_type": asset.schedule_type,
        "schedule_type_label": SCHEDULE_TYPE_LABELS.get(asset.schedule_type, asset.schedule_type),
        "schedule_times": times,
        "schedule_frequency": asset.schedule_frequency,
        "schedule_weekdays": list(asset.schedule_weekdays_json or []),
        "schedule_month_days": list(asset.schedule_month_days_json or []),
    }


def schedule_window_sort_key(window_key: str | None) -> datetime:
    text = str(window_key or "").strip()
    if len(text) >= 13 and text[8] == "-":
        try:
            return datetime.strptime(f"{text[:8]}{text[9:13]}", "%Y%m%d%H%M")
        except ValueError:
            pass
    return datetime.min
