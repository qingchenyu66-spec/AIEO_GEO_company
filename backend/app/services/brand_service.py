from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup
from app.models.tenant import Tenant
from app.schemas.brand import BrandAssetSaveRequest, CompetitorSaveRequest


def resolve_tenant_id(current: CurrentSession, requested_tenant_id: int | None) -> int:
    """平台端可指定企业；客户端强制使用当前身份绑定企业。"""
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise ValueError("当前客户身份未绑定企业")
        return current.identity.tenant_id
    if requested_tenant_id is None:
        raise ValueError("平台端需要指定企业")
    return requested_tenant_id


def ensure_tenant(db: Session, tenant_id: int) -> Tenant:
    """确认企业存在且未删除。"""
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    return tenant


def get_brand_asset(db: Session, tenant_id: int) -> BrandAsset | None:
    """读取企业品牌资产配置。"""
    return db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))


def list_keyword_groups(db: Session, tenant_id: int) -> list[BrandKeywordGroup]:
    """读取企业监测词组，按排序稳定返回。"""
    return list(
        db.scalars(
            select(BrandKeywordGroup)
            .where(BrandKeywordGroup.tenant_id == tenant_id, BrandKeywordGroup.deleted.is_(False))
            .order_by(BrandKeywordGroup.sort_order.asc(), BrandKeywordGroup.id.asc())
        )
    )


def _fallback_keyword_groups(asset: BrandAsset) -> list[dict[str, Any]]:
    """旧数据没有词组表时，用旧字段临时拼出一组可用关系。"""
    monitor_keywords = _dedupe([asset.company_full_name, asset.brand_name, asset.brand_short_name, *(asset.monitor_keywords_json or [])])
    aliases = _dedupe([asset.brand_short_name, *(asset.aliases_json or [])])
    result: list[dict[str, Any]] = []
    for index, keyword in enumerate(monitor_keywords):
        result.append({
            "id": None,
            "tenant_id": asset.tenant_id,
            "monitor_keyword": keyword,
            "exposure_terms": aliases if index == 0 else [keyword],
            "sort_order": index,
            "status": True,
        })
    return result


def keyword_group_to_dict(group: BrandKeywordGroup) -> dict[str, Any]:
    """序列化监测词组。"""
    return {
        "id": group.id,
        "tenant_id": group.tenant_id,
        "monitor_keyword": group.monitor_keyword,
        "exposure_terms": group.exposure_terms_json or [],
        "sort_order": group.sort_order,
        "status": group.status,
    }


def save_keyword_groups(db: Session, asset: BrandAsset, payload: BrandAssetSaveRequest) -> None:
    """用前端提交的词组覆盖当前企业词组。"""
    existing = {item.id: item for item in list_keyword_groups(db, asset.tenant_id)}
    seen_ids: set[int] = set()
    source_groups = payload.keyword_groups
    if not source_groups:
        source_groups = [
            type("_Group", (), {"id": None, "monitor_keyword": keyword, "exposure_terms": [keyword], "sort_order": index, "status": True})()
            for index, keyword in enumerate(_dedupe([payload.company_full_name, payload.brand_name, *payload.monitor_keywords]))
        ]
    for index, item in enumerate(source_groups):
        keyword = item.monitor_keyword.strip()
        if not keyword:
            continue
        group = existing.get(item.id) if item.id else None
        if group is None:
            group = BrandKeywordGroup(
                tenant_id=asset.tenant_id,
                brand_asset_id=asset.id,
                monitor_keyword=keyword,
                exposure_terms_json=[],
            )
            db.add(group)
        group.brand_asset_id = asset.id
        group.monitor_keyword = keyword
        group.exposure_terms_json = _dedupe(item.exposure_terms or [keyword])
        group.sort_order = item.sort_order if item.sort_order is not None else index
        group.status = item.status
        group.deleted = False
        if group.id:
            seen_ids.add(group.id)
    for group_id, group in existing.items():
        if group_id not in seen_ids:
            group.deleted = True


