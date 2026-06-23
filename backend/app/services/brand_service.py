from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset, BrandCompetitor
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
            schedule_times_json=[],
            schedule_weekdays_json=[],
            schedule_month_days_json=[],
        )
        db.add(asset)
    asset.company_full_name = payload.company_full_name
    asset.brand_name = payload.brand_name
    asset.brand_short_name = payload.brand_short_name
    asset.monitor_keywords_json = _dedupe([payload.brand_name, payload.brand_short_name, *payload.monitor_keywords])
    asset.aliases_json = _dedupe([payload.brand_short_name, *payload.aliases])
    asset.product_keywords_json = _dedupe(payload.product_keywords)
    asset.official_url = payload.official_url
    asset.description = payload.description
    asset.schedule_type = payload.schedule_type
    asset.schedule_times_json = _dedupe(payload.schedule_times)
    asset.schedule_frequency = payload.schedule_frequency
    asset.schedule_weekdays_json = _int_dedupe(payload.schedule_weekdays, 1, 7)
    asset.schedule_month_days_json = _int_dedupe(payload.schedule_month_days, 1, 31)
    asset.status = True
    asset.deleted = False
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


def asset_to_dict(asset: BrandAsset | None) -> dict[str, Any] | None:
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


def molizhishu_brand_payload(db: Session, tenant_id: int) -> tuple[str, list[str], list[dict[str, Any]]]:
    """把企业品牌资产转换为模力指数 monitorKeywords、aliases、competitors。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise ValueError("当前企业未配置品牌资产，请先维护品牌主词和简称")
    monitor_keyword = asset.brand_name
    aliases = _dedupe([asset.company_full_name, asset.brand_short_name, *asset.monitor_keywords_json, *asset.aliases_json])
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
