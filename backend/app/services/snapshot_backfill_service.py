"""快照补录：失败子任务粘贴分享链接，自动解析正文与信源，重算排名并触发聚合。"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import and_, false, func, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.core.config import settings
from app.core.region_catalog import region_submission_targets
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask, GeoSnapshotBackfillGapDismiss
from app.models.tenant import Tenant
from app.services.brand_service import (
    active_keyword_groups,
    get_brand_asset,
    keyword_group_display_label,
    keyword_group_monitor_keywords,
    keyword_group_name,
    keyword_group_platforms,
    keyword_group_primary_keyword,
    keyword_group_to_dict,
    list_keyword_groups,
    tenant_purchased_platforms,
)
from app.schemas.monitor import FAST_MONITOR_MODE, SnapshotBackfillBatchDismissSlot
from app.services.operation_log_service import write_operation_log
from app.services.media_proxy_service import public_screenshot_url
from app.services.monitor_service import (
    backfill_weak_rank_threshold,
    subtask_inflight_blocks_snapshot_backfill,
    TERMINAL_STATUSES,
    _average_mention_position,
    _platform_display_names,
    _prompt_belongs_to_group,
    _reconcile_task_progress,
    _resolve_keyword_group_filter,
    _resolve_prompt_keyword_group,
    _subtask_answer_plaintext,
    get_monitor_subtask,
    get_monitor_task,
    recompute_subtask_rank_from_answer,
    serialize_subtask_for_display,
    subtask_needs_snapshot_backfill,
)
from app.core.masking import excerpt_sensitive_text
from app.services.ranking_parser import rankings_for_storage
from app.services.schedule_service import schedule_times_for_asset
from app.services.share_page_fetch_service import fetch_share_page
from app.services.share_page_screenshot_service import (
    enqueue_backfill_screenshot,
    is_image_screenshot_url,
)
from app.services.schedule_context import (
    lead_diagnosis_runs_for_tasks,
    resolve_monitor_task_source,
    resolve_task_schedule_context,
    schedule_runs_for_tasks,
)
from app.services.system_notification_service import (
    resolve_subtask_backfill_notification,
    upsert_batch_backfill_notification as persist_batch_backfill_notification,
)

_SNAPSHOT_HOST_HINTS: dict[str, set[str]] = {
    "doubao.com": {"doubao", "doubao_mobile"},
    "deepseek.com": {"deepseek", "deepseek_mobile"},
    "deepseek.cn": {"deepseek", "deepseek_mobile"},
    "yuanbao.tencent.com": {"yuanbao"},
    "qianwen.com": {"qianwen", "qianwen_mobile"},
    "tongyi.aliyun.com": {"qianwen", "qianwen_mobile"},
    "kimi.com": {"kimi", "kimi_mobile"},
    "moonshot.cn": {"kimi", "kimi_mobile"},
    "quark.cn": {"quark"},
}


def _normalize_host(netloc: str) -> str:
    host = (netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def validate_snapshot_url(url: str, *, platform: str | None = None) -> str:
    """校验分享链接格式；平台与域名不匹配时仅告警，不阻断。"""
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("快照链接须为 http 或 https 地址")
    if not parsed.netloc:
        raise ValueError("快照链接无效")
    if len(value) > 1000:
        raise ValueError("快照链接过长")
    host = _normalize_host(parsed.netloc)
    if platform:
        expected = next((codes for suffix, codes in _SNAPSHOT_HOST_HINTS.items() if host.endswith(suffix)), None)
        if expected and platform not in expected:
            raise ValueError(f"链接域名与平台 {platform} 可能不匹配，请确认后再提交")
    return value


def _brand_terms_for_task(db: Session, task: GeoMonitorTask, asset: BrandAsset | None) -> list[str]:
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    if asset is not None:
        from app.services.monitor_service import _ranking_match_terms

        terms = _ranking_match_terms(asset, groups)
        if terms:
            return terms
    terms: list[str] = []
    keyword = str(task.monitor_keywords or "").strip()
    if keyword:
        terms.append(keyword)
    request = task.raw_request_json or {}
    for alias in request.get("monitorKeywordAliases") or request.get("monitor_keyword_aliases") or []:
        text = str(alias or "").strip()
        if text and text not in terms:
            terms.append(text)
    return terms or ([keyword] if keyword else [])


def _lead_context_for_task(db: Session, task_id: str) -> dict[str, Any]:
    run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task_id))
    if run is None:
        return {}
    lead = db.get(LeadDiagnosis, run.lead_diagnosis_id)
    return {
        "lead_diagnosis_id": run.lead_diagnosis_id,
        "brand_name": lead.brand_name if lead else None,
        "created_by_user_id": lead.created_by_user_id if lead else None,
    }


def resolve_backfill_owner_user_id(
    db: Session,
    task: GeoMonitorTask,
    *,
    lead_ctx: dict[str, Any] | None = None,
) -> int | None:
    """补录待办归属销售：签约企业 → tenant.owner_user_id；售前 → 诊断创建人。"""
    if task.tenant_id:
        tenant = db.get(Tenant, task.tenant_id)
        if tenant and tenant.owner_user_id:
            return int(tenant.owner_user_id)
    ctx = lead_ctx if lead_ctx is not None else _lead_context_for_task(db, task.task_id)
    creator = ctx.get("created_by_user_id")
    if creator:
        return int(creator)
    return None


def _schedule_context_for_task(
    db: Session,
    task: GeoMonitorTask,
    *,
    schedule_runs_map: dict[str, GeoMonitorScheduleRun] | None = None,
    lead_runs_map: dict[str, LeadDiagnosisRun] | None = None,
    brand_asset_cache: dict[int, BrandAsset | None] | None = None,
) -> dict[str, Any]:
    """与实时监测一致的调度批次：签约企业优先 GeoMonitorScheduleRun，不用售前诊断挂靠批次。"""
    asset = None
    if task.tenant_id:
        if brand_asset_cache is not None:
            if task.tenant_id not in brand_asset_cache:
                try:
                    brand_asset_cache[task.tenant_id] = get_brand_asset(db, task.tenant_id)
                except Exception:
                    brand_asset_cache[task.tenant_id] = None
            asset = brand_asset_cache[task.tenant_id]
        else:
            try:
                asset = get_brand_asset(db, task.tenant_id)
            except Exception:
                asset = None

    schedule_run = (schedule_runs_map or {}).get(task.task_id)
    if schedule_run is None:
        schedule_run = db.scalar(
            select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.task_id == task.task_id)
        )

    lead_run = None
    if not task.tenant_id:
        lead_run = (lead_runs_map or {}).get(task.task_id)
        if lead_run is None:
            lead_run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task.task_id))

    return resolve_task_schedule_context(task, schedule_run, asset, lead_run)


def subtask_backfill_dismissed(subtask: GeoMonitorSubtask) -> bool:
    """运营已忽略该子任务的待补录提醒。"""
    return getattr(subtask, "backfill_dismissed_at", None) is not None


def _mark_subtask_dismissed(subtask: GeoMonitorSubtask, user_id: int, now: datetime) -> bool:
    if subtask_backfill_dismissed(subtask):
        return False
    subtask.backfill_dismissed_at = now
    subtask.backfill_dismissed_by = user_id
    return True


def _slot_is_batch_dismissable(slot: dict[str, Any]) -> bool:
    if slot.get("backfill_dismissed"):
        return False
    return bool(slot.get("is_gap") or slot.get("subtask_id"))


def clear_subtask_backfill_dismiss(subtask: GeoMonitorSubtask) -> None:
    subtask.backfill_dismissed_at = None
    subtask.backfill_dismissed_by = None


def _bust_snapshot_backfill_matrix_cache() -> None:
    try:
        from app.core.redis_client import delete_cache_pattern

        delete_cache_pattern("snapshot_backfill:mtx:*")
    except Exception:
        pass


def parse_schedule_slot(
    window_key: str | None,
    schedule_label: str | None = None,
) -> tuple[str, str]:
    """场次 key + 展示时刻。返回 (20260728-0430, 2026-07-28 04:30)。

    2026-07-28 - 通知不用早午晚 - 场次未必一天三次，按具体时刻汇总
    """
    text = str(window_key or "").strip()
    if len(text) >= 13 and text[8] == "-" and text[:8].isdigit():
        day, hm = text[:8], text[9:]
        if len(hm) >= 4 and hm[:4].isdigit():
            label = f"{day[0:4]}-{day[4:6]}-{day[6:8]} {hm[0:2]}:{hm[2:4]}"
            return f"{day}-{hm[:4]}", label

    label_raw = str(schedule_label or "").strip().replace("：", ":")
    # "2026-07-28 09:30" / "2026-07-28 9:30"
    if len(label_raw) >= 16 and label_raw[4] == "-" and label_raw[7] == "-":
        day_part = label_raw[:10]
        rest = label_raw[11:].strip()
        if ":" in rest:
            hh_s, mm_s = rest.split(":", 1)[0], rest.split(":", 1)[1][:2]
            try:
                hh, mm = int(hh_s), int(mm_s)
                key = f"{day_part.replace('-', '')}-{hh:02d}{mm:02d}"
                return key, f"{day_part} {hh:02d}:{mm:02d}"
            except ValueError:
                pass
    # 仅时刻 "09:30" —— 无日期时退回时段
    for token in label_raw.split():
        if ":" in token:
            parts = token.split(":", 1)
            try:
                hh, mm = int(parts[0]), int(parts[1][:2])
                today = date.today()
                key = f"{today.strftime('%Y%m%d')}-{hh:02d}{mm:02d}"
                return key, f"{today.isoformat()} {hh:02d}:{mm:02d}"
            except ValueError:
                continue
    return "unknown", "时段"


def schedule_slot_label(window_key: str | None, schedule_label: str | None = None) -> str:
    """通知正文用的具体场次时刻。"""
    return parse_schedule_slot(window_key, schedule_label)[1]


def schedule_period_bucket(window_key: str | None, schedule_label: str | None = None) -> str:
    """兼容旧名：现返回具体时刻，不再映射早/午/晚。"""
    return schedule_slot_label(window_key, schedule_label)


def _detect_day_from_schedule(schedule_ctx: dict[str, Any] | None) -> str | None:
    ctx = schedule_ctx or {}
    for key in (ctx.get("schedule_window_key"), ctx.get("schedule_key")):
        text = str(key or "").strip()
        if len(text) >= 8 and text[:8].isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    label = str(ctx.get("schedule_label") or "").strip()
    if len(label) >= 10 and label[4] == "-" and label[7] == "-":
        return label[:10]
    return None


def matrix_cell_has_todo(*, ranks: list[float], sample_count: int, gap_count: int = 0) -> bool:
    """词×平台×日红点：有场次且（无均值 或 均值>阈值）；漏跑日缺口槽位也标。"""
    if sample_count <= 0:
        # 2026-08-03 - 到期漏跑日无子任务 - 矩阵仍露缺口格供补录
        return gap_count > 0
    # 2026-07-28 - 算不出均值也标红 - 有场次但无一有效展示位次
    if not ranks:
        return True
    avg = _average_mention_position(ranks)
    if avg is None:
        return True
    return float(avg) > float(backfill_weak_rank_threshold())


def enrich_subtask_display_backfill_flags(
    display: dict[str, Any],
    subtask: GeoMonitorSubtask,
) -> dict[str, Any]:
    """补录 API 响应带上与矩阵一致的 needs_backfill，避免前端 patch 误消红点。"""
    display_rank = display.get("mention_position")
    try:
        effective = int(display_rank) if display_rank is not None else None
    except (TypeError, ValueError):
        effective = None
    needs = subtask_needs_snapshot_backfill(
        subtask,
        effective_rank=effective,
        use_effective_rank=True,
        brand_mentioned=display.get("brand_mentioned"),
    )
    dismissed = subtask_backfill_dismissed(subtask)
    display["backfill_dismissed"] = dismissed
    display["needs_backfill"] = bool(needs) and not dismissed
    display["needs_backfill_raw"] = bool(needs)
    display["has_answer"] = bool((subtask.answer_content or "").strip())
    return display


def build_snapshot_backfill_matrix_sample(
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    schedule_ctx: dict[str, Any],
    tenant_name: str | None = None,
    lead_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """矩阵轻量样本：跳过展示对账，避免千级子任务逐条 serialize。"""
    # 2026-07-28 - 矩阵加载慢 - 热力只用库内位次，抽屉点详情再拉完整展示
    has_answer = bool((subtask.answer_content or "").strip())
    pos = subtask.mention_position
    try:
        effective = int(pos) if pos is not None else None
    except (TypeError, ValueError):
        effective = None
    needs = subtask_needs_snapshot_backfill(
        subtask,
        effective_rank=effective,
        use_effective_rank=True,
    )
    dismissed = subtask_backfill_dismissed(subtask)
    updated = getattr(subtask, "updated_at", None)
    return {
        "subtask_id": subtask.subtask_id,
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "tenant_name": tenant_name,
        "brand_name": (lead_ctx or {}).get("brand_name"),
        "platform": subtask.platform,
        "prompt": subtask.prompt,
        "error_message": subtask.error_message,
        "monitor_keywords": task.monitor_keywords,
        "mention_position": effective,
        "needs_backfill": bool(needs) and not dismissed,
        "needs_backfill_raw": bool(needs),
        "backfill_dismissed": dismissed,
        "has_answer": has_answer,
        "status": subtask.status,
        "schedule_key": schedule_ctx.get("schedule_key"),
        "schedule_window_key": schedule_ctx.get("schedule_window_key"),
        "schedule_label": schedule_ctx.get("schedule_label"),
        "source": _resolve_snapshot_backfill_source(task, lead_ctx or {}),
        "updated_at": updated.isoformat(sep=" ", timespec="seconds") if updated else None,
    }


def notify_failed_subtasks_for_task(db: Session, task: GeoMonitorTask) -> int:
    """任务终态时按「公司×具体场次时刻」汇总写入待补录通知（平台拆进正文）。"""
    if task.status not in TERMINAL_STATUSES and (task.failed_items or 0) <= 0:
        return 0
    # 2026-07-31 - 售前诊断不发补录铃铛 - 通知只服务签约日常监测，报告/诊断另线
    if _is_lead_diagnosis_backfill_task(db, task):
        return 0
    groups: dict[tuple[str, str, str], list[tuple[GeoMonitorSubtask, dict[str, Any]]]] = defaultdict(list)
    for subtask in task.subtasks or []:
        if subtask_backfill_dismissed(subtask):
            continue
        ctx = build_snapshot_backfill_item(db, subtask, task)
        if not ctx.get("needs_backfill"):
            continue
        slot_key, slot_label = parse_schedule_slot(
            ctx.get("schedule_window_key"), ctx.get("schedule_label")
        )
        detect_day = _detect_day_from_schedule(ctx) or (
            f"{slot_key[0:4]}-{slot_key[4:6]}-{slot_key[6:8]}" if len(slot_key) >= 8 and slot_key[:8].isdigit() else date.today().isoformat()
        )
        scope = str(ctx.get("brand_name") or ctx.get("tenant_name") or task.monitor_keywords or "监测任务")
        groups[(slot_key, slot_label, scope)].append((subtask, ctx))

    count = 0
    for (slot_key, slot_label, scope), rows in groups.items():
        payloads = [ctx for _st, ctx in rows]
        detect_day = _detect_day_from_schedule(payloads[0]) if payloads else date.today().isoformat()
        if not detect_day:
            detect_day = (
                f"{slot_key[0:4]}-{slot_key[4:6]}-{slot_key[6:8]}"
                if len(slot_key) >= 8 and slot_key[:8].isdigit()
                else date.today().isoformat()
            )
        entries = []
        for st, ctx in rows:
            platform = str(st.platform or ctx.get("platform") or "").strip() or "unknown"
            entries.append(
                {
                    "subtask_id": str(st.subtask_id),
                    "platform": platform,
                    "platform_label": None,
                }
            )
        _notify_batch_backfill(
            db,
            period=slot_label,
            slot_key=slot_key,
            detect_day=detect_day,
            scope=scope,
            subtask_entries=entries,
            payloads=payloads,
        )
        count += len(rows)
    return count


def _notify_batch_backfill(
    db: Session,
    *,
    period: str,
    detect_day: str,
    scope: str,
    payloads: list[dict[str, Any]],
    subtask_entries: list[dict[str, Any]] | None = None,
    platform: str | None = None,
    subtask_ids: list[str] | None = None,
    slot_key: str | None = None,
) -> None:
    platform_names = _platform_display_names()
    owner_user_id = None
    tenant_id = None
    for payload in payloads:
        if payload.get("owner_user_id") is not None:
            owner_user_id = payload.get("owner_user_id")
        if payload.get("tenant_id") is not None:
            tenant_id = payload.get("tenant_id")

    entries: list[dict[str, Any]] = []
    for item in subtask_entries or []:
        code = str(item.get("platform") or platform or "unknown").strip() or "unknown"
        entries.append(
            {
                "subtask_id": str(item.get("subtask_id") or "").strip(),
                "platform": code,
                "platform_label": str(item.get("platform_label") or platform_names.get(code) or code),
            }
        )
    if not entries and subtask_ids:
        code = str(platform or "unknown").strip() or "unknown"
        label = platform_names.get(code) or code
        for sid in subtask_ids:
            entries.append(
                {
                    "subtask_id": str(sid),
                    "platform": code,
                    "platform_label": label,
                }
            )
    entries = [e for e in entries if e.get("subtask_id")]
    if not entries:
        return

    resolved_slot = slot_key
    if not resolved_slot and payloads:
        resolved_slot, _label = parse_schedule_slot(
            payloads[0].get("schedule_window_key"),
            payloads[0].get("schedule_label"),
        )

    # 同批多次 notify 合并 subtask_ids，N 用合并后条数
    persist_batch_backfill_notification(
        db,
        period=period,
        slot_key=resolved_slot,
        detect_day=detect_day,
        scope=scope,
        subtask_entries=entries,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        sample_payload=payloads[0] if payloads else {},
    )


def _notify_subtask_backfill(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    ctx: dict[str, Any] | None = None,
) -> None:
    """兼容旧调用：单条并入公司×场次时刻汇总。"""
    # 2026-07-31 - 同上：取消忽略等单条入口也不给售前发铃铛
    if _is_lead_diagnosis_backfill_task(db, task):
        return
    payload = ctx or build_snapshot_backfill_item(db, subtask, task)
    scope = str(payload.get("brand_name") or payload.get("tenant_name") or task.monitor_keywords or "监测任务")
    platform = str(subtask.platform or payload.get("platform") or "").strip() or "unknown"
    slot_key, slot_label = parse_schedule_slot(
        payload.get("schedule_window_key"), payload.get("schedule_label")
    )
    detect_day = _detect_day_from_schedule(payload) or (
        f"{slot_key[0:4]}-{slot_key[4:6]}-{slot_key[6:8]}"
        if len(slot_key) >= 8 and slot_key[:8].isdigit()
        else date.today().isoformat()
    )
    _notify_batch_backfill(
        db,
        period=slot_label,
        slot_key=slot_key,
        detect_day=detect_day,
        scope=scope,
        subtask_entries=[
            {
                "subtask_id": str(subtask.subtask_id),
                "platform": platform,
                "platform_label": None,
            }
        ],
        payloads=[payload],
    )


def apply_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    snapshot_url: str | None = None,
    answer_content: str | None = None,
    current: CurrentSession,
    mention_position: int | None = None,
    sentiment: str | None = None,
    reference_urls: list[str] | None = None,
) -> dict[str, Any]:
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可执行快照补录")

    subtask = get_monitor_subtask(db, subtask_id, current)
    task = get_monitor_task(db, subtask.task_id, current)
    # 2026-08-11 - 监测未终态就补录会被同步盖掉 - 仅 completed/failed/stopped 等终态可补
    if subtask_inflight_blocks_snapshot_backfill(subtask):
        raise ValueError("该场次监测尚未结束，请等抓取完成或失败后再补录")

    previous_stat_date = None
    if task.tenant_id:
        from app.services.monitor_stats_service import _detect_stat_date
        from app.services.schedule_context import lead_diagnosis_runs_for_tasks, schedule_runs_for_tasks

        schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
        lead_run = lead_diagnosis_runs_for_tasks(db, [task.task_id]).get(task.task_id)
        asset = get_brand_asset(db, task.tenant_id)
        previous_stat_date = _detect_stat_date(
            subtask,
            task,
            schedule_run=schedule_run,
            lead_run=lead_run,
            asset=asset,
        )

    url_raw = str(snapshot_url or "").strip()
    # 2026-08-21 - 截图 CDN/代理图被填进「分享链接」会误走解析；图链不算分享页，并入已有快照后再走只改排名
    if url_raw and is_image_screenshot_url(url_raw):
        if not (subtask.page_screenshot or "").strip():
            subtask.page_screenshot = url_raw
        url_raw = ""
    # 无分享页：只改排名，须已有模力正文/截图（或 raw 里仍有）；缺口空格必须贴分享链接
    if not url_raw:
        if mention_position is None:
            raise ValueError("未填写分享链接时，请填写品牌排名")
        previous_raw = dict(subtask.raw_result_json or {})
        if not (subtask.answer_content or "").strip():
            raw_ans = previous_raw.get("answerContent") or previous_raw.get("answer_content")
            if isinstance(raw_ans, str) and raw_ans.strip():
                subtask.answer_content = raw_ans
        if not (subtask.page_screenshot or "").strip():
            raw_shot = previous_raw.get("pageScreenshot") or previous_raw.get("page_screenshot")
            if isinstance(raw_shot, str) and raw_shot.strip():
                subtask.page_screenshot = raw_shot
        has_mol_result = bool(
            (subtask.answer_content or "").strip() or (subtask.page_screenshot or "").strip()
        )
        if not has_mol_result:
            raise ValueError("当前无可用快照，请粘贴分享链接补录")
        clear_subtask_backfill_dismiss(subtask)
        subtask.error_message = None
        subtask.status = "completed"
        recompute_subtask_rank_from_answer(
            db, subtask, task, override_mention_position=mention_position
        )
        manual_meta = {
            "source": "manual_snapshot",
            "snapshot_url": previous_raw.get("snapshot_url") or subtask.page_screenshot,
            "operator_user_id": current.user.id,
            "rank_only": True,
            "manual_rank_locked": True,
            "replaced": False,
        }
        if previous_raw.get("source"):
            manual_meta["replaced_previous_source"] = previous_raw.get("source")
        raw = dict(subtask.raw_result_json or previous_raw or {})
        raw.update(manual_meta)
        subtask.raw_result_json = raw

        write_operation_log(
            db,
            current,
            "排名补录",
            _snapshot_backfill_log_description(db, subtask, task, action_type="排名补录"),
            target_module="快照补录",
            tenant_id=task.tenant_id,
            risk_level="正常",
        )
        db.flush()
        db.commit()

        from app.services.monitor_stats_service import refresh_stats_after_subtask_backfill
        from app.services.monitor_service import invalidate_monitor_summary_cache

        if task.tenant_id:
            refresh_stats_after_subtask_backfill(
                db,
                task=task,
                subtask=subtask,
                previous_stat_date=previous_stat_date,
            )
            db.commit()
            invalidate_monitor_summary_cache(task.tenant_id, bust_overview=True)
        else:
            invalidate_monitor_summary_cache(bust_overview=True)
        resolve_subtask_backfill_notification(db, subtask.subtask_id)
        _bust_snapshot_backfill_matrix_cache()

        from app.services.lead_diagnosis_service import refresh_lead_diagnosis_after_backfill

        refresh_lead_diagnosis_after_backfill(db, task.task_id)

        db.refresh(subtask)
        db.refresh(task)
        asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
        groups = (
            [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
            if task.tenant_id
            else []
        )
        display = enrich_subtask_display_backfill_flags(
            serialize_subtask_for_display(
                subtask,
                monitor_keywords=task.monitor_keywords,
                asset=asset,
                keyword_groups=groups,
            ),
            subtask,
        )
        return {
            "subtask": display,
            "task": {
                "task_id": task.task_id,
                "status": task.status,
                "completed_items": task.completed_items,
                "failed_items": task.failed_items,
            },
            "brand_terms": _brand_terms_for_task(db, task, asset),
            "lead_context": _lead_context_for_task(db, task.task_id),
            "rank_only": True,
        }

    url = validate_snapshot_url(url_raw, platform=subtask.platform)
    # 只要补录就从分享页抓取并覆盖正文；可选手工正文仅作抓取失败时的兼容兜底
    fetched_refs: list[dict[str, Any]] = []
    fetch_meta: dict[str, Any] = {}
    content = (answer_content or "").strip()
    try:
        fetched = fetch_share_page(url)
        content = (fetched.answer_content or "").strip()
        fetched_refs = list(fetched.references or [])
        fetch_meta = {
            "fetch_host": fetched.source_host,
            "fetch_title": fetched.title,
            "fetch_reference_count": len(fetched_refs),
        }
    except ValueError:
        if not content:
            raise
        fetch_meta = {"fetch_skipped": True, "fetch_fallback": "manual_answer"}
    if not content:
        raise ValueError("未能解析分享页正文")

    previous_answer = subtask.answer_content
    previous_raw = dict(subtask.raw_result_json or {})
    previous_source = previous_raw.get("source")
    previous_shot = (subtask.page_screenshot or "").strip() or None

    clear_subtask_backfill_dismiss(subtask)
    # 2026-08-27 - 贴链补录留旧 CDN 图运营以为未生效 - 清空待异步新截图；rank_only/误填图链分支不动
    subtask.page_screenshot = None
    fetch_meta["screenshot_pending"] = True
    if previous_shot:
        fetch_meta["replaced_previous_screenshot"] = previous_shot
    subtask.answer_content = content
    subtask.error_message = None
    subtask.status = "completed"
    subtask.mention_context = None

    refs: list[dict[str, Any]] = []
    if reference_urls:
        for index, item in enumerate(reference_urls, start=1):
            text = str(item or "").strip()
            if text:
                refs.append({"index": index, "url": text, "title": text})
    if not refs and fetched_refs:
        refs = fetched_refs
    # 2026-08-14 - 补录抓到的引用也过静态资源过滤，与同步写入一致
    from app.services.monitor_service import _filter_citation_sources

    subtask.reference_list_json = _filter_citation_sources(refs) or None
    subtask.citation_list_json = None

    if sentiment:
        subtask.sentiment = sentiment.strip().lower()
    elif previous_answer:
        subtask.sentiment = None

    # 2026-07-27 - 补录写榜丢掉 category - 入库保留段内序与分类
    subtask.all_rankings_json = rankings_for_storage(_subtask_answer_plaintext(subtask), None)
    subtask.competitor_rankings_json = None

    # 2026-08-12 - 补录写入允许重算；批量洗数默认跳过 manual_snapshot
    recompute_subtask_rank_from_answer(
        db,
        subtask,
        task,
        override_mention_position=mention_position,
        force=mention_position is None,
    )

    manual_meta = {
        "source": "manual_snapshot",
        "snapshot_url": url,
        "operator_user_id": current.user.id,
        "replaced": bool(previous_answer),
        # 2026-08-12 - 补录位次一律锁定，避免规则升级洗数冲掉
        "manual_rank_locked": True,
        **fetch_meta,
    }
    if previous_answer:
        manual_meta["replaced_previous_source"] = previous_source
        manual_meta["replaced_previous_answer_preview"] = excerpt_sensitive_text(previous_answer, limit=80)
    # 在重算后的 raw 上合并补录元数据，避免冲掉 rank_resolution
    raw = dict(subtask.raw_result_json or previous_raw or {})
    raw.update(manual_meta)
    raw.pop("screenshot_ok", None)
    raw.pop("screenshot_error", None)
    subtask.raw_result_json = raw

    _reconcile_task_progress(task)
    task.failed_items = sum(
        1 for item in (task.subtasks or []) if item.status in {"failed", "stopped"} and not item.answer_content
    )
    task.completed_items = sum(1 for item in (task.subtasks or []) if item.answer_content)

    action_type = "快照覆盖" if previous_answer else "快照补录"
    write_operation_log(
        db,
        current,
        action_type,
        _snapshot_backfill_log_description(db, subtask, task, action_type=action_type),
        target_module="快照补录",
        tenant_id=task.tenant_id,
        risk_level="关注" if previous_answer else "正常",
    )

    db.flush()

    run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task.task_id))
    if run is not None and run.status == "failed" and (task.completed_items or 0) > 0:
        run.status = "completed"
        run.error_message = None

    db.commit()
    # commit 后再投递，避免 worker 读到未提交行
    try:
        mode = enqueue_backfill_screenshot(subtask_id=subtask.subtask_id, snapshot_url=url)
        # 2026-08-07 - 同步截图另开会话写库后，原 session 仍持旧 raw，再 commit 会盖掉 screenshot_ok
        db.refresh(subtask)
        raw2 = dict(subtask.raw_result_json or {})
        raw2["screenshot_enqueue"] = mode
        subtask.raw_result_json = raw2
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.refresh(subtask)
        raw2 = dict(subtask.raw_result_json or {})
        raw2["screenshot_pending"] = False
        raw2["screenshot_ok"] = False
        raw2["screenshot_error"] = f"enqueue_failed:{exc}"[:240]
        subtask.raw_result_json = raw2
        db.commit()

    from app.services.monitor_stats_service import refresh_stats_after_subtask_backfill
    from app.services.monitor_service import invalidate_monitor_summary_cache

    if task.tenant_id:
        refresh_stats_after_subtask_backfill(
            db,
            task=task,
            subtask=subtask,
            previous_stat_date=previous_stat_date,
        )
        db.commit()
        invalidate_monitor_summary_cache(task.tenant_id, bust_overview=True)
    else:
        invalidate_monitor_summary_cache(bust_overview=True)
    resolve_subtask_backfill_notification(db, subtask.subtask_id)
    _bust_snapshot_backfill_matrix_cache()

    from app.services.lead_diagnosis_service import refresh_lead_diagnosis_after_backfill

    refresh_lead_diagnosis_after_backfill(db, task.task_id)

    db.refresh(subtask)
    db.refresh(task)
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    display = enrich_subtask_display_backfill_flags(
        serialize_subtask_for_display(
            subtask,
            monitor_keywords=task.monitor_keywords,
            asset=asset,
            keyword_groups=groups,
        ),
        subtask,
    )
    return {
        "subtask": display,
        "task": {
            "task_id": task.task_id,
            "status": task.status,
            "completed_items": task.completed_items,
            "failed_items": task.failed_items,
        },
        "brand_terms": _brand_terms_for_task(db, task, asset),
        "lead_context": _lead_context_for_task(db, task.task_id),
    }



def build_backfill_notification_context(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    schedule_ctx: dict[str, Any] | None = None,
    tenant_name: str | None = None,
    lead_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tenant_name is None and task.tenant_id:
        tenant = db.get(Tenant, task.tenant_id)
        tenant_name = tenant.name if tenant else None
    if lead_ctx is None:
        lead_ctx = _lead_context_for_task(db, task.task_id)
    source = resolve_monitor_task_source(
        task,
        has_lead_run=bool(lead_ctx.get("lead_diagnosis_id")),
    )
    if schedule_ctx is None:
        schedule_ctx = _schedule_context_for_task(db, task)
    owner_user_id = resolve_backfill_owner_user_id(db, task, lead_ctx=lead_ctx)
    return {
        "subtask_id": subtask.subtask_id,
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "tenant_name": tenant_name,
        "owner_user_id": owner_user_id,
        "platform": subtask.platform,
        "prompt": subtask.prompt,
        "error_message": subtask.error_message,
        "source": source,
        "monitor_keywords": task.monitor_keywords,
        "task_status": task.status,
        "updated_at": subtask.updated_at.isoformat() if subtask.updated_at else None,
        "task_created_at": task.created_at.isoformat() if task.created_at else None,
        "schedule_key": schedule_ctx.get("schedule_key"),
        "schedule_window_key": schedule_ctx.get("schedule_window_key"),
        "schedule_label": schedule_ctx.get("schedule_label"),
        "schedule_source": schedule_ctx.get("schedule_source"),
        "region_code": schedule_ctx.get("region_code"),
        "region_label": schedule_ctx.get("region_label"),
        "lead_diagnosis_id": lead_ctx.get("lead_diagnosis_id") if source == "lead_diagnosis" else None,
        "brand_name": lead_ctx.get("brand_name") if source == "lead_diagnosis" else None,
    }


def _snapshot_backfill_log_description(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    action_type: str,
) -> str:
    """操作日志描述：仅使用业务可识别的企业/周期/词组/平台/问题，不含子任务 ID。"""
    ctx = build_backfill_notification_context(db, subtask, task)
    keyword_group = None
    if task.tenant_id:
        try:
            groups = list_keyword_groups(db, task.tenant_id)
            matched = _resolve_prompt_keyword_group(subtask.prompt or "", groups)
            if matched is not None:
                keyword_group = keyword_group_display_label(matched)
        except Exception:
            keyword_group = None
    if not keyword_group:
        keyword_group = str(task.monitor_keywords or "").strip() or None

    platform_names = _platform_display_names()
    platform_label = platform_names.get(subtask.platform or "", subtask.platform or "—")
    scope = ctx.get("brand_name") or ctx.get("tenant_name") or "未命名任务"
    schedule_label = str(ctx.get("schedule_label") or "").strip()
    region_label = str(ctx.get("region_label") or "").strip()
    prompt_text = (subtask.prompt or "").strip() or "—"
    if len(prompt_text) > 60:
        prompt_text = prompt_text[:59] + "…"

    detail_parts: list[str] = [scope]
    if schedule_label:
        detail_parts.append(schedule_label)
    if region_label and region_label != "全部区域":
        detail_parts.append(region_label)
    if keyword_group:
        detail_parts.append(f"词组「{keyword_group}」")
    detail_parts.append(platform_label)
    detail_parts.append(f"问题「{prompt_text}」")
    rank_text = subtask.mention_position
    if rank_text is not None:
        detail_parts.append(f"排名 {int(rank_text)}")
    return f"{action_type}：" + " · ".join(detail_parts)


def subtask_backfill_eligible(subtask: GeoMonitorSubtask, *, pending_only: bool = False) -> bool:
    """待补录项，或已有回答可覆盖更正的子任务。

    pending_only：已忽略不进待补列表。
    非 pending（矩阵）：已忽略仍保留，便于看排名/快照/继续补录，只是不再提醒。
    """
    if pending_only and subtask_backfill_dismissed(subtask):
        return False
    if pending_only:
        return subtask_needs_snapshot_backfill(subtask)
    # 2026-08-04 - 已忽略无正文占位被滤掉 - 矩阵丢格后缺口合并又造 is_gap
    if subtask_backfill_dismissed(subtask):
        return True
    if subtask_needs_snapshot_backfill(subtask):
        return True
    return bool((subtask.answer_content or "").strip())


def dismiss_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    current: CurrentSession,
) -> dict[str, Any]:
    """忽略该子任务待补提醒：保留答案/排名，矩阵仍可见，只退出提醒与待补红点。"""
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可忽略快照补录")

    subtask = get_monitor_subtask(db, subtask_id, current)
    task = get_monitor_task(db, subtask.task_id, current)

    if subtask_backfill_dismissed(subtask):
        item = build_snapshot_backfill_item(db, subtask, task)
        return {"subtask_id": subtask.subtask_id, "backfill_dismissed": True, "item": item}

    # 2026-07-28 - 点开即可忽略消红点 - 不要求仍是待补状态
    now = datetime.now(UTC).replace(tzinfo=None)
    if not _mark_subtask_dismissed(subtask, current.user.id, now):
        item = build_snapshot_backfill_item(db, subtask, task)
        return {"subtask_id": subtask.subtask_id, "backfill_dismissed": True, "item": item}

    dismiss_desc = _snapshot_backfill_log_description(db, subtask, task, action_type="忽略补录")
    write_operation_log(
        db,
        current,
        "忽略补录",
        f"{dismiss_desc} · 子任务 {subtask.subtask_id}",
        target_module="快照补录",
        tenant_id=task.tenant_id,
        risk_level="关注",
    )
    db.commit()
    resolve_subtask_backfill_notification(db, subtask.subtask_id)
    _bust_snapshot_backfill_matrix_cache()
    db.refresh(subtask)
    item = build_snapshot_backfill_item(db, subtask, task)
    return {"subtask_id": subtask.subtask_id, "backfill_dismissed": True, "item": item}


def undismiss_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    current: CurrentSession,
) -> dict[str, Any]:
    """取消忽略：若仍待补录则回列表并重新通知。"""
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可取消忽略快照补录")

    subtask = get_monitor_subtask(db, subtask_id, current)
    task = get_monitor_task(db, subtask.task_id, current)

    if not subtask_backfill_dismissed(subtask):
        item = build_snapshot_backfill_item(db, subtask, task)
        return {"subtask_id": subtask.subtask_id, "backfill_dismissed": False, "item": item}

    clear_subtask_backfill_dismiss(subtask)
    undismiss_desc = _snapshot_backfill_log_description(db, subtask, task, action_type="取消忽略补录")
    write_operation_log(
        db,
        current,
        "取消忽略补录",
        f"{undismiss_desc} · 子任务 {subtask.subtask_id}",
        target_module="快照补录",
        tenant_id=task.tenant_id,
        risk_level="正常",
    )
    db.commit()
    db.refresh(subtask)
    item = build_snapshot_backfill_item(db, subtask, task)
    if item.get("needs_backfill"):
        _notify_subtask_backfill(db, subtask, task, ctx=item)
    return {"subtask_id": subtask.subtask_id, "backfill_dismissed": False, "item": item}


BATCH_DISMISS_CHUNK = 200
BATCH_DISMISS_MAX = 3000
BATCH_DISMISS_SLOTS_MAX = 5000


def _gap_dismiss_matrix_key(
    *,
    platform: str,
    prompt: str,
    day_text: str,
    schedule_window_key: str,
) -> tuple[str, str, str, str]:
    return (platform, prompt, day_text, schedule_window_key)


def _load_dismissed_gap_matrix_keys(
    db: Session,
    *,
    tenant_id: int,
    d0: date,
    d1: date,
) -> set[tuple[str, str, str, str]]:
    """批量忽略登记的漏跑缺口，矩阵合并时跳过。"""
    start_key = f"{d0.strftime('%Y%m%d')}-0000"
    end_key = f"{d1.strftime('%Y%m%d')}-9999"
    rows = db.execute(
        select(
            GeoSnapshotBackfillGapDismiss.platform,
            GeoSnapshotBackfillGapDismiss.prompt,
            GeoSnapshotBackfillGapDismiss.schedule_window_key,
        ).where(
            GeoSnapshotBackfillGapDismiss.tenant_id == int(tenant_id),
            GeoSnapshotBackfillGapDismiss.schedule_window_key >= start_key,
            GeoSnapshotBackfillGapDismiss.schedule_window_key <= end_key,
        )
    ).all()
    keys: set[tuple[str, str, str, str]] = set()
    for plat, prompt, window_key in rows:
        text = str(window_key or "").strip()
        if len(text) < 8 or not text[:8].isdigit():
            continue
        day_text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        keys.add(
            _gap_dismiss_matrix_key(
                platform=str(plat or "").strip(),
                prompt=str(prompt or "").strip(),
                day_text=day_text,
                schedule_window_key=text,
            )
        )
    return keys


def _bulk_insert_gap_dismissals(
    db: Session,
    *,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    stmt = mysql_insert(GeoSnapshotBackfillGapDismiss).values(rows)
    stmt = stmt.prefix_with("IGNORE")
    result = db.execute(stmt)
    return int(result.rowcount or 0)


def dismiss_snapshot_backfill_slots(
    db: Session,
    *,
    current: CurrentSession,
    slots: list[SnapshotBackfillBatchDismissSlot],
) -> dict[str, Any]:
    """按前端已加载矩阵场次批量忽略，跳过重扫矩阵。"""
    # 2026-08-28 - 一键忽略要即时 - bulk UPDATE + 缺口登记表，不再逐条 ensure_gap
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可忽略快照补录")
    if not slots:
        return {"dismissed": 0, "skipped": 0, "truncated": False, "todo_only": True}

    from app.services.monitor_service import ensure_sales_tenant_access

    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = current.user.id
    gap_rows: list[dict[str, Any]] = []
    subtask_ids: list[str] = []
    seen_subtask: set[str] = set()
    seen_gap: set[tuple[int, str, str, str]] = set()
    checked_tenants: set[int] = set()

    for slot in slots[:BATCH_DISMISS_SLOTS_MAX]:
        sid = str(slot.subtask_id or "").strip()
        if slot.is_gap or not sid:
            tenant_slot = slot.tenant_id
            window_key = str(slot.schedule_window_key or "").strip()
            prompt = str(slot.prompt or "").strip()
            plat = str(slot.platform or "").strip()
            if tenant_slot is None or not window_key or not prompt or not plat:
                continue
            gap_key = (int(tenant_slot), plat, prompt, window_key)
            if gap_key in seen_gap:
                continue
            seen_gap.add(gap_key)
            if int(tenant_slot) not in checked_tenants:
                ensure_sales_tenant_access(db, current, int(tenant_slot))
                checked_tenants.add(int(tenant_slot))
            gap_rows.append(
                {
                    "tenant_id": int(tenant_slot),
                    "platform": plat,
                    "prompt": prompt,
                    "schedule_window_key": window_key,
                    "dismissed_at": now,
                    "dismissed_by": user_id,
                }
            )
            continue
        if sid in seen_subtask:
            continue
        seen_subtask.add(sid)
        subtask_ids.append(sid)

    dismissed = 0
    skipped = 0

    if subtask_ids:
        allowed_ids = list(
            db.scalars(
                select(GeoMonitorSubtask.subtask_id)
                .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
                .where(
                    GeoMonitorSubtask.subtask_id.in_(subtask_ids),
                    GeoMonitorSubtask.backfill_dismissed_at.is_(None),
                    GeoMonitorTask.deleted.is_(False),
                )
            )
        )
        skipped += max(0, len(subtask_ids) - len(allowed_ids))
        tenant_ids = list(
            db.scalars(
                select(GeoMonitorTask.tenant_id)
                .join(GeoMonitorSubtask, GeoMonitorSubtask.task_id == GeoMonitorTask.task_id)
                .where(
                    GeoMonitorSubtask.subtask_id.in_(allowed_ids),
                    GeoMonitorTask.tenant_id.isnot(None),
                )
                .distinct()
            )
        )
        for tenant_slot in tenant_ids:
            if tenant_slot is None or int(tenant_slot) in checked_tenants:
                continue
            ensure_sales_tenant_access(db, current, int(tenant_slot))
            checked_tenants.add(int(tenant_slot))
        if allowed_ids:
            result = db.execute(
                update(GeoMonitorSubtask)
                .where(
                    GeoMonitorSubtask.subtask_id.in_(allowed_ids),
                    GeoMonitorSubtask.backfill_dismissed_at.is_(None),
                )
                .values(backfill_dismissed_at=now, backfill_dismissed_by=user_id)
            )
            dismissed += int(result.rowcount or 0)

    if gap_rows:
        _bulk_insert_gap_dismissals(db, rows=gap_rows)
        dismissed += len(gap_rows)

    truncated = len(slots) > BATCH_DISMISS_SLOTS_MAX
    if dismissed:
        write_operation_log(
            db,
            current,
            "批量忽略补录",
            f"按矩阵场次批量忽略 {dismissed} 条待补场次"
            + (f"（另有 {skipped} 条跳过）" if skipped else "")
            + (f"；截断上限 {BATCH_DISMISS_SLOTS_MAX}" if truncated else ""),
            target_module="快照补录",
            tenant_id=next(iter(checked_tenants), None),
            risk_level="关注",
        )
        db.commit()
        _bust_snapshot_backfill_matrix_cache()

    return {
        "dismissed": dismissed,
        "skipped": skipped,
        "truncated": truncated,
        "todo_only": True,
    }


def _collect_batch_dismiss_targets(
    cells: list[dict[str, Any]],
    *,
    todo_only: bool,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """从矩阵格收集待忽略场次；todo_only 时红点格内全部未忽略场次都纳入。"""
    targets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for cell in cells:
        if todo_only and not cell.get("has_todo"):
            continue
        for slot in cell.get("slots") or []:
            if slot.get("backfill_dismissed"):
                continue
            if todo_only:
                if slot.get("is_gap") or slot.get("subtask_id"):
                    targets.append((cell, slot))
            elif _slot_is_batch_dismissable(slot):
                targets.append((cell, slot))
    return targets


def dismiss_snapshot_backfill_batch(
    db: Session,
    *,
    current: CurrentSession,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    allowed_lead_task_ids: list[str] | None = None,
    detect_date_from: date | None = None,
    detect_date_to: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
    todo_only: bool = False,
) -> dict[str, Any]:
    """按矩阵筛选批量忽略待补录，减少逐条点忽略。"""
    # 2026-08-28 - 补录页红点过多 - 按当前筛选一键忽略，默认仅 has_todo 格子
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可忽略快照补录")

    matrix = list_snapshot_backfill_matrix(
        db,
        tenant_id=tenant_id,
        tenant_ids=tenant_ids,
        allowed_lead_task_ids=allowed_lead_task_ids,
        detect_date_from=detect_date_from,
        detect_date_to=detect_date_to,
        source=source,
        platform=platform,
        keyword=keyword,
        keyword_group=keyword_group,
    )
    targets = _collect_batch_dismiss_targets(matrix.get("cells") or [], todo_only=todo_only)

    truncated = len(targets) > BATCH_DISMISS_MAX
    if truncated:
        targets = targets[:BATCH_DISMISS_MAX]

    now = datetime.now(UTC).replace(tzinfo=None)
    dismissed = 0
    skipped = 0
    resolved_ids: list[str] = []

    # 2026-08-28 - 批量忽略慢/漏清 - 矩阵只扫一次，缺口占位 defer commit，按块提交
    for chunk_start in range(0, len(targets), BATCH_DISMISS_CHUNK):
        chunk = targets[chunk_start : chunk_start + BATCH_DISMISS_CHUNK]
        chunk_resolved: list[str] = []
        for cell, slot in chunk:
            subtask: GeoMonitorSubtask | None = None
            subtask_id = str(slot.get("subtask_id") or "").strip()
            if slot.get("is_gap") or not subtask_id:
                tenant_slot = slot.get("tenant_id") or tenant_id
                window_key = str(slot.get("schedule_window_key") or "").strip()
                prompt = str(slot.get("prompt") or cell.get("word") or "").strip()
                plat = str(slot.get("platform") or cell.get("platform") or "").strip()
                if tenant_slot is None or not window_key or not prompt or not plat:
                    skipped += 1
                    continue
                try:
                    subtask = ensure_gap_backfill_subtask(
                        db,
                        tenant_id=int(tenant_slot),
                        platform=plat,
                        prompt=prompt,
                        schedule_window_key=window_key,
                        current=current,
                        auto_commit=False,
                    )
                    subtask_id = subtask.subtask_id
                except Exception:
                    skipped += 1
                    continue
            else:
                try:
                    subtask = get_monitor_subtask(db, subtask_id, current)
                except (ValueError, PermissionError):
                    skipped += 1
                    continue

            if subtask is None:
                skipped += 1
                continue
            if _mark_subtask_dismissed(subtask, current.user.id, now):
                dismissed += 1
                chunk_resolved.append(subtask_id)
                resolved_ids.append(subtask_id)
            else:
                skipped += 1

        if chunk_resolved:
            db.commit()
            for sid in chunk_resolved:
                resolve_subtask_backfill_notification(db, sid)

    if dismissed:
        write_operation_log(
            db,
            current,
            "批量忽略补录",
            f"当前筛选下批量忽略 {dismissed} 条待补场次"
            + (f"（另有 {skipped} 条跳过）" if skipped else "")
            + (f"；截断上限 {BATCH_DISMISS_MAX}" if truncated else ""),
            target_module="快照补录",
            tenant_id=tenant_id,
            risk_level="关注",
        )
        db.commit()
        _bust_snapshot_backfill_matrix_cache()

    return {
        "dismissed": dismissed,
        "skipped": skipped,
        "truncated": truncated,
        "todo_only": todo_only,
    }


def build_snapshot_backfill_item(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    schedule_runs_map: dict[str, GeoMonitorScheduleRun] | None = None,
    lead_runs_map: dict[str, LeadDiagnosisRun] | None = None,
    keyword_groups_cache: dict[int, list] | None = None,
    keyword_group_dict_cache: dict[int, list[dict[str, Any]]] | None = None,
    brand_asset_cache: dict[int, BrandAsset | None] | None = None,
    tenant_name: str | None = None,
    lead_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运营端快照补录单条展示字段，与列表/通知/详情抽屉共用。"""
    keyword_groups_cache = keyword_groups_cache if keyword_groups_cache is not None else {}
    keyword_group_dict_cache = keyword_group_dict_cache if keyword_group_dict_cache is not None else {}
    brand_asset_cache = brand_asset_cache if brand_asset_cache is not None else {}

    schedule_ctx = _schedule_context_for_task(
        db,
        task,
        schedule_runs_map=schedule_runs_map,
        lead_runs_map=lead_runs_map,
        brand_asset_cache=brand_asset_cache,
    )
    ctx = build_backfill_notification_context(
        db,
        subtask,
        task,
        schedule_ctx=schedule_ctx,
        tenant_name=tenant_name,
        lead_ctx=lead_ctx,
    )

    if task.tenant_id:
        if task.tenant_id not in keyword_groups_cache:
            try:
                orm_groups = list_keyword_groups(db, task.tenant_id)
            except Exception:
                orm_groups = []
            keyword_groups_cache[task.tenant_id] = orm_groups
            keyword_group_dict_cache[task.tenant_id] = [
                keyword_group_to_dict(item)
                for item in orm_groups
                if item.status and item.monitor_keyword
            ]
        keyword_group_rows = keyword_groups_cache[task.tenant_id]
        keyword_group_dicts = keyword_group_dict_cache[task.tenant_id]
    else:
        keyword_group_rows = []
        keyword_group_dicts = []

    matched_group = _resolve_prompt_keyword_group(subtask.prompt or "", keyword_group_rows)
    if matched_group is not None:
        ctx["keyword_group"] = keyword_group_display_label(matched_group)
    else:
        ctx["keyword_group"] = str(task.monitor_keywords or "").strip() or None
    ctx["sentiment"] = subtask.sentiment
    # 对外展示走代理；勿覆盖 serialize 后的脱敏 URL（include_ops 合并时会带上本字段）
    ctx["page_screenshot"] = public_screenshot_url(subtask.page_screenshot)
    ctx["has_answer"] = bool((subtask.answer_content or "").strip())
    ctx["status"] = subtask.status

    asset = brand_asset_cache.get(task.tenant_id) if task.tenant_id else None
    if task.tenant_id and task.tenant_id not in brand_asset_cache:
        try:
            brand_asset_cache[task.tenant_id] = get_brand_asset(db, task.tenant_id)
        except Exception:
            brand_asset_cache[task.tenant_id] = None
        asset = brand_asset_cache[task.tenant_id]

    rank_display = serialize_subtask_for_display(
        subtask,
        monitor_keywords=task.monitor_keywords,
        asset=asset,
        keyword_groups=keyword_group_dicts,
    )
    ctx["mention_position"] = rank_display.get("mention_position")
    ctx["raw_mention_position"] = rank_display.get("raw_mention_position")
    ctx["brand_rank"] = rank_display.get("brand_rank", rank_display.get("mention_position"))
    ctx["brand_mentioned"] = rank_display.get("brand_mentioned")
    ctx["prompt_intent"] = rank_display.get("prompt_intent")
    ctx["rank_source"] = rank_display.get("rank_source")
    ctx["rank_category"] = rank_display.get("rank_category")
    ctx["rank_basis"] = rank_display.get("rank_basis")
    # 与卡片展示位次一致，避免库内 raw 差位却已重算进 Top3 仍标「待补录」
    display_rank = rank_display.get("mention_position")
    effective: int | None
    try:
        effective = int(display_rank) if display_rank is not None else None
    except (TypeError, ValueError):
        effective = None
    needs = subtask_needs_snapshot_backfill(
        subtask,
        effective_rank=effective,
        use_effective_rank=True,
        brand_mentioned=rank_display.get("brand_mentioned"),
    )
    dismissed = subtask_backfill_dismissed(subtask)
    ctx["backfill_dismissed"] = dismissed
    # 列表口径：已忽略不再算待补录；详情深链仍可通过 backfill_dismissed 看到并取消忽略
    ctx["needs_backfill"] = bool(needs) and not dismissed
    ctx["needs_backfill_raw"] = bool(needs)
    return ctx


