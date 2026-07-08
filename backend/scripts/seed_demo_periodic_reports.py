"""为指定企业注入模拟监测快照并生成已发布的周期报告（演示/验收用）。"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import desc, select

from app.core.database import SessionLocal
from app.models.report import GeoReport
from app.models.tenant import Tenant
from app.services.brand_service import ensure_tenant, get_brand_asset, list_competitors
from app.services.report_period_content_service import REPORT_MODULE_SCHEMA_VERSION
from app.services.report_period_service import bounds_from_period_key, period_bounds, period_key, period_label
from app.services.report_schedule_service import report_already_generated
from app.services.report_service import (
    _serialize_report_row,
    compose_tenant_diagnosis_report_bundle,
    generate_scheduled_report_for_tenant,
    refresh_diagnosis_report_for_tenant,
    refresh_scheduled_report_for_tenant,
)

DEFAULT_TENANT_CODE = "AIDIYA_REAL"
REPORT_TYPES = ("weekly", "monthly", "quarterly", "annual")

ANCHOR_OFFSETS = {
    "weekly": lambda today: _last_friday(today),
    "monthly": lambda today: _last_month_end(today),
    "quarterly": lambda today: _last_quarter_end(today),
    "annual": lambda today: date(today.year - 1, 12, 31),
}


def _last_friday(today: date) -> date:
    weekday = today.weekday()
    days_since_friday = (weekday - 4) % 7
    if days_since_friday == 0 and today.weekday() == 4:
        return today
    return today - timedelta(days=days_since_friday or 7)


def _last_month_end(today: date) -> date:
    first_this_month = today.replace(day=1)
    return first_this_month - timedelta(days=1)


def _last_quarter_end(today: date) -> date:
    month = today.month
    quarter_end_month = ((month - 1) // 3) * 3
    if quarter_end_month == 0:
        return date(today.year - 1, 12, 31)
    return date(today.year, quarter_end_month, 1) - timedelta(days=1)


def _resolve_tenant_id(db, *, tenant_id: int | None, tenant_code: str | None) -> int:
    if tenant_id is not None:
        ensure_tenant(db, tenant_id)
        return tenant_id
    code = tenant_code or DEFAULT_TENANT_CODE
    row = db.scalar(select(Tenant.id).where(Tenant.code == code, Tenant.deleted.is_(False)))
    if row is None:
        raise ValueError(f"未找到企业 code={code}")
    return row


def build_demo_monitor_snapshot(
    db,
    tenant_id: int,
    report_type: str,
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    asset = get_brand_asset(db, tenant_id)
    brand_name = (asset.brand_name if asset else None) or _tenant_brand_name(db, tenant_id)
    company_name = asset.company_full_name if asset else brand_name
    competitors = list_competitors(db, tenant_id)
    competitor_count = len(competitors)

    profiles: dict[str, dict[str, Any]] = {
        "weekly": {
            "completed": 42,
            "mention_rate": 61.9,
            "avg_rank": 2.4,
            "top3_rate": 47.6,
            "positive_rate": 72.0,
            "health_score": 78,
        },
        "monthly": {
            "completed": 168,
            "mention_rate": 58.3,
            "avg_rank": 2.7,
            "top3_rate": 44.0,
            "positive_rate": 69.5,
            "health_score": 76,
        },
        "quarterly": {
            "completed": 486,
            "mention_rate": 55.8,
            "avg_rank": 2.9,
            "top3_rate": 41.2,
            "positive_rate": 67.0,
            "health_score": 74,
        },
        "annual": {
            "completed": 1920,
            "mention_rate": 57.1,
            "avg_rank": 2.8,
            "top3_rate": 42.5,
            "positive_rate": 68.2,
            "health_score": 75,
        },
    }
    profile = profiles.get(report_type, profiles["monthly"])
    label = period_label(report_type, period_start, period_end)
    per_platform = max(1, profile["completed"] // 3)

    platform_stats = [
        {"platform": "doubao", "total": per_platform, "completed": per_platform, "mention_rate": 62.0, "avg_rank": 2.2},
        {"platform": "kimi", "total": per_platform, "completed": per_platform, "mention_rate": 57.5, "avg_rank": 2.6},
        {"platform": "deepseek", "total": per_platform, "completed": per_platform, "mention_rate": 54.0, "avg_rank": 3.1},
    ]
    top_sources = [
        {"title": "知乎 - 行业选购指南", "url": "https://www.zhihu.com/question/demo-guide", "count": 12, "platforms": ["doubao", "kimi"]},
        {"title": "官方网站品牌介绍", "url": "https://example.com/brand", "count": 9, "platforms": ["doubao", "deepseek"]},
        {"title": "垂直行业媒体评测", "url": "https://example.com/review", "count": 7, "platforms": ["kimi"]},
    ]
    highlights = [
        f"统计周期 {label}，共完成 {profile['completed']} 条监测子任务（演示数据）。",
        f"品牌提及率 {profile['mention_rate']}%，平均推荐排名 #{profile['avg_rank']}。",
        f"Top3 露出率 {profile['top3_rate']}%，正面情绪占比 {profile['positive_rate']}%。",
    ]
    if competitor_count:
        highlights.append(f"纳入 {competitor_count} 个竞品维度横向对比。")

    completed = profile["completed"]
    return {
        "brand_name": brand_name,
        "company_name": company_name,
        "competitor_count": competitor_count,
        "platform_count": len(platform_stats),
        "kpis": {
            "mention_rate": profile["mention_rate"],
            "avg_rank": profile["avg_rank"],
            "top3_rate": profile["top3_rate"],
            "positive_rate": profile["positive_rate"],
            "health_score": profile["health_score"],
            "subtask_count": completed,
            "completed_count": completed,
            "source_count": 18,
            "task_count": max(8, completed // 6),
        },
        "sentiment_counts": {
            "正面": int(completed * 0.682),
            "中性": int(completed * 0.22),
            "负面": int(completed * 0.098),
        },
        "platform_stats": platform_stats,
        "top_sources": top_sources,
        "highlights": highlights,
        "demo_data": True,
    }


def _find_active_report(db, *, tenant_id: int, report_type: str, key: str) -> GeoReport | None:
    return db.scalar(
        select(GeoReport).where(
            GeoReport.tenant_id == tenant_id,
            GeoReport.report_type == report_type,
            GeoReport.period_key == key,
            GeoReport.deleted.is_(False),
        )
    )


def _release_archived_period_keys(db, *, tenant_id: int, report_type: str, key: str) -> int:
    """软删记录仍占用 uk_geo_report_tenant_type_period，释放 period_key 避免插入冲突。"""
    rows = list(
        db.scalars(
            select(GeoReport).where(
                GeoReport.tenant_id == tenant_id,
                GeoReport.report_type == report_type,
                GeoReport.period_key == key,
                GeoReport.deleted.is_(True),
            )
        )
    )
    for row in rows:
        row.period_key = None
    if rows:
        db.commit()
    return len(rows)


def _mark_demo_content(db, report_id: int) -> None:
    report = db.scalar(select(GeoReport).where(GeoReport.id == report_id))
    if report is None:
        return
    content = dict(report.report_content_json or {})
    content["demo_data"] = True
    report.report_content_json = content
    db.commit()


def _upsert_demo_report(
    db,
    *,
    tenant_id: int,
    report_type: str,
    start: date,
    end: date,
    key: str,
    force: bool,
) -> dict[str, Any] | None:
    existing = _find_active_report(db, tenant_id=tenant_id, report_type=report_type, key=key)
    if existing and not force:
        return None

    snapshot = build_demo_monitor_snapshot(
        db,
        tenant_id,
        report_type,
        period_start=start,
        period_end=end,
    )
    generated_at = datetime.combine(end, time(hour=20, minute=0))

    if existing:
        row = refresh_scheduled_report_for_tenant(
            db,
            report_id=existing.id,
            period_start=start,
            period_end=end,
            generated_at=generated_at,
            snapshot_override=snapshot,
        )
        if row:
            _mark_demo_content(db, row["id"])
            row["refreshed"] = True
        return row

    released = _release_archived_period_keys(db, tenant_id=tenant_id, report_type=report_type, key=key)
    if released:
        print(f"  released {released} archived period_key for {report_type} {key}")

    row = generate_scheduled_report_for_tenant(
        db,
        tenant_id=tenant_id,
        report_type=report_type,
        period_start=start,
        period_end=end,
        period_key=key,
        generated_at=generated_at,
        snapshot_override=snapshot,
    )
    if row:
        _mark_demo_content(db, row["id"])
    return row


def purge_tenant_reports(db, *, tenant_id: int) -> int:
    """软删企业全部报告并释放 period_key（避免唯一索引占用）。"""
    rows = list(
        db.scalars(
            select(GeoReport).where(
                GeoReport.tenant_id == tenant_id,
                GeoReport.deleted.is_(False),
            )
        )
    )
    for row in rows:
        row.deleted = True
        row.period_key = None
    if rows:
        db.commit()
    return len(rows)


def create_demo_diagnosis_report(db, *, tenant_id: int) -> dict[str, Any] | None:
    """生成已发布的演示诊断报告（与售前诊断共用 aggregate_lead_diagnosis 链路）。"""
    try:
        bundle = compose_tenant_diagnosis_report_bundle(db, tenant_id)
    except ValueError as exc:
        print(f"SKIP diagnosis: {exc}")
        return None

    content = dict(bundle["content"])
    content["demo_data"] = True

    report = GeoReport(
        tenant_id=tenant_id,
        report_title=bundle["report_title"],
        report_type="diagnosis",
        status="published",
        period_key=None,
        data_summary=bundle["data_summary"],
        report_content_json=content,
        created_by=None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    return _serialize_report_row(report, tenant.name if tenant else None)


def refresh_all_existing_reports(db, *, tenant_id: int, report_types: list[str]) -> list[dict[str, Any]]:
    """刷新企业下所有已发布的周期/演示报告正文（保留原 id 与 period_key）。"""
    refreshed: list[dict[str, Any]] = []

    if "diagnosis" in report_types:
        diagnosis_rows = list(
            db.scalars(
                select(GeoReport).where(
                    GeoReport.tenant_id == tenant_id,
                    GeoReport.report_type == "diagnosis",
                    GeoReport.deleted.is_(False),
                    GeoReport.status == "published",
                ).order_by(GeoReport.id.asc())
            )
        )
        for report in diagnosis_rows:
            row = refresh_diagnosis_report_for_tenant(db, report_id=report.id, tenant_id=tenant_id)
            if row:
                _mark_demo_content(db, row["id"])
                refreshed.append(row)

    periodic_types = [item for item in report_types if item != "diagnosis"]
    if not periodic_types:
        return refreshed

    rows = list(
        db.scalars(
            select(GeoReport).where(
                GeoReport.tenant_id == tenant_id,
                GeoReport.report_type.in_(periodic_types),
                GeoReport.deleted.is_(False),
                GeoReport.status == "published",
            ).order_by(GeoReport.id.asc())
        )
    )
    for report in rows:
        content = dict(report.report_content_json or {})
        start: date | None = None
        end: date | None = None
        if content.get("period_start"):
            try:
                start = date.fromisoformat(str(content["period_start"])[:10])
            except ValueError:
                start = None
        if content.get("period_end"):
            try:
                end = date.fromisoformat(str(content["period_end"])[:10])
            except ValueError:
                end = None
        if start is None or end is None:
            bounds = bounds_from_period_key(report.report_type, str(report.period_key or ""))
            if bounds:
                start, end = bounds
        if start is None or end is None:
            print(f"SKIP id={report.id} {report.report_type} (cannot resolve period bounds)")
            continue

        snapshot = build_demo_monitor_snapshot(
            db,
            tenant_id,
            report.report_type,
            period_start=start,
            period_end=end,
        )
        row = refresh_scheduled_report_for_tenant(
            db,
            report_id=report.id,
            period_start=start,
            period_end=end,
            generated_at=datetime.combine(end, time(hour=20, minute=0)),
            snapshot_override=snapshot,
        )
        if row:
            _mark_demo_content(db, row["id"])
            refreshed.append(row)
    return refreshed


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo weekly/monthly/quarterly/annual reports")
    parser.add_argument("--tenant-id", type=int, default=None)
    parser.add_argument("--tenant-code", type=str, default=None, help=f"default {DEFAULT_TENANT_CODE}")
    parser.add_argument("--type", action="append", dest="types", choices=list(REPORT_TYPES))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing report for same period_key (in-place refresh, keeps report id)",
    )
    parser.add_argument(
        "--refresh-all",
        action="store_true",
        help="Refresh all published periodic reports for tenant (upgrade JSON/modules in DB)",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Soft-delete all existing reports for tenant before seeding",
    )
    parser.add_argument(
        "--with-diagnosis",
        action="store_true",
        help="Also generate a published demo diagnosis report",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant_id = _resolve_tenant_id(db, tenant_id=args.tenant_id, tenant_code=args.tenant_code)
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        today = date.today()
        types = args.types or list(REPORT_TYPES)
        created: list[dict[str, Any]] = []

        if args.purge:
            removed = purge_tenant_reports(db, tenant_id=tenant_id)
            print(f"PURGE removed {removed} reports for tenant_id={tenant_id}")
            args.force = True

        if args.refresh_all:
            refresh_types = list(types)
            if "diagnosis" not in refresh_types:
                refresh_types.append("diagnosis")
            refreshed = refresh_all_existing_reports(db, tenant_id=tenant_id, report_types=refresh_types)
            for row in refreshed:
                content = db.scalar(select(GeoReport.report_content_json).where(GeoReport.id == row["id"]))
                modules = (content or {}).get("report_modules") or {}
                schema = modules.get("schema_version")
                print(f"REFRESH id={row['id']} {row['report_type']} schema={schema}")
                created.append(row)
            print(f"\n已刷新 {len(refreshed)} 份报告 JSON（schema v{REPORT_MODULE_SCHEMA_VERSION}）。")
            return

        for report_type in types:
            anchor = ANCHOR_OFFSETS[report_type](today)
            start, end = period_bounds(report_type, anchor)
            key = period_key(report_type, start, end)
            if report_already_generated(db, tenant_id=tenant_id, report_type=report_type, key=key) and not args.force:
                print(f"SKIP {report_type} {key} (exists, use --force)")
                continue

            row = _upsert_demo_report(
                db,
                tenant_id=tenant_id,
                report_type=report_type,
                start=start,
                end=end,
                key=key,
                force=args.force,
            )
            if row:
                action = "REFRESH" if row.get("refreshed") else "OK"
                content = db.scalar(select(GeoReport.report_content_json).where(GeoReport.id == row["id"]))
                has_modules = bool((content or {}).get("report_modules"))
                print(f"{action} {report_type} id={row['id']} modules={has_modules} {row['report_title']}")
                created.append({"id": row["id"], "type": report_type, "title": row["report_title"], "period_key": key})
            else:
                print(f"FAIL {report_type} {key}")

        if args.with_diagnosis or args.purge:
            diag = create_demo_diagnosis_report(db, tenant_id=tenant_id)
            if diag:
                content = db.scalar(select(GeoReport.report_content_json).where(GeoReport.id == diag["id"]))
                has_modules = bool((content or {}).get("report_modules"))
                print(f"OK diagnosis id={diag['id']} modules={has_modules} {diag['report_title']}")
                created.append(diag)

        print(f"\n企业: {tenant.name if tenant else tenant_id} (id={tenant_id})")
        print(f"已处理 {len(created)} 份已发布报告，客户端报告中心可见。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
