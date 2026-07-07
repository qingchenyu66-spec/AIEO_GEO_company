"""报告中心——基于监测与诊断数据生成结构化报告。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.core.platform_order import sort_platform_items
from app.models.brand import BrandAsset
from app.models.diagnosis import BrandDiagnosis
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.report import GeoReport
from app.models.tenant import Tenant
from app.services.brand_service import active_keyword_groups, brand_exposure_terms, ensure_tenant, get_brand_asset, list_competitors, tenant_purchased_platforms
from app.services.monitor_service import TERMINAL_STATUSES, _is_valid_citation_source, _matched_source_keywords
from app.services.report_ai_service import enrich_report_narrative
from app.services.tenant_scope import ensure_sales_tenant_access, guard_tenant_resource_access, sales_owned_tenant_ids

REPORT_TYPE_LABELS = {
    "diagnosis": "企业诊断",
    "weekly": "监测周报",
    "monthly": "监测月报",
    "annual": "监测年报",
    "comparison": "对比报告",
    "periodic": "周期报告",
}

REPORT_STATUS_LABELS = {
    "draft": "草稿",
    "published": "已发布",
    "archived": "已归档",
}


def sanitize_display_text(value: str | None, fallback: str | None = None) -> str | None:
    """过滤历史乱码/占位符文本，避免页面上出现一串问号。"""
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    if "\ufffd" in text:
        return fallback
    question_marks = text.count("?") + text.count("？")
    if question_marks and question_marks >= max(3, len(text) // 2):
        return fallback
    return text


def _default_diagnosis_title(brand_name: str, report_type: str) -> str:
    del brand_name
    label = REPORT_TYPE_LABELS.get(report_type, "品牌诊断")
    return f"GEO {label}"


def _sanitize_report_content(content: dict[str, Any] | None, *, brand_name: str, report_type: str) -> dict[str, Any] | None:
    if not content:
        return content
    payload = dict(content)
    diagnosis = dict(payload.get("diagnosis") or {})
    fallback_title = _default_diagnosis_title(
        str(payload.get("brand_name") or brand_name or "品牌"),
        report_type,
    )
    diagnosis["diagnosis_title"] = sanitize_display_text(diagnosis.get("diagnosis_title"), fallback_title)
    payload["diagnosis"] = diagnosis
    return payload


def _tenant_brand_name(db: Session, tenant_id: int) -> str:
    asset = db.scalar(
        select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False))
    )
    if asset is None:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
        return tenant.name if tenant else f"企业{tenant_id}"
    return asset.brand_name or asset.company_full_name


def build_tenant_monitor_snapshot(db: Session, tenant_id: int) -> dict[str, Any]:
    """汇总企业监测数据，供报告生成与预览使用。"""
    asset = get_brand_asset(db, tenant_id)
    competitors = list_competitors(db, tenant_id)
    purchased_platforms = set(tenant_purchased_platforms(db, tenant_id, asset))

    task_rows = list(
        db.scalars(
            select(GeoMonitorTask)
            .where(GeoMonitorTask.tenant_id == tenant_id, GeoMonitorTask.deleted.is_(False))
            .order_by(GeoMonitorTask.id.desc())
            .limit(120)
        )
    )
    task_ids = [item.task_id for item in task_rows]
    subtasks: list[GeoMonitorSubtask] = []
    if task_ids:
        subtasks = list(
            db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(task_ids)))
        )

    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES]
    completed_ids = {item.id for item in completed}
    mentioned = [item for item in completed if item.mention_position is not None]
    top3 = [item for item in mentioned if item.mention_position is not None and item.mention_position <= 3]

    mention_rate = round(len(mentioned) / len(completed) * 100, 1) if completed else 0.0
    avg_rank = round(sum(item.mention_position for item in mentioned) / len(mentioned), 1) if mentioned else None
    top3_rate = round(len(top3) / len(completed) * 100, 1) if completed else 0.0

    sentiment_labels = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
        "正向": "正面",
        "中立": "中性",
        "负向": "负面",
    }
    sentiment_counts = {"正面": 0, "中性": 0, "负面": 0, "未知": 0}
    for item in completed:
        label = sentiment_labels.get(str(item.sentiment or "").strip().lower(), item.sentiment or "未知")
        if label not in sentiment_counts:
            label = "未知"
        sentiment_counts[label] += 1
    sentiment_total = sum(sentiment_counts.values()) or 1
    positive_rate = round(sentiment_counts["正面"] / sentiment_total * 100, 1)

    exposure_terms = brand_exposure_terms(asset, active_keyword_groups(db, tenant_id)) if asset else []
    platform_bucket: dict[str, dict[str, Any]] = {}
    source_map: dict[str, dict[str, Any]] = {}
    for item in subtasks:
        if purchased_platforms and item.platform not in purchased_platforms:
            continue
        bucket = platform_bucket.setdefault(
            item.platform,
            {"platform": item.platform, "total": 0, "completed": 0, "mentioned": 0, "rank_total": 0, "rank_count": 0},
        )
        bucket["total"] += 1
        if item.id in completed_ids:
            bucket["completed"] += 1
        if item.mention_position is not None:
            bucket["mentioned"] += 1
            bucket["rank_total"] += item.mention_position
            bucket["rank_count"] += 1
        if item.id in completed_ids:
            for source in item.reference_list_json or []:
                if not _is_valid_citation_source(source):
                    continue
                url = source.get("url") or source.get("site") or source.get("title")
                if not url:
                    continue
                if exposure_terms and not _matched_source_keywords(source, exposure_terms):
                    continue
                key = str(url).split("?")[0]
                row = source_map.setdefault(
                    key,
                    {"title": source.get("title") or source.get("site") or key, "url": url, "count": 0, "platforms": set()},
                )
                row["count"] += 1
                row["platforms"].add(item.platform)

    platform_stats = []
    for bucket in platform_bucket.values():
        total = bucket["total"] or 1
        platform_stats.append(
            {
                "platform": bucket["platform"],
                "total": bucket["total"],
                "completed": bucket["completed"],
                "mention_rate": round(bucket["mentioned"] / total * 100, 1),
                "avg_rank": round(bucket["rank_total"] / bucket["rank_count"], 1) if bucket["rank_count"] else None,
            }
        )
    platform_stats = sort_platform_items(platform_stats)

    top_sources = sorted(source_map.values(), key=lambda row: row["count"], reverse=True)[:8]
    for row in top_sources:
        row["platforms"] = sorted(row["platforms"])

    highlights: list[str] = []
    if mention_rate >= 50:
        highlights.append(f"品牌提及率 {mention_rate}%，在 AI 推荐中露出表现较好。")
    elif completed:
        highlights.append(f"品牌提及率 {mention_rate}%，仍有提升空间，建议加强权威信源布局。")
    if avg_rank is not None and avg_rank <= 3:
        highlights.append(f"平均推荐排名 #{avg_rank}，处于推荐列表前列。")
    elif avg_rank is not None:
        highlights.append(f"平均推荐排名 #{avg_rank}，可通过内容优化争取更靠前位置。")
    if top_sources:
        highlights.append(f"已识别 {len(source_map)} 个有效引用信源，高频站点可作为内容投放参考。")
    if competitors:
        highlights.append(f"报告纳入 {len(competitors)} 个竞品对比维度。")

    return {
        "brand_name": asset.brand_name if asset else None,
        "company_name": asset.company_full_name if asset else None,
        "competitor_count": len(competitors),
        "platform_count": len(purchased_platforms) or len(platform_bucket),
        "kpis": {
            "mention_rate": mention_rate,
            "avg_rank": avg_rank,
            "top3_rate": top3_rate,
            "positive_rate": positive_rate,
            "subtask_count": len(subtasks),
            "completed_count": len(completed),
            "source_count": len(source_map),
            "task_count": len(task_rows),
        },
        "sentiment_counts": sentiment_counts,
        "platform_stats": platform_stats,
        "top_sources": [
            {
                "title": row["title"],
                "url": row["url"],
                "count": row["count"],
                "platforms": row["platforms"],
            }
            for row in top_sources
        ],
        "highlights": highlights,
    }


def _serialize_report_row(report: GeoReport, tenant_name: str | None = None) -> dict[str, Any]:
    content = report.report_content_json or {}
    kpis = content.get("kpis") or {}
    diagnosis = content.get("diagnosis") or {}
    health_score = diagnosis.get("health_score") or kpis.get("health_score")
    return {
        "id": report.id,
        "tenant_id": report.tenant_id,
        "tenant_name": tenant_name,
        "report_title": report.report_title,
        "report_type": report.report_type,
        "report_type_label": REPORT_TYPE_LABELS.get(report.report_type, report.report_type),
        "status": report.status,
        "status_label": REPORT_STATUS_LABELS.get(report.status, report.status),
        "data_summary": report.data_summary,
        "health_score": health_score,
        "mention_rate": kpis.get("mention_rate"),
        "avg_rank": kpis.get("avg_rank"),
        "report_url": report.report_url,
        "ai_source": (content.get("ai_insights") or {}).get("source"),
        "created_by": report.created_by,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
    }


def _period_label_for_type(report_type: str, now: datetime) -> str:
    if report_type == "weekly":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        weekday = start.weekday()
        start = start.replace(day=start.day - weekday)
        return f"{start.strftime('%Y-%m-%d')} 至 {now.strftime('%Y-%m-%d')}"
    if report_type == "monthly":
        return now.strftime("%Y年%m月")
    if report_type == "annual":
        return f"{now.year} 年度"
    return f"截至 {now.strftime('%Y-%m-%d')}"


def _default_report_title(report_type: str, brand_name: str) -> str:
    del brand_name
    return {
        "diagnosis": "GEO 企业诊断报告",
        "weekly": "GEO 监测周报",
        "monthly": "GEO 监测月报",
        "annual": "GEO 监测年报",
        "comparison": "竞品对比报告",
        "periodic": "周期监测报告",
    }.get(report_type, "GEO 监测报告")


def _ensure_platform_operator(current: CurrentSession) -> None:
    if current.identity.identity_type != "PLATFORM":
        raise ValueError("无权操作")


def _check_report_access(db: Session, current: CurrentSession) -> None:
    from app.services.menu_permission_service import require_report_access

    require_report_access(db, current)


def _check_report_action(db: Session, current: CurrentSession, action: str) -> None:
    from app.services.menu_permission_service import require_report_permission

    require_report_permission(db, current, action)


def list_reports(db: Session, current: CurrentSession) -> list[dict[str, Any]]:
    _check_report_access(db, current)
    tenant_scope: int | None = None
    if current.identity.identity_type == "CUSTOMER":
        tenant_scope = current.identity.tenant_id
    stmt = select(GeoReport).where(GeoReport.deleted.is_(False)).order_by(desc(GeoReport.id)).limit(200)
    if tenant_scope:
        stmt = stmt.where(GeoReport.tenant_id == tenant_scope)
        stmt = stmt.where(GeoReport.status == "published")
    else:
        owned = sales_owned_tenant_ids(db, current)
        if owned is not None:
            if not owned:
                return []
            stmt = stmt.where(GeoReport.tenant_id.in_(owned))
    rows = list(db.scalars(stmt))
    tenant_ids = {row.tenant_id for row in rows if row.tenant_id}
    tenant_map = {
        item.id: item.name
        for item in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids), Tenant.deleted.is_(False)))
    } if tenant_ids else {}
    return [_serialize_report_row(row, tenant_map.get(row.tenant_id)) for row in rows]


def get_report_detail(db: Session, report_id: int, current: CurrentSession) -> dict[str, Any]:
    _check_report_access(db, current)
    report = db.scalar(select(GeoReport).where(GeoReport.id == report_id, GeoReport.deleted.is_(False)))
    if report is None:
        raise ValueError("报告不存在")
    if current.identity.identity_type == "CUSTOMER":
        if report.tenant_id != current.identity.tenant_id:
            raise ValueError("无权查看")
        if report.status != "published":
            raise ValueError("报告不存在")
    else:
        guard_tenant_resource_access(db, current, report.tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == report.tenant_id, Tenant.deleted.is_(False)))
    payload = _serialize_report_row(report, tenant.name if tenant else None)
    brand_name = str((report.report_content_json or {}).get("brand_name") or _tenant_brand_name(db, report.tenant_id))
    payload["report_content"] = _sanitize_report_content(
        report.report_content_json,
        brand_name=brand_name,
        report_type=report.report_type,
    )
    return payload


def generate_report(db: Session, payload: dict[str, Any], current: CurrentSession) -> dict[str, Any]:
    _check_report_action(db, current, "can_create")
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise ValueError("请指定企业")
    tenant_id = int(tenant_id)
    ensure_tenant(db, tenant_id)
    ensure_sales_tenant_access(db, current, tenant_id)

    diagnosis = db.scalar(
        select(BrandDiagnosis)
        .where(BrandDiagnosis.tenant_id == tenant_id, BrandDiagnosis.deleted.is_(False))
        .order_by(desc(BrandDiagnosis.id))
        .limit(1)
    )
    snapshot = build_tenant_monitor_snapshot(db, tenant_id)
    brand_name = snapshot.get("brand_name") or _tenant_brand_name(db, tenant_id)
    competitors = list_competitors(db, tenant_id)
    competitor_names = [item.name for item in competitors if item.name]
    kpis = dict(snapshot.get("kpis") or {})

    existing_diagnosis = None
    if diagnosis:
        existing_diagnosis = {
            "health_score": diagnosis.health_score,
            "sentiment_summary": diagnosis.sentiment_summary,
            "strength_points": diagnosis.strength_points,
            "weakness_points": diagnosis.weakness_points,
            "recommendation": diagnosis.recommendation,
            "diagnosis_title": diagnosis.diagnosis_title,
        }
        kpis["health_score"] = diagnosis.health_score

    report_type = str(payload.get("report_type") or "diagnosis")
    now = datetime.now()
    period_label = _period_label_for_type(report_type, now)

    highlights, diagnosis_block, ai_insights, kpis = enrich_report_narrative(
        brand_name=brand_name,
        company_name=snapshot.get("company_name"),
        report_type=report_type,
        period_label=period_label,
        snapshot=snapshot,
        competitor_names=competitor_names,
        existing_diagnosis=existing_diagnosis,
    )

    default_title = _default_report_title(report_type, brand_name)
    report_title = str(payload.get("report_title") or default_title).strip() or default_title

    diagnosis_block["diagnosis_title"] = sanitize_display_text(
        diagnosis_block.get("diagnosis_title"),
        _default_diagnosis_title(brand_name, report_type),
    )

    completed_count = kpis.get("completed_count") or 0
    data_summary = f"基于 {completed_count} 条已完成监测子任务 · {period_label}"

    content: dict[str, Any] = {
        "brand_name": brand_name,
        "company_name": snapshot.get("company_name"),
        "period_label": period_label,
        "generated_at": now.isoformat(),
        "kpis": kpis,
        "diagnosis": diagnosis_block,
        "ai_insights": ai_insights,
        "monitor_snapshot": {
            "sentiment_counts": snapshot.get("sentiment_counts"),
            "platform_stats": snapshot.get("platform_stats"),
            "top_sources": snapshot.get("top_sources"),
            "highlights": highlights,
            "competitor_count": snapshot.get("competitor_count"),
            "platform_count": snapshot.get("platform_count"),
        },
    }

    report = GeoReport(
        tenant_id=tenant_id,
        report_title=report_title,
        report_type=report_type,
        status="draft",
        data_summary=data_summary,
        report_content_json=content,
        created_by=current.user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    return _serialize_report_row(report, tenant.name if tenant else None)


def update_report(db: Session, report_id: int, payload: dict[str, Any], current: CurrentSession) -> dict[str, Any]:
    _check_report_action(db, current, "can_update")
    report = db.scalar(select(GeoReport).where(GeoReport.id == report_id, GeoReport.deleted.is_(False)))
    if report is None:
        raise ValueError("报告不存在")
    guard_tenant_resource_access(db, current, report.tenant_id)

    if payload.get("report_title"):
        report.report_title = str(payload["report_title"]).strip() or report.report_title
    if "data_summary" in payload:
        report.data_summary = str(payload.get("data_summary") or "").strip() or None

    content = dict(report.report_content_json or {})
    if payload.get("executive_summary") is not None:
        ai_insights = dict(content.get("ai_insights") or {})
        ai_insights["executive_summary"] = str(payload.get("executive_summary") or "").strip() or None
        content["ai_insights"] = ai_insights

    diagnosis_patch = payload.get("diagnosis")
    if isinstance(diagnosis_patch, dict):
        diagnosis = dict(content.get("diagnosis") or {})
        for key in ("sentiment_summary", "strength_points", "weakness_points", "recommendation", "diagnosis_title"):
            if key in diagnosis_patch:
                diagnosis[key] = str(diagnosis_patch.get(key) or "").strip() or None
        content["diagnosis"] = diagnosis

    if payload.get("highlights") is not None:
        highlights = payload.get("highlights")
        if isinstance(highlights, str):
            highlights = [line.strip() for line in highlights.splitlines() if line.strip()]
        elif isinstance(highlights, list):
            highlights = [str(item).strip() for item in highlights if str(item).strip()]
        else:
            highlights = []
        snapshot = dict(content.get("monitor_snapshot") or {})
        snapshot["highlights"] = highlights
        content["monitor_snapshot"] = snapshot

    report.report_content_json = content
    db.commit()
    db.refresh(report)
    tenant = db.scalar(select(Tenant).where(Tenant.id == report.tenant_id, Tenant.deleted.is_(False)))
    result = _serialize_report_row(report, tenant.name if tenant else None)
    result["report_content"] = report.report_content_json
    return result


def publish_report(db: Session, report_id: int, current: CurrentSession) -> dict[str, Any]:
    _check_report_action(db, current, "can_update")
    report = db.scalar(select(GeoReport).where(GeoReport.id == report_id, GeoReport.deleted.is_(False)))
    if report is None:
        raise ValueError("报告不存在")
    guard_tenant_resource_access(db, current, report.tenant_id)
    report.status = "published"
    db.commit()
    db.refresh(report)
    tenant = db.scalar(select(Tenant).where(Tenant.id == report.tenant_id, Tenant.deleted.is_(False)))
    return _serialize_report_row(report, tenant.name if tenant else None)