def _lead_context_from_maps(
    db: Session,
    task_id: str,
    lead_runs_map: dict[str, LeadDiagnosisRun],
    lead_cache: dict[int, LeadDiagnosis],
) -> dict[str, Any]:
    run = lead_runs_map.get(task_id)
    if run is None:
        return {}
    lead = lead_cache.get(run.lead_diagnosis_id)
    if lead is None:
        lead = db.get(LeadDiagnosis, run.lead_diagnosis_id)
        if lead is not None:
            lead_cache[run.lead_diagnosis_id] = lead
    return {
        "lead_diagnosis_id": run.lead_diagnosis_id,
        "brand_name": lead.brand_name if lead else None,
        "created_by_user_id": lead.created_by_user_id if lead else None,
    }


def _snapshot_backfill_sort_key(schedule_ctx: dict[str, Any], subtask: GeoMonitorSubtask) -> str:
    return "|".join(
        [
            str(schedule_ctx.get("schedule_key") or ""),
            str(subtask.platform or ""),
            str(subtask.prompt or ""),
        ]
    )


def _resolve_snapshot_backfill_source(
    task: GeoMonitorTask,
    lead_ctx: dict[str, Any],
) -> str:
    return resolve_monitor_task_source(
        task,
        has_lead_run=bool(lead_ctx.get("lead_diagnosis_id")),
    )


