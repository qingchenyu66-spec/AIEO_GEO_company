"""数据分析API——词云、竞品对比。"""

from collections import Counter
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error
from app.core.database import get_db
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.common import ApiResponse
from app.services.competitor_analytics_service import build_competitor_compare_summary
from app.services.monitor_service import customer_display_cutoff
from app.services.sentiment_keyword_service import build_sentiment_keywords
from app.services.tenant_scope import resolve_and_guard_analytics_tenant

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
    prompt: str | None = None,
    limit: int = Query(default=80, ge=1, le=120),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """品牌情绪词——按正/负面回答提取短语，供词云展示与快照下钻。"""
    try:
        data = build_sentiment_keywords(
            db,
            current,
            tenant_id=tenant_id,
            platform=platform,
            platforms=platforms,
            days=days,
            prompt=prompt,
            limit=limit,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.sentiment_keywords")


@router.get("/competitor-compare", response_model=ApiResponse[dict])
def competitor_compare(
    tenant_id: int | None = None,
    platform: str | None = None,
    platforms: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    prompt: str | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """品牌洞察——提及率/排名/情绪趋势及竞品对比。"""
    try:
        data = build_competitor_compare_summary(
            db,
            current,
            tenant_id=tenant_id,
            platform=platform,
            platforms=platforms,
            days=days,
            prompt=prompt,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="analytics.competitor_compare")
