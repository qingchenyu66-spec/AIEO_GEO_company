"""Failed monitor subtask auto-retry (once), then snapshot backfill.

模力无同 task 内重跑接口：按失败平台×问题再 submit 迷你任务，成功回写原格子。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.monitor_purpose import normalize_task_purpose
from app.core.region_catalog import normalize_region_codes
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.monitor import PlatformConfig
from app.services.molizhishu_client import MolizhishuApiError, MolizhishuClient
from app.services.molizhishu_platforms import filter_submittable_platforms

logger = logging.getLogger(__name__)

GEO_AUTO_RETRY_META = "_geo_auto_retry"
AUTO_RETRY_MAX = 1
TERMINAL_STATUSES = frozenset({"completed", "partial_completed", "failed", "stopped"})


def is_auto_retry_task(task: GeoMonitorTask) -> bool:
    raw = task.raw_request_json if isinstance(task.raw_request_json, dict) else {}
    return isinstance(raw.get(GEO_AUTO_RETRY_META), dict)


def subtask_hard_failed(subtask: GeoMonitorSubtask) -> bool:
    if (subtask.answer_content or "").strip():
        return False
    return subtask.status in {"failed", "stopped"} or bool(subtask.error_message and subtask.status in TERMINAL_STATUSES)


def subtask_failure_awaits_or_in_auto_retry(subtask: GeoMonitorSubtask) -> bool:
    """失败格尚未完成「自动重试 1 次」闭环时，不进补录。"""
    if not subtask_hard_failed(subtask):
        return False
    status = (subtask.auto_retry_status or "").strip().lower()
    if status == "succeeded":
        return False
    if status == "failed":
        return False
    if status == "pending":
        return True
    # 尚未发起：同步流程里会立刻发起；补录侧先挡住，避免抢跑
    return (subtask.auto_retry_count or 0) < AUTO_RETRY_MAX


def _platform_payload(task: GeoMonitorTask, platform: str) -> dict[str, Any]:
    from app.schemas.monitor import FAST_MONITOR_MODE

    for item in task.platforms_json or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("platform") or "") == platform:
            try:
                return PlatformConfig(
                    platform=platform,
                    mode=FAST_MONITOR_MODE,
                    screenshot=item.get("screenshot") if item.get("screenshot") is not None else 1,
                ).model_dump()
            except Exception:
                break
    return PlatformConfig(platform=platform, mode=FAST_MONITOR_MODE).model_dump()


def _strip_geo_meta(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if not str(k).startswith("_geo")}


def _enqueue_sync(task_id: str) -> None:
    try:
        from app.tasks.monitor import sync_one_monitor_task

        sync_one_monitor_task.apply_async(kwargs={"task_id": task_id}, task_id=f"sync-{task_id}")
    except Exception as exc:
        logger.warning("enqueue auto-retry sync failed task_id=%s error=%s", task_id, exc)


def _copy_result_onto_origin(origin: GeoMonitorSubtask, source: GeoMonitorSubtask) -> None:
    origin.status = "completed"
    origin.error_message = None
    origin.answer_content = source.answer_content
    origin.page_screenshot = source.page_screenshot
    origin.reference_list_json = source.reference_list_json
    origin.citation_list_json = source.citation_list_json
    origin.reasoning_process_json = source.reasoning_process_json
    origin.recommended_questions_json = source.recommended_questions_json
    origin.media_content_json = source.media_content_json
    origin.proxy_ip = source.proxy_ip
    origin.amount = source.amount
    origin.mention_position = source.mention_position
    origin.mention_context = source.mention_context
    origin.sentiment = source.sentiment
    origin.competitor_rankings_json = source.competitor_rankings_json
    origin.all_rankings_json = source.all_rankings_json
    origin.remote_time = source.remote_time
    if isinstance(source.raw_result_json, dict):
        origin.raw_result_json = dict(source.raw_result_json)


def launch_auto_retries_for_task(db: Session, task: GeoMonitorTask) -> list[str]:
    """对尚未重试过的失败子任务按平台打包再提交；返回新建 retry task_id 列表。"""
    if is_auto_retry_task(task):
        return []

    candidates = [
        item
        for item in (task.subtasks or [])
        if subtask_hard_failed(item) and (item.auto_retry_count or 0) < AUTO_RETRY_MAX
    ]
    if not candidates:
        return []

    by_platform: dict[str, list[GeoMonitorSubtask]] = defaultdict(list)
    for item in candidates:
        code = str(item.platform or "").strip()
        if code:
            by_platform[code].append(item)

    created: list[str] = []
    client = MolizhishuClient()
    for platform, items in by_platform.items():
        if platform not in filter_submittable_platforms([platform]):
            for item in items:
                item.auto_retry_count = AUTO_RETRY_MAX
                item.auto_retry_status = "failed"
            continue

        prompts: list[str] = []
        seen_prompts: set[str] = set()
        for item in items:
            text = str(item.prompt or "").strip()
            if text and text not in seen_prompts:
                seen_prompts.add(text)
                prompts.append(text)
        if not prompts:
            continue

        platform_payload = _platform_payload(task, platform)
        request_body: dict[str, Any] = {
            "prompts": prompts,
            "platforms": [platform_payload],
        }
        origin_req = task.raw_request_json if isinstance(task.raw_request_json, dict) else {}
        for key in ("monitorKeywords", "monitorKeywordAliases", "competitors", "regionCode", "callbackUrl"):
            if origin_req.get(key) is not None:
                request_body[key] = origin_req[key]
        if task.region_code_json and "regionCode" not in request_body:
            codes = normalize_region_codes(task.region_code_json)
            if codes:
                request_body["regionCode"] = codes[0]

        meta = {
            "of_task_id": task.task_id,
            "pairs": [
                {"subtask_id": item.subtask_id, "platform": item.platform, "prompt": item.prompt}
                for item in items
            ],
        }
        stored_request = {**request_body, GEO_AUTO_RETRY_META: meta}

        try:
            response = client.submit_task(_strip_geo_meta(request_body))
        except (MolizhishuApiError, ValueError, OSError) as exc:
            logger.warning(
                "auto-retry submit failed origin=%s platform=%s error=%s",
                task.task_id,
                platform,
                exc,
            )
            # 提交都失败则记 exhausted，避免永远卡在「等重试」进不了补录
            for item in items:
                item.auto_retry_count = AUTO_RETRY_MAX
                item.auto_retry_status = "failed"
            continue

        data = response.get("data") or {}
        retry_task_id = data.get("taskId")
        if not retry_task_id:
            logger.warning("auto-retry missing taskId origin=%s platform=%s", task.task_id, platform)
            continue

        existing = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == retry_task_id))
        if existing is not None:
            logger.warning("auto-retry task already exists task_id=%s", retry_task_id)
            continue

        from app.services.monitor_service import _upsert_subtask

        retry_task = GeoMonitorTask(
            task_id=retry_task_id,
            tenant_id=task.tenant_id,
            created_by=task.created_by,
            monitor_keywords=task.monitor_keywords,
            status=data.get("status") or "pending",
            total_items=data.get("totalTask") or data.get("totalItems") or 0,
            completed_items=data.get("completedItems") or 0,
            failed_items=data.get("failedItems") or 0,
            prompts_json=prompts,
            platforms_json=[platform_payload],
            region_code_json=task.region_code_json,
            purpose=normalize_task_purpose(getattr(task, "purpose", None)),
            callback_url=data.get("callbackUrl"),
            poll_url=data.get("pollUrl"),
            raw_request_json=stored_request,
            raw_response_json=response,
        )
        db.add(retry_task)
        for remote_sub in data.get("subTaskList") or []:
            _upsert_subtask(db, retry_task_id, remote_sub)

        for item in items:
            item.auto_retry_count = AUTO_RETRY_MAX
            item.auto_retry_task_id = retry_task_id
            item.auto_retry_status = "pending"

        db.flush()
        created.append(retry_task_id)
        _enqueue_sync(retry_task_id)
        logger.info(
            "auto-retry launched origin=%s retry=%s platform=%s prompts=%s",
            task.task_id,
            retry_task_id,
            platform,
            len(prompts),
        )
    return created


def apply_auto_retry_results(db: Session, retry_task: GeoMonitorTask) -> list[str]:
    """重试任务同步后：成功回写原格子，失败标记 exhausted。返回受影响的 origin task_id。"""
    if not is_auto_retry_task(retry_task):
        return []

    raw = retry_task.raw_request_json if isinstance(retry_task.raw_request_json, dict) else {}
    meta = raw.get(GEO_AUTO_RETRY_META) or {}
    pairs = meta.get("pairs") or []
    if not pairs:
        return []

    by_key = {
        (str(p.get("platform") or ""), str(p.get("prompt") or "")): str(p.get("subtask_id") or "")
        for p in pairs
        if p.get("subtask_id")
    }
    touched_origins: set[str] = set()
    retry_subs = list(
        db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == retry_task.task_id))
    )
    if not retry_subs:
        return []

    for source in retry_subs:
        origin_id = by_key.get((str(source.platform or ""), str(source.prompt or "")))
        if not origin_id:
            continue
        origin = db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == origin_id))
        if origin is None:
            continue
        touched_origins.add(origin.task_id)
        has_answer = bool((source.answer_content or "").strip())
        if has_answer and source.status in {"completed", "partial_completed"}:
            _copy_result_onto_origin(origin, source)
            origin.auto_retry_status = "succeeded"
            continue
        if source.status in {"failed", "stopped"} or (source.error_message and not has_answer and source.status in TERMINAL_STATUSES):
            origin.auto_retry_status = "failed"
            continue
        # 仍在跑：保持 pending
        if origin.auto_retry_status != "succeeded":
            origin.auto_retry_status = "pending"

    # 若整单已终态且仍有 origin 停在 pending，一律记失败（避免永远不进补录）
    if retry_task.status in TERMINAL_STATUSES:
        for origin_id in {str(p.get("subtask_id") or "") for p in pairs if p.get("subtask_id")}:
            origin = db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == origin_id))
            if origin is None:
                continue
            if origin.auto_retry_status == "pending" and subtask_hard_failed(origin):
                origin.auto_retry_status = "failed"
                touched_origins.add(origin.task_id)

    from app.services.monitor_service import _reconcile_task_progress
    from app.services.snapshot_backfill_service import notify_failed_subtasks_for_task

    for origin_task_id in touched_origins:
        origin_task = db.scalar(
            select(GeoMonitorTask).where(GeoMonitorTask.task_id == origin_task_id, GeoMonitorTask.deleted.is_(False))
        )
        if origin_task is None:
            continue
        origin_task.subtasks = list(
            db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == origin_task_id))
        )
        _reconcile_task_progress(origin_task)
        notify_failed_subtasks_for_task(db, origin_task)

    return list(touched_origins)