def _is_lead_diagnosis_backfill_task(db: Session, task: GeoMonitorTask) -> bool:
    """独立售前抓取任务（无签约 tenant）。"""
    if task.tenant_id:
        return False
    lead_ctx = _lead_context_for_task(db, task.task_id)
    return _resolve_snapshot_backfill_source(task, lead_ctx) == "lead_diagnosis"


def _matches_keyword_group_filter(
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    keyword_group_filter: str,
    keyword_group_dicts: list[dict[str, Any]],
    keyword_group_rows: list,
) -> bool:
    if not keyword_group_filter:
        return True
    matched_group = _resolve_prompt_keyword_group(subtask.prompt or "", keyword_group_rows)
    keyword_group_label = (
        keyword_group_display_label(matched_group)
        if matched_group is not None
        else str(task.monitor_keywords or "").strip() or None
    )
    return _snapshot_backfill_matches_keyword_group(
        subtask,
        {
            "keyword_group": keyword_group_label,
            "monitor_keywords": task.monitor_keywords,
        },
        keyword_group=keyword_group_filter,
        keyword_group_dicts=keyword_group_dicts,
    )


def _snapshot_backfill_matches_keyword_group(
    subtask: GeoMonitorSubtask,
    ctx: dict[str, Any],
    *,
    keyword_group: str,
    keyword_group_dicts: list[dict[str, Any]],
) -> bool:
    group_filter = str(keyword_group or "").strip()
    if not group_filter:
        return True
    selected = _resolve_keyword_group_filter(group_filter, keyword_group_dicts) if keyword_group_dicts else None
    if selected is not None:
        return _prompt_belongs_to_group(
            subtask.prompt or "",
            keyword_group_monitor_keywords(selected),
            selected.get("exposure_terms") or [],
        )
    lower = group_filter.lower()
    haystacks = [
        ctx.get("keyword_group") or "",
        subtask.prompt or "",
        ctx.get("monitor_keywords") or "",
    ]
    return any(lower in str(text).lower() for text in haystacks if text)


