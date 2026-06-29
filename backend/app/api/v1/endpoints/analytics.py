"""数据分析API——词云、情感趋势、竞品对比。"""

from collections import Counter
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/analytics")

# 中文停用词表（精简版）
_STOP_WORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 什么 怎么 哪 为什么 可以 因为 所以 但是 如果 虽然 而且 还是 只是 已经 比较 非常 一起 需要 可能 应该 或者 然后 不过 其实 目前 根据 方面 通过 进行 使用 以及 一些 更加 相关 存在 包括 不同 主要 关于 其中 对于 同时 问题 情况 内容 结果 信息 用户 数据 功能 服务 产品 公司 企业 品牌 提供 是否 如何 这样 那样 那样 之后 以前 之后 以后 之前 之中 之外 之内".split()
)


def _extract_keywords(text: str, top_n: int = 100) -> list[dict]:
    """从文本中提取关键词及词频，过滤停用词和短词。"""
    if not text:
        return []
    # 提取中文字符序列
    words = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    counter: Counter[str] = Counter()
    for w in words:
        if w not in _STOP_WORDS and len(w) >= 2:
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
    stmt = select(GeoMonitorSubtask.answer_content).where(
        GeoMonitorSubtask.answer_content.isnot(None),
        GeoMonitorSubtask.answer_content != "",
    )
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            return ApiResponse(data=[])
        tenant_id = current.identity.tenant_id

    if tenant_id:
        task_ids_sub = select(GeoMonitorTask.task_id).where(
            GeoMonitorTask.tenant_id == tenant_id, GeoMonitorTask.deleted.is_(False)
        )
        stmt = stmt.where(GeoMonitorSubtask.task_id.in_(task_ids_sub))
    if task_id:
        stmt = stmt.where(GeoMonitorSubtask.task_id == task_id)

    stmt = stmt.limit(limit)
    rows = db.execute(stmt).all()

    combined = " ".join(row[0] for row in rows if row[0])
    keywords = _extract_keywords(combined)
    return ApiResponse(data=keywords)


@router.get("/sentiment-trends", response_model=ApiResponse[list[dict]])
def sentiment_trends(
    tenant_id: int | None = None,
    days: int = Query(default=30, ge=1, le=365),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """情感趋势——按天统计正/中/负数量。"""
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            return ApiResponse(data=[])
        tenant_id = current.identity.tenant_id

    since = datetime.utcnow() - timedelta(days=days)
    stmt = select(
        sa_func.date(GeoMonitorSubtask.updated_at).label("day"),
        GeoMonitorSubtask.sentiment,
        sa_func.count(GeoMonitorSubtask.id).label("cnt"),
    ).where(
        GeoMonitorSubtask.updated_at >= since,
        GeoMonitorSubtask.sentiment.isnot(None),
        GeoMonitorSubtask.sentiment != "",
    )

    if tenant_id:
        task_ids_sub = select(GeoMonitorTask.task_id).where(
            GeoMonitorTask.tenant_id == tenant_id, GeoMonitorTask.deleted.is_(False)
        )
        stmt = stmt.where(GeoMonitorSubtask.task_id.in_(task_ids_sub))

    stmt = stmt.group_by(sa_func.date(GeoMonitorSubtask.updated_at), GeoMonitorSubtask.sentiment).order_by(
        sa_func.date(GeoMonitorSubtask.updated_at).desc()
    )
    rows = db.execute(stmt).all()

    # 按天聚合
    day_map: dict[str, dict[str, int]] = {}
    for day, sentiment, cnt in rows:
        day_str = str(day)
        if day_str not in day_map:
            day_map[day_str] = {"positive": 0, "neutral": 0, "negative": 0}
        s = (sentiment or "").lower()
        if s in ("positive", "正面", "积极"):
            day_map[day_str]["positive"] += cnt
        elif s in ("negative", "负面", "消极"):
            day_map[day_str]["negative"] += cnt
        else:
            day_map[day_str]["neutral"] += cnt

    result = [{"date": d, **counts} for d, counts in sorted(day_map.items())]
    return ApiResponse(data=result)


@router.get("/competitor-compare", response_model=ApiResponse[list[dict]])
def competitor_compare(
    tenant_id: int | None = None,
    platform: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """竞品对比——各竞品在不同平台的排名/曝光/提及。"""
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            return ApiResponse(data=[])
        tenant_id = current.identity.tenant_id

    stmt = select(
        GeoMonitorSubtask.platform,
        GeoMonitorSubtask.competitor_rankings_json,
        GeoMonitorSubtask.all_rankings_json,
        GeoMonitorSubtask.mention_context,
        GeoMonitorSubtask.updated_at,
    ).where(
        GeoMonitorSubtask.competitor_rankings_json.isnot(None),
    )

    if tenant_id:
        task_ids_sub = select(GeoMonitorTask.task_id).where(
            GeoMonitorTask.tenant_id == tenant_id, GeoMonitorTask.deleted.is_(False)
        )
        stmt = stmt.where(GeoMonitorSubtask.task_id.in_(task_ids_sub))
    if platform:
        stmt = stmt.where(GeoMonitorSubtask.platform == platform)

    stmt = stmt.order_by(GeoMonitorSubtask.updated_at.desc()).limit(limit)
    rows = db.execute(stmt).all()

    result = []
    for platform_val, rankings, all_rankings, mention, updated_at in rows:
        item: dict = {
            "platform": platform_val,
            "competitor_rankings": rankings,
            "all_rankings": all_rankings,
            "mention_context": mention,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }
        result.append(item)
    return ApiResponse(data=result)
