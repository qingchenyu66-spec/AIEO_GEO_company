from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kombu.exceptions import OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session, require_platform
from app.api.http_errors import molizhishu_upstream_error_detail, raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.core.read_cache import (
    MANAGEMENT_OVERVIEW_CACHE_KEY,
    MANAGEMENT_OVERVIEW_CACHE_TTL,
    MONITOR_SUMMARY_CACHE_TTL,
    RANKING_MATRIX_CACHE_TTL,
    WORKSPACE_BRIEF_CACHE_TTL,
    get_or_build_json_cache,
    monitor_summary_cache_key,
    ranking_matrix_cache_key,
    workspace_brief_cache_key,
)
from app.schemas.common import ApiResponse
from app.schemas.monitor import (
    MonitorTaskCreateRequest,
    SnapshotBackfillListResponse,
    SnapshotBackfillRequest,
)
from app.services.monitor_service import (
    filter_subtasks_for_customer,
    get_monitor_subtask,
    get_monitor_task,
    list_monitor_tasks,
    monitor_summary,
    ranking_matrix,
    workspace_brief,
    list_inclusion_snapshots,
    serialize_subtask_for_display,
    serialize_task,
    serialize_tasks_for_display,
    submit_monitor_task,
    sync_monitor_task,
)
from app.services.molizhishu_callback_service import ingest_molizhishu_callback, verify_callback_token
from app.services.snapshot_backfill_service import (
    apply_snapshot_backfill,
    build_snapshot_backfill_item,
    dismiss_snapshot_backfill,
    list_snapshot_backfill_page,
    undismiss_snapshot_backfill,
)
from app.services.brand_service import get_brand_asset, keyword_group_to_dict, list_keyword_groups
from app.services.molizhishu_client import MolizhishuApiError
from app.services.menu_permission_service import (
    has_identity_menu_permission,
    require_platform_menu_permission,
    require_snapshot_backfill_permission,
)
from app.services.tenant_scope import (
    ensure_sales_tenant_access,
    sales_owned_lead_diagnosis_task_ids,
    sales_owned_tenant_ids,
)
from app.services.schedule_context import schedule_plan_summary, schedule_runs_for_tasks
from app.services.schedule_service import preview_scheduled_tasks, run_due_scheduled_tasks

router = APIRouter(prefix="/monitor")


@router.post("/molizhishu/callback", response_model=ApiResponse[dict])
async def molizhishu_callback(
    request: Request,
    token: str | None = Query(default=None, description="回调鉴权 token"),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """模力指数 Webhook：无 JWT，靠 query token；幂等写入子任务结果。"""
    if not verify_callback_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="回调鉴权失败")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="回调体不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="回调体必须是 JSON 对象")

    task_id = str(payload.get("taskId") or "").strip()
    from app.core.redis_client import redis_lock

    # 与手动/Celery sync 共用锁，避免并发写花子任务
    lock_key = f"sync-task:{task_id}" if task_id else "sync-task:unknown-callback"
    with redis_lock(lock_key, ttl_seconds=600) as acquired:
        if not acquired:
            # 返回 409 会触发模力退避重试，合理
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务正在同步中，请稍后重试")
        try:
            result = ingest_molizhishu_callback(db, payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"回调处理失败：{exc}",
            ) from exc
    return ApiResponse(data=result)


def _keyword_groups_for_tenant(db: Session, tenant_id: int | None) -> list[dict]:
    if tenant_id is None:
        return []
    return [
        keyword_group_to_dict(item)
        for item in list_keyword_groups(db, tenant_id)
        if item.status and item.monitor_keyword
    ]


def _serialize_task_subtasks(db: Session, task, current: CurrentSession | None = None) -> list[dict]:
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = _keyword_groups_for_tenant(db, task.tenant_id)
    subtasks = task.subtasks
    if current and current.identity.identity_type == "CUSTOMER":
        subtasks = filter_subtasks_for_customer(subtasks, task=task, db=db)
    return [
        serialize_subtask_for_display(
            item,
            monitor_keywords=task.monitor_keywords,
            asset=asset,
            keyword_groups=groups,
        )
        for item in subtasks
    ]