def list_snapshot_backfill_page(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    allowed_lead_task_ids: list[str] | None = None,
    detect_date: date | None = None,
    detect_date_from: date | None = None,
    detect_date_to: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
    pending_only: bool = False,
    offset: int = 0,
    limit: int = 50,
    include_summary: bool = True,
    light: bool = False,
) -> dict[str, Any]:
    """运营端快照补录列表（含汇总统计），可按企业/检测日(区间)/来源/平台/关键词筛选。

    include_summary=False 时尽早凑齐本页后停止扫描，供首屏轻量加载；
    汇总请另请求 include_summary=True（可走短缓存）。
    light=True：矩阵专用，跳过展示位次对账，只取库内位次与待补标记。
    """
    platform_code = str(platform or "").strip()
    keyword_text = str(keyword or "").strip()
    keyword_group_filter = str(keyword_group or "").strip()
    source_filter = str(source or "").strip()

    # 2026-07-28 - 补录支持日期区间 - 单日参数兼容映射到 from/to
    range_from = detect_date_from
    range_to = detect_date_to
    if detect_date is not None and range_from is None and range_to is None:
        range_from = range_to = detect_date
    if range_from is not None and range_to is not None and range_from > range_to:
        range_from, range_to = range_to, range_from

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            # 品牌词不进补录运营台；售前无 tenant 的 lead 任务仍可进
            or_(GeoMonitorTask.purpose == "geo", GeoMonitorTask.tenant_id.is_(None)),
        )
        .order_by(GeoMonitorTask.created_at.desc(), GeoMonitorSubtask.updated_at.desc())
    )
    if tenant_ids is not None:
        if allowed_lead_task_ids is not None:
            lead_scope = (
                and_(
                    GeoMonitorTask.tenant_id.is_(None),
                    GeoMonitorTask.task_id.in_(allowed_lead_task_ids),
                )
                if allowed_lead_task_ids
                else false()
            )
            if tenant_ids:
                stmt = stmt.where(or_(GeoMonitorTask.tenant_id.in_(tenant_ids), lead_scope))
            else:
                stmt = stmt.where(lead_scope)
        else:
            stmt = stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    elif tenant_id is not None:
        stmt = stmt.where(GeoMonitorTask.tenant_id == tenant_id)
    elif allowed_lead_task_ids is not None:
        if not allowed_lead_task_ids:
            stmt = stmt.where(false())
        else:
            stmt = stmt.where(
                GeoMonitorTask.tenant_id.is_(None),
                GeoMonitorTask.task_id.in_(allowed_lead_task_ids),
            )

    if platform_code:
        stmt = stmt.where(GeoMonitorSubtask.platform == platform_code)
    if source_filter == "lead_diagnosis":
        if allowed_lead_task_ids is not None:
            if not allowed_lead_task_ids:
                stmt = stmt.where(false())
            else:
                stmt = stmt.where(
                    GeoMonitorTask.tenant_id.is_(None),
                    GeoMonitorTask.task_id.in_(allowed_lead_task_ids),
                )
        else:
            lead_task_ids = select(LeadDiagnosisRun.task_id).where(LeadDiagnosisRun.task_id.isnot(None))
            stmt = stmt.where(
                GeoMonitorTask.tenant_id.is_(None),
                GeoMonitorTask.task_id.in_(lead_task_ids),
            )
    elif source_filter == "tenant_monitor":
        lead_task_ids = select(LeadDiagnosisRun.task_id).where(LeadDiagnosisRun.task_id.isnot(None))
        stmt = stmt.where(
            or_(
                GeoMonitorTask.tenant_id.isnot(None),
                GeoMonitorTask.task_id.notin_(lead_task_ids),
            )
        )
    if range_from is not None or range_to is not None:
        d0 = range_from or range_to
        d1 = range_to or range_from
        assert d0 is not None and d1 is not None
        start_key = d0.strftime("%Y%m%d")
        end_key_exclusive = (d1 + timedelta(days=1)).strftime("%Y%m%d")
        lead_task_ids = select(LeadDiagnosisRun.task_id).where(
            LeadDiagnosisRun.task_id.isnot(None),
            LeadDiagnosisRun.schedule_key >= start_key,
            LeadDiagnosisRun.schedule_key < end_key_exclusive,
        )
        schedule_task_ids = select(GeoMonitorScheduleRun.task_id).where(
            GeoMonitorScheduleRun.schedule_key >= start_key,
            GeoMonitorScheduleRun.schedule_key < end_key_exclusive,
        )
        stmt = stmt.where(
            or_(
                GeoMonitorTask.task_id.in_(lead_task_ids),
                GeoMonitorTask.task_id.in_(schedule_task_ids),
                and_(
                    func.date(GeoMonitorTask.created_at) >= d0,
                    func.date(GeoMonitorTask.created_at) <= d1,
                ),
            )
        )

    # 2026-07-28 - 忽略后矩阵丢排名/点不开 - 仅待补列表排除已忽略；矩阵仍保留场次
    if pending_only:
        stmt = stmt.where(GeoMonitorSubtask.backfill_dismissed_at.is_(None))

    no_answer = or_(GeoMonitorSubtask.answer_content.is_(None), GeoMonitorSubtask.answer_content == "")
    if pending_only:
        fail_pending = and_(
            no_answer,
            or_(
                GeoMonitorSubtask.status.in_(("failed", "stopped")),
                and_(
                    GeoMonitorSubtask.error_message.isnot(None),
                    GeoMonitorSubtask.error_message != "",
                    GeoMonitorSubtask.status.in_(tuple(TERMINAL_STATUSES)),
                ),
            ),
        )
        # 有回答先全捞，再按展示位次筛：仅前 N 放过（库内 Top3 但展示无位次也要进）
        stmt = stmt.where(or_(fail_pending, ~no_answer))
    if keyword_text:
        stmt = stmt.where(GeoMonitorSubtask.prompt.like(f"%{keyword_text}%"))

    has_scope_filter = bool(
        tenant_id
        or tenant_ids
        or range_from
        or range_to
        or platform_code
        or keyword_text
        or keyword_group_filter
        or source_filter
    )
    if tenant_id is None and not tenant_ids:
        # ponytail: 无筛选时收紧扫描上限，避免 2500~4000 行全进内存再 slice
        scan_cap = min(max(limit * 12, 400), 800) if not has_scope_filter else min(max(limit * 20, 800), 1500)
    else:
        scan_cap = None
    # 首屏轻量：缩小扫描窗口，稍后再拉全量汇总
    if not include_summary:
        light_cap = max(int(limit or 50) * 5, 100)
        scan_cap = light_cap if scan_cap is None else min(scan_cap, light_cap)
    if scan_cap is not None:
        stmt = stmt.limit(scan_cap)

    # 2026-07-29 - 运营总览 503「Out of sort memory」- ORDER BY 时 SELECT 全量子任务宽列（answer/raw JSON）撑爆 sort buffer；先只取 id 再按 id 装载
    id_stmt = stmt.with_only_columns(GeoMonitorSubtask.id, maintain_column_froms=True)
    ordered_ids = list(db.scalars(id_stmt))
    rows: list[GeoMonitorSubtask] = []
    if ordered_ids:
        by_id = {
            item.id: item
            for item in db.scalars(
                select(GeoMonitorSubtask).where(GeoMonitorSubtask.id.in_(ordered_ids))
            )
        }
        rows = [by_id[i] for i in ordered_ids if i in by_id]
    task_ids = {item.task_id for item in rows}
    tasks = {
        item.task_id: item
        for item in db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.task_id.in_(task_ids)))
    } if task_ids else {}
    schedule_runs_map = schedule_runs_for_tasks(db, list(task_ids))
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, list(task_ids))

    tenant_name_map: dict[int, str] = {}
    if tasks:
        tenant_ids_in_page = {task.tenant_id for task in tasks.values() if task.tenant_id}
        if tenant_ids_in_page:
            tenant_name_map = {
                row.id: row.name
                for row in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids_in_page)))
            }

    keyword_groups_cache: dict[int, list] = {}
    keyword_group_dict_cache: dict[int, list[dict[str, Any]]] = {}
    brand_asset_cache: dict[int, BrandAsset | None] = {}
    lead_cache: dict[int, LeadDiagnosis] = {}

    candidates: list[tuple[GeoMonitorSubtask, GeoMonitorTask, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    pending_count = 0
    overwrite_count = 0
    for subtask in rows:
        task = tasks.get(subtask.task_id)
        # 列表预筛：pending_only 时 SQL 可能仍带上 raw>阈值项，最终以展示位次为准再滤。
        if task is None or not subtask_backfill_eligible(subtask, pending_only=False):
            continue

        lead_ctx = _lead_context_from_maps(db, task.task_id, lead_runs_map, lead_cache)
        task_source = _resolve_snapshot_backfill_source(task, lead_ctx)
        if source_filter and task_source != source_filter:
            continue

        keyword_group_rows: list = []
        keyword_group_dicts: list[dict[str, Any]] = []
        # light 矩阵且无词组筛选：跳过词组库查询
        if task.tenant_id and (keyword_group_filter or not light):
            if task.tenant_id not in keyword_groups_cache:
                try:
                    orm_groups = list_keyword_groups(db, task.tenant_id)
                except Exception:
                    orm_groups = []
                keyword_groups_cache[task.tenant_id] = orm_groups
                keyword_group_dict_cache[task.tenant_id] = [
                    keyword_group_to_dict(item)
                    for item in orm_groups
                    if item.status and item.monitor_keyword
                ]
            keyword_group_rows = keyword_groups_cache[task.tenant_id]
            keyword_group_dicts = keyword_group_dict_cache[task.tenant_id]

        if not _matches_keyword_group_filter(
            subtask,
            task,
            keyword_group_filter=keyword_group_filter,
            keyword_group_dicts=keyword_group_dicts,
            keyword_group_rows=keyword_group_rows,
        ):
            continue

        schedule_ctx = _schedule_context_for_task(
            db,
            task,
            schedule_runs_map=schedule_runs_map,
            lead_runs_map=lead_runs_map,
            brand_asset_cache=brand_asset_cache,
        )
        if light:
            item = build_snapshot_backfill_matrix_sample(
                subtask,
                task,
                schedule_ctx=schedule_ctx,
                tenant_name=tenant_name_map.get(task.tenant_id) if task.tenant_id else None,
                lead_ctx=lead_ctx,
            )
        else:
            item = build_snapshot_backfill_item(
                db,
                subtask,
                task,
                schedule_runs_map=schedule_runs_map,
                lead_runs_map=lead_runs_map,
                keyword_groups_cache=keyword_groups_cache,
                keyword_group_dict_cache=keyword_group_dict_cache,
                brand_asset_cache=brand_asset_cache,
                tenant_name=tenant_name_map.get(task.tenant_id) if task.tenant_id else None,
                lead_ctx=lead_ctx,
            )
        needs = bool(item.get("needs_backfill"))
        has_answer = bool(item.get("has_answer"))
        if pending_only and not needs:
            continue
        candidates.append((subtask, task, schedule_ctx, lead_ctx, item))
        if needs:
            pending_count += 1
        elif has_answer:
            overwrite_count += 1

    candidates.sort(
        key=lambda row: _snapshot_backfill_sort_key(row[2], row[0]),
        reverse=True,
    )
    total = len(candidates)
    page_offset = max(0, int(offset or 0))
    page_candidates = candidates[page_offset:page_offset + limit]
    page_items = [item for _subtask, _task, _schedule_ctx, _lead_ctx, item in page_candidates]
    return {
        "items": page_items,
        "summary": {
            "total": total,
            "pending": pending_count,
            "overwrite": overwrite_count,
            "shown": len(page_items),
            "offset": page_offset,
            "limit": limit,
            "has_more": page_offset + len(page_items) < total,
            "scan_capped": bool(scan_cap is not None and len(rows) >= scan_cap),
            "summary_partial": not include_summary,
        },
    }


def list_snapshot_backfill_matrix(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    allowed_lead_task_ids: list[str] | None = None,
    detect_date_from: date | None = None,
    detect_date_to: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
) -> dict[str, Any]:
    """词×日热力：格内为日三次均值；红点=均值>阈值或算不出均值。"""
    today = date.today()
    d1 = detect_date_to or today
    d0 = detect_date_from or (d1 - timedelta(days=6))
    if d0 > d1:
        d0, d1 = d1, d0
    # 区间最多 31 天，避免一次扫爆
    if (d1 - d0).days > 30:
        d0 = d1 - timedelta(days=30)

    payload = list_snapshot_backfill_page(
        db,
        tenant_id=tenant_id,
        tenant_ids=tenant_ids,
        allowed_lead_task_ids=allowed_lead_task_ids,
        detect_date_from=d0,
        detect_date_to=d1,
        source=source,
        platform=platform,
        keyword=keyword,
        keyword_group=keyword_group,
        pending_only=False,
        offset=0,
        limit=4000,
        include_summary=True,
        light=True,
    )
    items = payload.get("items") or []
    platform_names = _platform_display_names()
    # 2026-07-28 - 全平台对比露出历史端 - 补录侧栏只认配置精确码，不做 desktop/mobile 成对放宽
    purchased_platforms: list[str] = []
    if tenant_id is not None:
        purchased_platforms = tenant_purchased_platforms(db, int(tenant_id))
    purchased_exact = {code for code in purchased_platforms if code}

    dates: list[str] = []
    cursor = d0
    while cursor <= d1:
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)

    # key: (platform, word, date) -> samples
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    word_order: list[str] = []
    word_seen: set[str] = set()
    platform_order: list[str] = []
    platform_seen: set[str] = set()

    for item in items:
        plat = str(item.get("platform") or "").strip()
        if not plat:
            continue
        if purchased_exact and plat not in purchased_exact:
            continue
        word = str(item.get("prompt") or item.get("keyword_group") or item.get("monitor_keywords") or "").strip()
        if not word:
            continue
        day = _detect_day_from_schedule(item)
        if not day or day < d0.isoformat() or day > d1.isoformat():
            # 无调度日时退回 updated_at 日期
            updated = str(item.get("updated_at") or "")[:10]
            day = updated if updated and d0.isoformat() <= updated <= d1.isoformat() else None
        if not day:
            continue
        if plat not in platform_seen:
            platform_seen.add(plat)
            platform_order.append(plat)
        if word not in word_seen:
            word_seen.add(word)
            word_order.append(word)
        buckets[(plat, word, day)].append(item)

    cells: list[dict[str, Any]] = []
    platform_stats: dict[str, dict[str, Any]] = {
        code: {"id": code, "name": platform_names.get(code) or code, "todo": 0, "fail": 0, "avg_ranks": []}
        for code in platform_order
    }

    for (plat, word, day), samples in buckets.items():
        ranks: list[float] = []
        fail_count = 0
        slots: list[dict[str, Any]] = []
        for sample in samples:
            rank = sample.get("mention_position")
            try:
                if rank is not None:
                    ranks.append(float(rank))
            except (TypeError, ValueError):
                pass
            is_fail = bool(sample.get("needs_backfill")) and not bool(sample.get("has_answer"))
            if is_fail:
                fail_count += 1
            slots.append(
                {
                    "subtask_id": sample.get("subtask_id"),
                    "task_id": sample.get("task_id"),
                    "schedule_label": sample.get("schedule_label"),
                    "schedule_window_key": sample.get("schedule_window_key"),
                    "mention_position": sample.get("mention_position"),
                    "needs_backfill": bool(sample.get("needs_backfill")),
                    "backfill_dismissed": bool(sample.get("backfill_dismissed")),
                    "has_answer": bool(sample.get("has_answer")),
                    "status": sample.get("status"),
                    "error_message": sample.get("error_message"),
                    "prompt": sample.get("prompt"),
                    "platform": plat,
                    "tenant_id": sample.get("tenant_id"),
                    "tenant_name": sample.get("tenant_name"),
                    "brand_name": sample.get("brand_name"),
                    "source": sample.get("source"),
                    "monitor_keywords": sample.get("monitor_keywords"),
                    "keyword_group": sample.get("keyword_group"),
                    "updated_at": sample.get("updated_at"),
                }
            )
        avg = _average_mention_position(ranks)
        # 2026-07-28 - 忽略后红点仍在 - 红点只看未忽略场次的日均；全忽略则灭
        active_samples = [sample for sample in samples if not sample.get("backfill_dismissed")]
        active_ranks: list[float] = []
        for sample in active_samples:
            rank = sample.get("mention_position")
            try:
                if rank is not None:
                    active_ranks.append(float(rank))
            except (TypeError, ValueError):
                pass
        has_todo = matrix_cell_has_todo(ranks=active_ranks, sample_count=len(active_samples))
        cells.append(
            {
                "platform": plat,
                "word": word,
                "date": day,
                "rank": avg,
                "has_todo": has_todo,
                "fail_count": fail_count,
                "sample_count": len(samples),
                "rank_sample_count": len(ranks),
                "slots": slots,
            }
        )
        stats = platform_stats.setdefault(
            plat,
            {"id": plat, "name": platform_names.get(plat) or plat, "todo": 0, "fail": 0, "avg_ranks": []},
        )
        if has_todo:
            stats["todo"] += 1
        stats["fail"] += fail_count
        if avg is not None:
            stats["avg_ranks"].append(float(avg))

    source_filter = str(source or "").strip()
    # 2026-08-03 - 到期漏跑日无子任务 - 单企业矩阵补期望调度缺口格
    if tenant_id is not None and source_filter != "lead_diagnosis":
        _merge_gap_cells_into_matrix(
            db,
            tenant_id=int(tenant_id),
            d0=d0,
            d1=d1,
            dates=dates,
            cells=cells,
            word_order=word_order,
            word_seen=word_seen,
            platform_order=platform_order,
            platform_seen=platform_seen,
            platform_code=str(platform or "").strip(),
            keyword_text=str(keyword or "").strip(),
            keyword_group_filter=str(keyword_group or "").strip(),
            purchased_exact=purchased_exact,
        )
        platform_stats = {
            code: {"id": code, "name": platform_names.get(code) or code, "todo": 0, "fail": 0, "avg_ranks": []}
            for code in platform_order
        }
        for cell in cells:
            plat = str(cell.get("platform") or "")
            stats = platform_stats.setdefault(
                plat,
                {"id": plat, "name": platform_names.get(plat) or plat, "todo": 0, "fail": 0, "avg_ranks": []},
            )
            if cell.get("has_todo"):
                stats["todo"] += 1
            stats["fail"] += int(cell.get("fail_count") or 0)
            rank = cell.get("rank")
            if rank is not None:
                try:
                    stats["avg_ranks"].append(float(rank))
                except (TypeError, ValueError):
                    pass

    platforms_out: list[dict[str, Any]] = []
    for code in platform_order:
        stats = platform_stats[code]
        avg_ranks = stats.pop("avg_ranks", [])
        platforms_out.append(
            {
                "id": code,
                "name": stats["name"],
                "todo": int(stats["todo"]),
                "fail": int(stats["fail"]),
                "avg": _average_mention_position(avg_ranks),
            }
        )

    return {
        "date_from": d0.isoformat(),
        "date_to": d1.isoformat(),
        "dates": dates,
        "words": word_order,
        "platforms": platforms_out,
        "cells": cells,
        "summary": {
            "todo_cells": sum(1 for cell in cells if cell.get("has_todo")),
            "fail_slots": sum(int(cell.get("fail_count") or 0) for cell in cells),
            "item_total": len(items),
            "scan_capped": bool((payload.get("summary") or {}).get("scan_capped")),
            "gap_cells": sum(1 for cell in cells if int(cell.get("gap_count") or 0) > 0),
        },
    }


def _schedule_day_eligible(asset: BrandAsset, day: date) -> bool:
    """按企业调度配置判断该自然日是否应有监测。"""
    if asset.schedule_type == "weekly":
        return day.isoweekday() in (asset.schedule_weekdays_json or [])
    if asset.schedule_type == "monthly":
        return day.day in (asset.schedule_month_days_json or [])
    return True


def _gap_slot_window_key(day: date, slot: time) -> tuple[str, str]:
    window_key = f"{day.strftime('%Y%m%d')}-{slot.hour:02d}{slot.minute:02d}"
    label = f"{day.isoformat()} {slot.hour:02d}:{slot.minute:02d}"
    return window_key, label


def _schedule_slot_eligible_for_gap(
    day: date,
    slot_time: time,
    *,
    now: datetime | None = None,
) -> bool:
    """缺口补录：历史日可出；当天须过调度点+容差窗后仍无子任务才标漏跑。"""
    now = now or datetime.now()
    if day > now.date():
        return False
    if day < now.date():
        return True
    # 2026-08-03 - 当天未到调度时刻不展示缺口 - 按 slot 时刻判，不用容差窗
    # 2026-08-05 - 过早标漏跑 - 对齐 schedule_tolerance 后再出缺口（已弃用「时刻一到即漏」）
    grace = max(0, int(settings.schedule_tolerance_minutes or 0))
    return now >= datetime.combine(day, slot_time) + timedelta(minutes=grace)


def _schedule_window_key_eligible_for_gap(
    window_key: str,
    *,
    now: datetime | None = None,
) -> bool:
    text = str(window_key or "").strip()
    if len(text) < 13 or text[8] != "-":
        return False
    day_part, hm = text[:8], text[9:13]
    try:
        day = datetime.strptime(day_part, "%Y%m%d").date()
        slot_time = time(hour=int(hm[0:2]), minute=int(hm[2:4]))
    except ValueError:
        return False
    return _schedule_slot_eligible_for_gap(day, slot_time, now=now)

def _tenant_matrix_word_platforms(
    db: Session,
    tenant_id: int,
    *,
    platform_code: str = "",
    keyword_text: str = "",
    keyword_group_filter: str = "",
    purchased_exact: set[str] | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    """(prompt, platform, keyword_group_dict) 期望矩阵行。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return []
    groups = active_keyword_groups(db, tenant_id)
    group_filter = str(keyword_group_filter or "").strip()
    selected_group = (
        _resolve_keyword_group_filter(group_filter, groups) if group_filter else None
    )
    purchased = purchased_exact if purchased_exact is not None else set(tenant_purchased_platforms(db, tenant_id))
    platform_filter = str(platform_code or "").strip()
    keyword_filter = str(keyword_text or "").strip().lower()
    rows: list[tuple[str, str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    iter_groups = [selected_group] if selected_group is not None else groups
    for group in iter_groups:
        if group is None:
            continue
        for prompt in keyword_group_monitor_keywords(group):
            if keyword_filter and keyword_filter not in prompt.lower():
                continue
            if group_filter and selected_group is None:
                label = keyword_group_display_label(group)
                if group_filter.lower() not in label.lower() and group_filter.lower() not in prompt.lower():
                    continue
            for plat in keyword_group_platforms(group, asset):
                if purchased and plat not in purchased:
                    continue
                if platform_filter and plat != platform_filter:
                    continue
                key = (prompt, plat)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((prompt, plat, group))
    return rows


def _build_gap_slot_payload(
    *,
    tenant_id: int,
    tenant_name: str | None,
    platform: str,
    prompt: str,
    day: date,
    slot: time,
) -> dict[str, Any]:
    window_key, label = _gap_slot_window_key(day, slot)
    return {
        "subtask_id": None,
        "task_id": None,
        "schedule_label": label,
        "schedule_window_key": window_key,
        "mention_position": None,
        "needs_backfill": True,
        "backfill_dismissed": False,
        "has_answer": False,
        "status": "missing",
        "error_message": "到期漏跑/无自动监测，待快照补录",
        "prompt": prompt,
        "platform": platform,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "brand_name": None,
        "source": "tenant_monitor",
        "monitor_keywords": prompt,
        "keyword_group": None,
        "updated_at": None,
        "is_gap": True,
    }


def _merge_gap_cells_into_matrix(
    db: Session,
    *,
    tenant_id: int,
    d0: date,
    d1: date,
    dates: list[str],
    cells: list[dict[str, Any]],
    word_order: list[str],
    word_seen: set[str],
    platform_order: list[str],
    platform_seen: set[str],
    platform_code: str = "",
    keyword_text: str = "",
    keyword_group_filter: str = "",
    purchased_exact: set[str] | None = None,
) -> None:
    """单企业矩阵：为调度日无子任务的词×平台×日补缺口槽位（含到期漏跑日）。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return
    tenant = db.get(Tenant, tenant_id)
    tenant_name = tenant.name if tenant else None
    today = date.today()
    now = datetime.now()
    service_start = tenant.service_start_date if tenant else None
    schedule_times = schedule_times_for_asset(asset)
    if not schedule_times:
        return

    expectations = _tenant_matrix_word_platforms(
        db,
        tenant_id,
        platform_code=platform_code,
        keyword_text=keyword_text,
        keyword_group_filter=keyword_group_filter,
        purchased_exact=purchased_exact,
    )
    if not expectations:
        return

    dismissed_gap_keys = _load_dismissed_gap_matrix_keys(db, tenant_id=int(tenant_id), d0=d0, d1=d1)

    cell_index: dict[tuple[str, str, str], dict[str, Any]] = {
        (str(cell.get("platform") or ""), str(cell.get("word") or ""), str(cell.get("date") or "")): cell
        for cell in cells
    }
    occupied_slots: set[tuple[str, str, str, str]] = set()
    for cell in cells:
        plat = str(cell.get("platform") or "")
        word = str(cell.get("word") or "")
        day = str(cell.get("date") or "")
        for slot in cell.get("slots") or []:
            window_key = str(slot.get("schedule_window_key") or "").strip()
            if not window_key:
                window_key = parse_schedule_slot(
                    slot.get("schedule_window_key"),
                    slot.get("schedule_label"),
                )[0]
            occupied_slots.add((plat, word, day, window_key))

    cursor = d0
    while cursor <= d1:
        if cursor > today:
            cursor += timedelta(days=1)
            continue
        if service_start and cursor < service_start:
            cursor += timedelta(days=1)
            continue
        if not _schedule_day_eligible(asset, cursor):
            cursor += timedelta(days=1)
            continue
        day_text = cursor.isoformat()
        for prompt, plat, _group in expectations:
            gap_slots: list[dict[str, Any]] = []
            for slot_time in schedule_times:
                # 2026-08-03 - 未到调度点不展示缺口 - 避免当天未跑场次误进补录
                if not _schedule_slot_eligible_for_gap(cursor, slot_time, now=now):
                    continue
                window_key, _label = _gap_slot_window_key(cursor, slot_time)
                if (plat, prompt, day_text, window_key) in occupied_slots:
                    continue
                if (plat, prompt, day_text, window_key) in dismissed_gap_keys:
                    continue
                gap_slots.append(
                    _build_gap_slot_payload(
                        tenant_id=tenant_id,
                        tenant_name=tenant_name,
                        platform=plat,
                        prompt=prompt,
                        day=cursor,
                        slot=slot_time,
                    )
                )
            if not gap_slots:
                continue
            cell_key = (plat, prompt, day_text)
            existing = cell_index.get(cell_key)
            if existing is None:
                if plat not in platform_seen:
                    platform_seen.add(plat)
                    platform_order.append(plat)
                if prompt not in word_seen:
                    word_seen.add(prompt)
                    word_order.append(prompt)
                existing = {
                    "platform": plat,
                    "word": prompt,
                    "date": day_text,
                    "rank": None,
                    "has_todo": True,
                    "fail_count": len(gap_slots),
                    "sample_count": 0,
                    "rank_sample_count": 0,
                    "gap_count": len(gap_slots),
                    "slots": gap_slots,
                }
                cells.append(existing)
                cell_index[cell_key] = existing
            else:
                merged_slots = list(existing.get("slots") or []) + gap_slots
                gap_count = sum(
                    1 for slot in merged_slots if slot.get("is_gap") and not slot.get("backfill_dismissed")
                )
                active_samples = [slot for slot in merged_slots if not slot.get("backfill_dismissed") and not slot.get("is_gap")]
                active_ranks: list[float] = []
                for sample in active_samples:
                    rank = sample.get("mention_position")
                    try:
                        if rank is not None:
                            active_ranks.append(float(rank))
                    except (TypeError, ValueError):
                        pass
                fail_count = sum(
                    1
                    for slot in merged_slots
                    if slot.get("needs_backfill") and not slot.get("has_answer") and not slot.get("is_gap")
                ) + gap_count
                existing.update(
                    {
                        "slots": merged_slots,
                        "gap_count": gap_count,
                        "fail_count": fail_count,
                        "has_todo": matrix_cell_has_todo(
                            ranks=active_ranks,
                            sample_count=len(active_samples),
                            gap_count=gap_count,
                        ),
                    }
                )
        cursor += timedelta(days=1)


def _keyword_group_suffix(group: dict[str, Any]) -> str:
    return str(group.get("id") or group.get("sort_order", 0))


def _resolve_group_for_prompt(
    groups: list[dict[str, Any]],
    prompt: str,
) -> dict[str, Any] | None:
    text = str(prompt or "").strip()
    if not text:
        return None
    for group in groups:
        if text in keyword_group_monitor_keywords(group):
            return group
        if _prompt_belongs_to_group(
            text,
            keyword_group_monitor_keywords(group),
            group.get("exposure_terms") or [],
        ):
            return group
    return groups[0] if groups else None


def _new_gap_backfill_id(prefix: str = "bf") -> str:
    return f"{prefix}{uuid4().hex[:14]}"


def ensure_gap_backfill_subtask(
    db: Session,
    *,
    tenant_id: int,
    platform: str,
    prompt: str,
    schedule_window_key: str,
    current: CurrentSession,
    auto_commit: bool = True,
) -> GeoMonitorSubtask:
    """到期/漏跑日无子任务时，落本地占位 task+subtask+schedule_run 供快照补录。"""
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可执行快照补录")

    from app.services.monitor_service import ensure_sales_tenant_access

    ensure_sales_tenant_access(db, current, tenant_id)

    plat = str(platform or "").strip()
    prompt_text = str(prompt or "").strip()
    window_key = str(schedule_window_key or "").strip()
    if not plat or not prompt_text or not window_key:
        raise ValueError("platform、prompt、schedule_window_key 不能为空")
    if len(window_key) < 13 or window_key[8] != "-":
        raise ValueError("schedule_window_key 格式无效")
    if not _schedule_window_key_eligible_for_gap(window_key):
        raise ValueError("该调度场次尚未到点，暂不可补录")

    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise ValueError("企业品牌资产不存在")
    groups = active_keyword_groups(db, tenant_id)
    group = _resolve_group_for_prompt(groups, prompt_text)
    if group is None:
        raise ValueError("未找到对应监测词组")

    group_key: str | None = None
    existing_run: GeoMonitorScheduleRun | None = None
    region_code: str | None = None
    for code in region_submission_targets(asset.region_codes_json):
        region_suffix = f"-rg{code}" if code else ""
        candidate_key = f"{window_key}-kw{_keyword_group_suffix(group)}{region_suffix}"
        run = db.scalar(
            select(GeoMonitorScheduleRun).where(
                GeoMonitorScheduleRun.tenant_id == tenant_id,
                GeoMonitorScheduleRun.schedule_key == candidate_key,
            )
        )
        if run and run.task_id:
            task = db.scalar(
                select(GeoMonitorTask).where(
                    GeoMonitorTask.task_id == run.task_id,
                    GeoMonitorTask.deleted.is_(False),
                )
            )
            if task is not None:
                for subtask in task.subtasks or []:
                    if subtask.platform == plat and (subtask.prompt or "").strip() == prompt_text:
                        return subtask
        if group_key is None:
            group_key = candidate_key
            existing_run = run
            region_code = code
    if group_key is None:
        raise ValueError("无法构建调度键")

    day_part, hm_part = window_key[:8], window_key[9:13]
    try:
        slot_dt = datetime.strptime(f"{day_part}{hm_part}", "%Y%m%d%H%M")
    except ValueError as exc:
        raise ValueError("schedule_window_key 无法解析为检测时刻") from exc

    monitor_keywords = keyword_group_primary_keyword(group) or prompt_text

    def _gap_placeholder_subtask(task_id: str) -> GeoMonitorSubtask:
        return GeoMonitorSubtask(
            subtask_id=_new_gap_backfill_id("bfs"),
            task_id=task_id,
            platform=plat,
            mode=FAST_MONITOR_MODE,
            prompt=prompt_text,
            status="failed",
            error_message="到期漏跑/无自动监测，待快照补录",
            # 2026-08-04 - 缺口占位未标重试闭环 - needs_backfill 为假，忽略后矩阵丢格又冒缺口
            auto_retry_count=1,
            auto_retry_status="failed",
            raw_result_json={"source": "gap_backfill", "schedule_window_key": window_key},
            updated_at=slot_dt,
        )

    def _merge_platform_into_task(task: GeoMonitorTask) -> None:
        platforms = list(task.platforms_json or [])
        if not any(
            isinstance(item, dict) and str(item.get("platform") or "").strip() == plat
            for item in platforms
        ):
            platforms.append({"platform": plat, "mode": FAST_MONITOR_MODE, "screenshot": 1})
            task.platforms_json = platforms
        prompts = [str(item).strip() for item in (task.prompts_json or []) if str(item).strip()]
        if prompt_text not in prompts:
            prompts.append(prompt_text)
            task.prompts_json = prompts
        task.total_items = int(task.total_items or 0) + 1
        task.failed_items = int(task.failed_items or 0) + 1
        if task.status == "completed":
            task.status = "partial_completed"
        task.updated_at = slot_dt

    # 2026-08-11 - 同 schedule_key 多平台缺口曾各建 bft 并覆盖 task_id，矩阵只见一端 - 已有 task 则追加 subtask
    if existing_run and existing_run.task_id:
        anchor_task = db.scalar(
            select(GeoMonitorTask).where(
                GeoMonitorTask.task_id == existing_run.task_id,
                GeoMonitorTask.deleted.is_(False),
            )
        )
        if anchor_task is not None:
            for owned in anchor_task.subtasks or []:
                if owned.platform == plat and (owned.prompt or "").strip() == prompt_text:
                    return owned
            subtask = _gap_placeholder_subtask(anchor_task.task_id)
            db.add(subtask)
            _merge_platform_into_task(anchor_task)
            existing_run.status = "submitted"
            existing_run.error_message = None
            existing_run.prompt_count = max(int(existing_run.prompt_count or 0), len(anchor_task.prompts_json or []) or 1)
            plat_n = len(
                {
                    str(item.get("platform") or "").strip()
                    for item in (anchor_task.platforms_json or [])
                    if isinstance(item, dict) and str(item.get("platform") or "").strip()
                }
            )
            existing_run.platform_count = max(int(existing_run.platform_count or 0), plat_n or 1)
            existing_run.updated_at = slot_dt
            db.flush()
            if auto_commit:
                db.commit()
                db.refresh(subtask)
                _bust_snapshot_backfill_matrix_cache()
            return subtask

    task_id = _new_gap_backfill_id("bft")
    subtask = _gap_placeholder_subtask(task_id)
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=tenant_id,
        created_by=current.user.id,
        monitor_keywords=monitor_keywords,
        status="failed",
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=[prompt_text],
        platforms_json=[{"platform": plat, "mode": FAST_MONITOR_MODE, "screenshot": 1}],
        region_code_json=[region_code] if region_code else None,
        purpose="geo",
        raw_request_json={"source": "gap_backfill", "schedule_window_key": window_key},
        raw_response_json={"source": "gap_backfill"},
        created_at=slot_dt,
        updated_at=slot_dt,
    )
    task.subtasks = [subtask]
    db.add(task)

    if existing_run is None:
        db.add(
            GeoMonitorScheduleRun(
                tenant_id=tenant_id,
                schedule_key=group_key,
                task_id=task_id,
                status="submitted",
                prompt_count=1,
                platform_count=1,
                created_by=current.user.id,
                created_at=slot_dt,
                updated_at=slot_dt,
            )
        )
    else:
        # 仅在无有效 task 时写入指针；禁止用单平台新 task 覆盖已有挂靠
        existing_run.task_id = task_id
        existing_run.status = "submitted"
        existing_run.error_message = None
        existing_run.prompt_count = max(existing_run.prompt_count or 0, 1)
        existing_run.platform_count = max(existing_run.platform_count or 0, 1)
        existing_run.updated_at = slot_dt

    db.flush()
    if auto_commit:
        db.commit()
        db.refresh(subtask)
        _bust_snapshot_backfill_matrix_cache()
    return subtask


def list_snapshot_backfill_items(
    db: Session,
    *,
    tenant_id: int | None = None,
    detect_date: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
    pending_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """运营端快照补录列表（仅条目，兼容旧调用）。"""
    return list_snapshot_backfill_page(
        db,
        tenant_id=tenant_id,
        detect_date=detect_date,
        source=source,
        platform=platform,
        keyword=keyword,
        keyword_group=keyword_group,
        pending_only=pending_only,
        limit=limit,
    )["items"]


def list_pending_snapshot_backfills(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    """运营端待补录列表：仅失败或无回答的子任务。"""
    return list_snapshot_backfill_items(db, pending_only=True, limit=limit)
