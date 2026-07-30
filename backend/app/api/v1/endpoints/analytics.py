"""数据分析API——词云、竞品对比。"""

from collections import Counter
import re

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error
from app.core.database import get_db
from app.core.read_cache import (
    COMPETITOR_COMPARE_CACHE_TTL,
    SENTIMENT_KEYWORDS_CACHE_TTL,
    competitor_compare_cache_key,
    get_or_build_json_cache,
    sentiment_keywords_cache_key,
)
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.common import ApiResponse
from app.schemas.sentiment_wordcloud import (
    SentimentWordCloudImageRequest,
    SentimentWordCloudImageResponse,
)
from app.services.competitor_analytics_service import build_competitor_compare_summary
from app.services.monitor_service import build_source_analysis_summary, customer_display_cutoff
from app.services.sentiment_keyword_service import build_sentiment_keywords
from app.services.sentiment_wordcloud_image_service import generate_sentiment_wordcloud_image
from app.services.tenant_scope import resolve_and_guard_analytics_tenant
from app.services.menu_permission_service import has_identity_menu_permission

from app.core.chinese_stop_words import WORDCLOUD_STOP_WORDS

router = APIRouter(prefix="/analytics")


def _extract_keywords(text: str, top_n: int = 100) -> list[dict]:
    """从文本中提取关键词及词频，过滤停用词和短词。"""
    if not text:
        return []
    words = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    counter: Counter[str] = Counter()
    for w in words:
        if w not in WORDCLOUD_STOP_WORDS and len(w) >= 2:
            counter[w] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]


@router.get("/wordcloud", response_model=ApiResponse[list[dict]])
def wordcloud(
    tenant_id: int | None = None,
    task_id: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """从 subtask answer_content 提取关键词频率，用于词云展示。"""
    try:
        resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)
        stmt = select(GeoMonitorSubtask.answer_content).where(
            GeoMonitorSubtask.answer_content.isnot(None),
            GeoMonitorSubtask.answer_content != "",
        )
        if current.identity.identity_type == "CUSTOMER":
            cutoff = customer_display_cutoff()
            stmt = stmt.where(GeoMonitorSubtask.updated_at <= cutoff)

        task_ids_sub = select(GeoMonitorTask.task_id).where(
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.purpose == "geo",
        )
        stmt = stmt.where(GeoMonitorSubtask.task_id.in_(task_ids_sub))
        if task_id:
            stmt = stmt.where(GeoMonitorSubtask.task_id == task_id)

        stmt = stmt.limit(limit)
        rows = db.execute(stmt).all()
        combined = " ".join(row[0] for row in rows if row[0])
        keywords = _extract_keywords(combined)
        return ApiResponse(data=keywords)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.wordcloud")


@router.get("/sentiment-keywords", response_model=ApiResponse[dict])
def sentiment_keywords(
    tenant_id: int | None = None,
    platform: str | None = None,
    platforms: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    start_date: date | None = Query(default=None, description="起始日（含），客户侧不晚于昨日"),
    end_date: date | None = Query(default=None, description="截止日（含），客户侧不晚于昨日"),
    prompt: str | None = None,
    limit: int = Query(default=80, ge=1, le=120),
    llm: bool = Query(default=True, description="是否启用 DeepSeek 精修（默认开启；llm=0 仅规则抽词）"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """品牌情绪词——按正/负面回答提取短语，供词云展示与快照下钻。"""
    try:
        resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)
        cache_key = sentiment_keywords_cache_key(
            current.identity.identity_type,
            resolved_tenant_id,
            platform=platform,
            platforms=platforms,
            days=days,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            prompt=f"{prompt or 'all'}|llm={int(llm)}",
            limit=limit,
        )

        def build() -> dict:
            return build_sentiment_keywords(
                db,
                current,
                tenant_id=tenant_id,
                platform=platform,
                platforms=platforms,
                days=days,
                start_date=start_date,
                end_date=end_date,
                prompt=prompt,
                limit=limit,
                use_llm=llm,
            )

        data = get_or_build_json_cache(
            cache_key,
            build,
            ttl_seconds=SENTIMENT_KEYWORDS_CACHE_TTL,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.sentiment_keywords")


@router.post("/sentiment-wordcloud-image", response_model=ApiResponse[SentimentWordCloudImageResponse])
def sentiment_wordcloud_image(
    payload: SentimentWordCloudImageRequest,
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[SentimentWordCloudImageResponse]:
    """品牌情绪词云图——Python wordcloud 填充中国地图蒙版（参考优词云 fill 模式）。"""
    del current
    try:
        data = generate_sentiment_wordcloud_image(
            [item.model_dump() for item in payload.items],
            polarity=payload.polarity,
            width=payload.width,
            height=payload.height,
            max_words=payload.max_words,
        )
        return ApiResponse(data=SentimentWordCloudImageResponse.model_validate(data))
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.sentiment_wordcloud_image")


@router.get("/competitor-compare", response_model=ApiResponse[dict])
def competitor_compare(
    tenant_id: int | None = None,
    platform: str | None = None,
    platforms: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    start_date: date | None = Query(default=None, description="起始日（含），客户侧不晚于昨日"),
    end_date: date | None = Query(default=None, description="截止日（含），客户侧不晚于昨日"),
    prompt: str | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """品牌洞察——提及率/排名/情绪趋势及竞品对比。"""
    try:
        resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)
        cache_tenant = resolved_tenant_id if resolved_tenant_id is not None else "platform"
        cache_key = competitor_compare_cache_key(
            current.identity.identity_type,
            cache_tenant,
            platform=platform,
            platforms=platforms,
            days=days,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            prompt=prompt,
        )

        def _build() -> dict:
            return build_competitor_compare_summary(
                db,
                current,
                tenant_id=tenant_id,
                platform=platform,
                platforms=platforms,
                days=days,
                start_date=start_date,
                end_date=end_date,
                prompt=prompt,
            )

        data = get_or_build_json_cache(
            cache_key,
            _build,
            ttl_seconds=COMPETITOR_COMPARE_CACHE_TTL,
            lock_ttl_seconds=90,
            wait_seconds=3.0,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.competitor_compare")


@router.get("/source-stats", response_model=ApiResponse[dict])
def source_stats(
    tenant_id: int | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """信源分析页轻接口：信源聚合 + 引用趋势，不扫监测任务大表。"""
    try:
        if current.identity.identity_type == "CUSTOMER":
            if not has_identity_menu_permission(db, current.identity.id, "customer.sources", "can_export"):
                raise PermissionError("无权查看信源分析")
        else:
            if not (
                has_identity_menu_permission(db, current.identity.id, "platform.sources", "can_export")
                or has_identity_menu_permission(db, current.identity.id, "platform.audit.list", "can_export")
            ):
                raise PermissionError("无权查看信源分析")
        data = build_source_analysis_summary(db, current, tenant_id=tenant_id)
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.source_stats")