_MONITOR_PLATFORM_DETAIL = "仅平台运营端可以执行定时监测任务"


@router.post("/tasks", response_model=ApiResponse[dict])
def create_monitor_task(
    payload: MonitorTaskCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """提交模力指数检测任务，并把任务摘要保存到本地库。"""
    require_platform(current, detail="仅平台运营端可以提交 GEO 检测任务")
    if not (
        has_identity_menu_permission(db, current.identity.id, "platform.lead_diagnosis", "can_create")
        or has_identity_menu_permission(db, current.identity.id, "platform.audit.schedule", "can_update")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权提交 GEO 检测任务")
    try:
        task = submit_monitor_task(db, payload, current)
    except MolizhishuApiError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=molizhishu_upstream_error_detail(exc),
        ) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="monitor.create_task")
    return ApiResponse(data=serialize_task(task))


@router.get("/tasks", response_model=ApiResponse[list[dict]])
def monitor_tasks(
    tenant_id: int | None = Query(default=None, description="平台端客户预览时指定企业"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """查询本地任务列表；这里不请求模力指数远端接口。"""
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    scoped_tenant_id: int | None = None
    if current.identity.identity_type == "PLATFORM" and tenant_id is not None:
        try:
            scoped_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    tasks = list_monitor_tasks(db, current, tenant_id=scoped_tenant_id)
    return ApiResponse(data=serialize_tasks_for_display(db, tasks))


@router.get("/summary", response_model=ApiResponse[dict])
def monitor_dashboard_summary(
    tenant_id: int | None = Query(default=None, description="平台端客户预览时指定企业"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Read aggregated real monitoring data for customer and platform dashboards."""
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    scoped_tenant_id: int | None = None
    if current.identity.identity_type == "PLATFORM" and tenant_id is not None:
        try:
            scoped_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    tenant_key = scoped_tenant_id or current.identity.tenant_id or "platform"
    identity_key = "CUSTOMER" if scoped_tenant_id is not None else current.identity.identity_type
    cache_key = monitor_summary_cache_key(identity_key, tenant_key)
    try:
        data = get_or_build_json_cache(
            cache_key,
            lambda: monitor_summary(db, current, tenant_id=scoped_tenant_id),
            ttl_seconds=MONITOR_SUMMARY_CACHE_TTL,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.summary")


@router.get("/ranking-matrix", response_model=ApiResponse[dict])
def monitor_ranking_matrix(
    platform: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    keyword: str | None = None,
    monitor_group: str | None = None,
    keyword_group: str | None = None,
    monitor_keyword: str | None = None,
    exposure_term: str | None = None,
    limit_rows: int = 120,
    tenant_id: int | None = Query(default=None, description="平台端客户预览时指定企业"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Return prompt × snapshot ranking matrix for customer realtime monitor."""
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    scoped_tenant_id: int | None = None
    if current.identity.identity_type == "PLATFORM" and tenant_id is not None:
        try:
            scoped_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    start_at = datetime.combine(start_date, time.min) if start_date else None
    end_at = datetime.combine(end_date, time.max) if end_date else None
    try:
        cache_tenant = (
            scoped_tenant_id
            if scoped_tenant_id is not None
            else (current.identity.tenant_id if current.identity.identity_type == "CUSTOMER" else None)
        )
        if cache_tenant is None:
            data = ranking_matrix(
                db,
                current,
                platform=platform,
                start_at=start_at,
                end_at=end_at,
                keyword=keyword,
                monitor_group=monitor_group,
                keyword_group=keyword_group,
                monitor_keyword=monitor_keyword,
                exposure_term=exposure_term,
                limit_rows=limit_rows,
                tenant_id=scoped_tenant_id,
            )
        else:
            cache_key = ranking_matrix_cache_key(
                current.identity.identity_type,
                int(cache_tenant),
                platform=platform,
                start_date=start_date.isoformat() if start_date else None,
                end_date=end_date.isoformat() if end_date else None,
                keyword=keyword,
                monitor_group=monitor_group,
                keyword_group=keyword_group,
                monitor_keyword=monitor_keyword,
                exposure_term=exposure_term,
                limit_rows=limit_rows,
            )

            def _build() -> dict:
                return ranking_matrix(
                    db,
                    current,
                    platform=platform,
                    start_at=start_at,
                    end_at=end_at,
                    keyword=keyword,
                    monitor_group=monitor_group,
                    keyword_group=keyword_group,
                    monitor_keyword=monitor_keyword,
                    exposure_term=exposure_term,
                    limit_rows=limit_rows,
                    tenant_id=scoped_tenant_id,
                )

            data = get_or_build_json_cache(
                cache_key,
                _build,
                ttl_seconds=RANKING_MATRIX_CACHE_TTL,
                lock_ttl_seconds=60,
                wait_seconds=2.0,
            )
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.ranking_matrix")
    return ApiResponse(data=data)


@router.get("/workspace-brief", response_model=ApiResponse[dict])
def monitor_workspace_brief(
    start_date: date | None = Query(default=None, description="趋势起始日（含），客户侧不晚于昨日"),
    end_date: date | None = Query(default=None, description="趋势截止日（含），客户侧不晚于昨日"),
    tenant_id: int | None = Query(default=None, description="平台端只读预览时指定企业"),
    record_access: bool = Query(default=False, description="平台预览首次进入时记一条审计"),
    scope: str = Query(default="full", pattern="^(full|summary)$", description="summary=仅 KPI/趋势，切换周期用"),
    purpose: str = Query(default="geo", pattern="^(geo|brand_word)$", description="geo=日常监测；brand_word=品牌分析专用"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """客户工作台简报；平台端可带 tenant_id 只读预览（销售仅名下企业）。

    purpose=brand_word 仅供品牌分析页，与 GEO 监测数据隔离。
    """
    from app.services.operation_log_service import write_operation_log
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="起始日期不能晚于结束日期")

    resolved_tenant_id: int
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="运营工作台简报仅支持客户企业账号")
        resolved_tenant_id = current.identity.tenant_id
    elif current.identity.identity_type == "PLATFORM":
        try:
            resolved_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if record_access:
            write_operation_log(
                db,
                current,
                "预览客户工作台",
                f"只读预览企业工作台 tenant_id={resolved_tenant_id}",
                target_module="企业管理",
                target_id=resolved_tenant_id,
                tenant_id=resolved_tenant_id,
                risk_level="正常",
            )
            db.commit()
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问工作台简报")

    start_key = start_date.isoformat() if start_date else None
    end_key = end_date.isoformat() if end_date else None
    cache_key = workspace_brief_cache_key(resolved_tenant_id, start_key, end_key, scope, purpose)
    try:
        data = get_or_build_json_cache(
            cache_key,
            lambda: workspace_brief(
                db,
                current,
                start_date=start_date,
                end_date=end_date,
                tenant_id=resolved_tenant_id,
                scope=scope,
                purpose=purpose,
            ),
            ttl_seconds=WORKSPACE_BRIEF_CACHE_TTL,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.workspace_brief")


@router.get("/brand-analysis", response_model=ApiResponse[dict])
def monitor_brand_analysis(
    tenant_id: int | None = Query(default=None, description="平台端只读预览时指定企业"),
    parse: bool = Query(default=False, description="是否对未解析样本调用 DeepSeek；默认否，避免读路径堵接口"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """品牌分析专用看板：情感/平台饼图 + 分平台正中负回答（仅 brand_word 任务）。"""
    from app.services.brand_analysis_service import build_brand_analysis_dashboard
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    resolved_tenant_id: int | None = tenant_id
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持客户企业账号")
        resolved_tenant_id = current.identity.tenant_id
    elif current.identity.identity_type == "PLATFORM":
        try:
            resolved_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问品牌分析")

    try:
        data = build_brand_analysis_dashboard(
            db,
            current,
            tenant_id=resolved_tenant_id,
            parse_sentiments=parse,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.brand_analysis")


@router.get("/inclusion-snapshots", response_model=ApiResponse[dict])
def monitor_inclusion_snapshots(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    tenant_id: int | None = Query(default=None, description="平台端只读预览时指定企业"),
    platform: str | None = Query(default=None, description="平台 code；空或 all 表示全部已购平台"),
    limit: int = Query(default=48, ge=1, le=100),
    rank_scope: str = Query(default="ranked", description="ranked=有排名；all=全部（含未提及）"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """信源分析「收录明细」：按周期/平台取监测快照行（与引用次数口径不同）。"""
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="起始日期不能晚于结束日期")
    scope = str(rank_scope or "ranked").strip().lower()
    if scope not in {"ranked", "all"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rank_scope 仅支持 ranked 或 all")

    resolved_tenant_id: int | None = tenant_id
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持客户企业账号")
        resolved_tenant_id = current.identity.tenant_id
    elif current.identity.identity_type == "PLATFORM":
        try:
            resolved_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问收录明细")

    try:
        data = list_inclusion_snapshots(
            db,
            current,
            start_date=start_date,
            end_date=end_date,
            tenant_id=resolved_tenant_id,
            platform=platform,
            limit=limit,
            rank_scope=scope,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.inclusion_snapshots")


@router.get("/snapshot-backfill/pending", response_model=ApiResponse[SnapshotBackfillListResponse])
def monitor_snapshot_backfill_pending(
    tenant_id: int | None = None,
    all_tenants: bool = Query(
        default=False,
        description="为 true 时允许不传 tenant_id 查询全部企业（默认需指定企业以防误扫全库）",
    ),
    on_date: date | None = Query(default=None, alias="date"),
    source: str | None = Query(default=None, pattern="^(tenant_monitor|lead_diagnosis)$"),
    platform: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    keyword_group: str | None = Query(default=None),
    pending_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    include_summary: bool = Query(
        default=True,
        description="为 false 时缩小扫描窗口、尽快返回列表；汇总请再请求 include_summary=true",
    ),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[SnapshotBackfillListResponse]:
    """运营端快照补录列表：可按企业、单日、来源、平台、关键词/词组筛选；默认含已有结果以便覆盖更正。"""
    require_platform(current, detail=_MONITOR_PLATFORM_DETAIL)
    if tenant_id is None and not all_tenants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请指定 tenant_id，或显式传入 all_tenants=true 查询全部企业",
        )
    try:
        require_snapshot_backfill_permission(db, current, "can_export")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    owned = sales_owned_tenant_ids(db, current)
    scoped_tenant_ids: list[int] | None = None
    allowed_lead_task_ids: list[str] | None = None
    if owned is not None:
        allowed_lead_task_ids = sales_owned_lead_diagnosis_task_ids(db, current.user.id)
        if tenant_id is not None:
            try:
                ensure_sales_tenant_access(db, current, tenant_id)
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        elif all_tenants:
            if not owned and not allowed_lead_task_ids:
                return ApiResponse(data=SnapshotBackfillListResponse.model_validate({
                    "items": [], "summary": {"pending": 0, "total": 0}, "total": 0, "offset": offset, "limit": limit,
                }))
            scoped_tenant_ids = owned
            tenant_id = None
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定 tenant_id")

    cache_key = None
    if include_summary:
        from app.core.redis_client import get_json_cache, set_json_cache
        import hashlib

        raw = "|".join(
            [
                str(tenant_id or ""),
                ",".join(str(x) for x in (scoped_tenant_ids or [])),
                str(on_date or ""),
                str(source or ""),
                str(platform or ""),
                str(keyword or ""),
                str(keyword_group or ""),
                str(pending_only),
                str(offset),
                str(limit),
            ]
        )
        cache_key = f"snapshot_backfill:sum:{hashlib.sha1(raw.encode()).hexdigest()[:24]}"
        cached = get_json_cache(cache_key)
        if isinstance(cached, dict) and "items" in cached and "summary" in cached:
            return ApiResponse(data=SnapshotBackfillListResponse.model_validate(cached))

    payload = list_snapshot_backfill_page(
        db,
        tenant_id=tenant_id,
        tenant_ids=scoped_tenant_ids,
        allowed_lead_task_ids=allowed_lead_task_ids,
        detect_date=on_date,
        source=source,
        platform=platform,
        keyword=keyword,
        keyword_group=keyword_group,
        pending_only=pending_only,
        offset=offset,
        limit=limit,
        include_summary=include_summary,
    )
    if cache_key and include_summary:
        from app.core.redis_client import set_json_cache

        set_json_cache(cache_key, payload, ttl_seconds=45)
    return ApiResponse(data=SnapshotBackfillListResponse.model_validate(payload))


@router.post("/subtasks/{subtask_id}/snapshot-backfill", response_model=ApiResponse[dict])
def monitor_subtask_snapshot_backfill(
    subtask_id: str,
    payload: SnapshotBackfillRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """运营补录：有分享链接则解析覆盖；无链接时可只改排名（沿用原快照）。"""
    require_platform(current, detail=_MONITOR_PLATFORM_DETAIL)
    try:
        require_snapshot_backfill_permission(db, current, "can_update")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    try:
        data = apply_snapshot_backfill(
            db,
            subtask_id=subtask_id,
            snapshot_url=payload.snapshot_url,
            answer_content=payload.answer_content,
            current=current,
            mention_position=payload.mention_position,
            sentiment=payload.sentiment,
            reference_urls=payload.reference_urls,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="monitor.snapshot_backfill")
    return ApiResponse(data=data)


@router.post("/subtasks/{subtask_id}/snapshot-backfill/dismiss", response_model=ApiResponse[dict])
def monitor_subtask_snapshot_backfill_dismiss(
    subtask_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """忽略待补录：保留答案与排名，退出待补列表并不再提醒。"""
    require_platform(current, detail=_MONITOR_PLATFORM_DETAIL)
    try:
        require_snapshot_backfill_permission(db, current, "can_update")
        data = dismiss_snapshot_backfill(db, subtask_id=subtask_id, current=current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="monitor.snapshot_backfill_dismiss")
    return ApiResponse(data=data)


@router.post("/subtasks/{subtask_id}/snapshot-backfill/undismiss", response_model=ApiResponse[dict])
def monitor_subtask_snapshot_backfill_undismiss(
    subtask_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """取消忽略：若仍待补录则回列表并重新发出通知。"""
    require_platform(current, detail=_MONITOR_PLATFORM_DETAIL)
    try:
        require_snapshot_backfill_permission(db, current, "can_update")
        data = undismiss_snapshot_backfill(db, subtask_id=subtask_id, current=current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="monitor.snapshot_backfill_undismiss")
    return ApiResponse(data=data)


@router.get("/subtasks/{subtask_id}", response_model=ApiResponse[dict])
def monitor_subtask_detail(
    subtask_id: str,
    include_ops: bool = Query(default=False),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Query a single subtask with full answer content and references."""
    try:
        subtask = get_monitor_subtask(db, subtask_id, current)
        task = get_monitor_task(db, subtask.task_id, current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = _keyword_groups_for_tenant(db, task.tenant_id)
    display = serialize_subtask_for_display(
        subtask,
        monitor_keywords=task.monitor_keywords,
        asset=asset,
        keyword_groups=groups,
    )
    if not include_ops:
        return ApiResponse(data=display)
    if current.identity.identity_type == "PLATFORM":
        try:
            require_snapshot_backfill_permission(db, current, "can_export")
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    ops_meta = build_snapshot_backfill_item(db, subtask, task)
    # display 的 page_screenshot 已代理；ops_meta 同字段不得用库内原文覆盖
    merged = {**ops_meta, **display}
    return ApiResponse(data=merged)


def _resolve_schedule_tenant_scope(
    db: Session,
    current: CurrentSession,
    tenant_id: int | None,
) -> tuple[int | None, list[int] | None]:
    """销售账号未指定 tenant 时限定为负责企业；客户账号固定自身 tenant。"""
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id, None
    require_platform(current, detail=_MONITOR_PLATFORM_DETAIL)
    owned = sales_owned_tenant_ids(db, current)
    if tenant_id is not None:
        ensure_sales_tenant_access(db, current, tenant_id)
        return tenant_id, None
    if owned is not None:
        return None, owned
    return None, None


@router.get("/scheduled/preview", response_model=ApiResponse[list[dict]])
def scheduled_monitor_preview(
    tenant_id: int | None = None,
    max_prompts: int = 50,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """预览企业定时监测会提交的问题和模型平台，不调用模力指数接口。"""
    try:
        scoped_tenant_id, scoped_tenant_ids = _resolve_schedule_tenant_scope(db, current, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ApiResponse(data=preview_scheduled_tasks(
        db,
        tenant_id=scoped_tenant_id,
        tenant_ids=scoped_tenant_ids,
        max_prompts=max_prompts,
    ))


@router.post("/scheduled/run-due", response_model=ApiResponse[list[dict]])
def scheduled_monitor_run_due(
    tenant_id: int | None = None,
    limit: int = 10,
    max_prompts: int = 50,
    force: bool = False,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """执行到期的企业定时监测任务；force=true 用于人工立即执行一次。"""
    try:
        scoped_tenant_id, scoped_tenant_ids = _resolve_schedule_tenant_scope(db, current, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if force and not has_identity_menu_permission(
        db, current.identity.id, "platform.audit.schedule", "can_update"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权强制执行定时监测")
    try:
        result = run_due_scheduled_tasks(
            db,
            current,
            tenant_id=scoped_tenant_id,
            tenant_ids=scoped_tenant_ids,
            limit=limit,
            max_prompts=max_prompts,
            force=force,
        )
    except MolizhishuApiError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=molizhishu_upstream_error_detail(exc),
        ) from exc
    except (OperationalError, TimeoutError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列暂时不可用，请稍后重试",
        ) from exc
    return ApiResponse(data=result)


@router.get("/tasks/{task_id}", response_model=ApiResponse[dict])
def monitor_task_detail(
    task_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """查询本地任务详情；这里不请求模力指数远端接口。"""
    try:
        task = get_monitor_task(db, task_id, current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    return ApiResponse(data={
        "task": serialize_task(task, schedule_run=schedule_run, asset=asset),
        "subtasks": _serialize_task_subtasks(db, task, current),
    })


@router.post("/tasks/{task_id}/sync", response_model=ApiResponse[dict])
def monitor_task_sync(
    task_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """手动同步远端任务状态和已完成结果；只有这个接口会主动请求 status/result。"""
    from app.core.redis_client import redis_lock

    with redis_lock(f"sync-task:{task_id}", ttl_seconds=600) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该任务正在同步中，请稍后重试",
            )
        try:
            task = sync_monitor_task(db, task_id, current)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except MolizhishuApiError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=molizhishu_upstream_error_detail(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return ApiResponse(data={"task": serialize_task(task), "subtasks": _serialize_task_subtasks(db, task, current)})