def save_brand_asset(db: Session, payload: BrandAssetSaveRequest, current: CurrentSession) -> BrandAsset:
    """新增或更新企业品牌资产。"""
    tenant_id = resolve_tenant_id(current, payload.tenant_id)
    ensure_tenant(db, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        asset = BrandAsset(
            tenant_id=tenant_id,
            company_full_name=payload.company_full_name,
            brand_name=payload.brand_name,
            brand_short_name=payload.brand_short_name,
            monitor_keywords_json=[],
            aliases_json=[],
            product_keywords_json=[],
            monitored_platforms_json=[],
            schedule_times_json=[],
            schedule_weekdays_json=[],
            schedule_month_days_json=[],
        )
        db.add(asset)
    asset.company_full_name = payload.company_full_name
    asset.brand_name = payload.brand_name
    asset.brand_short_name = payload.brand_short_name
    asset.monitor_keywords_json = _dedupe([payload.brand_name, payload.brand_short_name, *payload.monitor_keywords, *payload.product_keywords])
    asset.aliases_json = _dedupe([payload.brand_short_name, *payload.aliases])
    asset.product_keywords_json = []
    asset.monitored_platforms_json = _dedupe(payload.monitored_platforms)
    asset.region_code = payload.region_code.strip() if payload.region_code else None
    asset.official_url = payload.official_url
    asset.description = payload.description
    asset.schedule_type = payload.schedule_type
    asset.schedule_times_json = _dedupe(payload.schedule_times)
    asset.schedule_frequency = payload.schedule_frequency
    asset.schedule_weekdays_json = _int_dedupe(payload.schedule_weekdays, 1, 7)
    asset.schedule_month_days_json = _int_dedupe(payload.schedule_month_days, 1, 31)
    asset.status = True
    asset.deleted = False
    db.flush()
    save_keyword_groups(db, asset, payload)
    db.commit()
    db.refresh(asset)
    return asset


def list_competitors(db: Session, tenant_id: int) -> list[BrandCompetitor]:
    """读取企业竞品库。"""
    return list(
        db.scalars(
            select(BrandCompetitor)
            .where(BrandCompetitor.tenant_id == tenant_id, BrandCompetitor.deleted.is_(False))
            .order_by(BrandCompetitor.id.desc())
        )
    )


def save_competitor(db: Session, payload: CompetitorSaveRequest, current: CurrentSession, competitor_id: int | None = None) -> BrandCompetitor:
    """新增或更新竞品。"""
    tenant_id = resolve_tenant_id(current, payload.tenant_id)
    ensure_tenant(db, tenant_id)
    competitor = None
    if competitor_id is not None:
        competitor = db.scalar(
            select(BrandCompetitor).where(
                BrandCompetitor.id == competitor_id,
                BrandCompetitor.tenant_id == tenant_id,
                BrandCompetitor.deleted.is_(False),
            )
        )
        if competitor is None:
            raise ValueError("竞品不存在")
    if competitor is None:
        competitor = BrandCompetitor(tenant_id=tenant_id, name=payload.name, aliases_json=[])
        db.add(competitor)
    competitor.name = payload.name
    competitor.short_name = payload.short_name
    competitor.aliases_json = _dedupe([payload.short_name, *payload.aliases])
    competitor.website_url = payload.website_url
    competitor.category = payload.category
    competitor.status = True
    competitor.deleted = False
    db.commit()
    db.refresh(competitor)
    return competitor


def delete_competitor(db: Session, current: CurrentSession, competitor_id: int, tenant_id: int | None = None) -> None:
    """逻辑删除竞品。"""
    resolved_tenant_id = resolve_tenant_id(current, tenant_id)
    competitor = db.scalar(
        select(BrandCompetitor).where(
            BrandCompetitor.id == competitor_id,
            BrandCompetitor.tenant_id == resolved_tenant_id,
            BrandCompetitor.deleted.is_(False),
        )
    )
    if competitor is None:
        raise ValueError("竞品不存在")
    competitor.deleted = True
    db.commit()


def asset_to_dict(asset: BrandAsset | None, keyword_groups: list[BrandKeywordGroup] | None = None) -> dict[str, Any] | None:
    """序列化品牌资产。"""
    if asset is None:
        return None
    return {
        "id": asset.id,
        "tenant_id": asset.tenant_id,
        "company_full_name": asset.company_full_name,
        "brand_name": asset.brand_name,
        "brand_short_name": asset.brand_short_name,
        "monitor_keywords": asset.monitor_keywords_json,
        "aliases": asset.aliases_json,
        "product_keywords": asset.product_keywords_json,
        "monitored_platforms": asset.monitored_platforms_json,
        "keyword_groups": [keyword_group_to_dict(item) for item in (keyword_groups or [])],
        "region_code": asset.region_code,
        "official_url": asset.official_url,
        "description": asset.description,
        "schedule_type": asset.schedule_type,
        "schedule_times": asset.schedule_times_json,
        "schedule_frequency": asset.schedule_frequency,
        "schedule_weekdays": asset.schedule_weekdays_json,
        "schedule_month_days": asset.schedule_month_days_json,
    }


def competitor_to_dict(competitor: BrandCompetitor) -> dict[str, Any]:
    """序列化竞品。"""
    return {
        "id": competitor.id,
        "tenant_id": competitor.tenant_id,
        "name": competitor.name,
        "short_name": competitor.short_name,
        "aliases": competitor.aliases_json,
        "website_url": competitor.website_url,
        "category": competitor.category,
    }


def active_keyword_groups(db: Session, tenant_id: int) -> list[dict[str, Any]]:
    """返回启用词组；没有新表数据时回退到旧字段。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return []
    groups = [
        keyword_group_to_dict(item)
        for item in list_keyword_groups(db, tenant_id)
        if item.status and item.monitor_keyword
    ]
    return groups or _fallback_keyword_groups(asset)


def molizhishu_brand_payload(db: Session, tenant_id: int) -> tuple[str, list[str], list[dict[str, Any]]]:
    """把企业品牌资产转换为模力指数 monitorKeywords、aliases、competitors。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise ValueError("当前企业未配置品牌资产，请先维护品牌主词和简称")
    groups = active_keyword_groups(db, tenant_id)
    first_group = groups[0] if groups else None
    monitor_keyword = first_group["monitor_keyword"] if first_group else asset.brand_name
    aliases = _dedupe(first_group["exposure_terms"] if first_group else [asset.company_full_name, asset.brand_short_name, *asset.monitor_keywords_json, *asset.aliases_json])
    competitors = [
        {"name": item.name, "aliases": item.aliases_json}
        for item in list_competitors(db, tenant_id)
        if item.status and item.name
    ]
    return monitor_keyword, aliases, competitors


def _dedupe(values: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result


def _int_dedupe(values: list[int], min_value: int, max_value: int) -> list[int]:
    result: list[int] = []
    for value in values:
        if min_value <= value <= max_value and value not in result:
            result.append(value)
    return result
